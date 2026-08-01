# -*- coding: utf-8 -*-
"""build_upskill_brief 离线单测：维度分类 / 缺口聚合 / 热力图 / brief 渲染。"""
import json
import os
import sys
import tempfile

# 与 test_fetch_boss 同构：把 scripts/ 注入 path，便于 import
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import build_upskill_brief as bub  # noqa: E402


def test_classify_dimension():
    assert bub.classify_dimension("需要雅思 7 分") == "credential"
    assert bub.classify_dimension("要求 Python/Spark 经验") == "tooling"
    assert bub.classify_dimension("跨部门沟通与推动能力") == "soft"
    assert bub.classify_dimension("缺少电商行业业务理解") == "domain"
    assert bub.classify_dimension("搜索排序算法经验不足") == "hard"


def _decision_fixture():
    """构造一个含重复/近重复缺口、不同定位的 decision_context。"""
    return {
        "assessments": [
            {
                "title": "推荐算法工程师", "company": "美团", "tier": "A",
                "positioning": "stretch", "gaps": [
                    "缺少搜索排序/召回的工程经验",
                    "缺少搜索排序召回的工程经验",  # 近重复
                ],
            },
            {
                "title": "搜索工程师", "company": "字节", "tier": "A",
                "positioning": "match", "gaps": [
                    "缺少电商行业业务理解",
                    "要求 Python/Spark 经验不足",
                ],
            },
            {
                "title": "后端开发", "company": "阿里", "tier": "B",
                "positioning": "safe", "gaps": [
                    "跨部门沟通与推动能力较弱",
                ],
            },
        ],
    }


def test_aggregate_gaps_clusters_and_dedup():
    decision = _decision_fixture()
    clusters = bub.aggregate_gaps(decision)
    # 近重复的「搜索排序/召回」应合并为一个簇
    reps = [c["representative"] for c in clusters]
    assert any("搜索排序" in r for r in reps)
    # 不应出现两条几乎相同的搜索排序簇
    search_clusters = [c for c in clusters if "搜索排序" in c["representative"]]
    assert len(search_clusters) == 1
    sc = search_clusters[0]
    # 两条近重复表述同属「美团」一个岗位（stretch / A 档）
    assert sc["count"] == 1
    assert sc["tier_a"] == 1
    assert sc["stretch"] == 1
    # 维度应为 hard（搜索排序算法）
    assert sc["dimension"] == "hard"


def test_aggregate_gaps_dimension_tagging():
    decision = _decision_fixture()
    clusters = {c["representative"]: c for c in bub.aggregate_gaps(decision)}
    # 「电商行业业务理解」→ domain
    domain_c = next(c for c in clusters.values() if "电商" in c["representative"])
    assert domain_c["dimension"] == "domain"
    # 「跨部门沟通」→ soft
    soft_c = next(c for c in clusters.values() if "沟通" in c["representative"])
    assert soft_c["dimension"] == "soft"
    # 「Python/Spark」→ tooling
    tool_c = next(c for c in clusters.values() if "Python" in c["representative"])
    assert tool_c["dimension"] == "tooling"


def test_build_heatmap():
    decision = _decision_fixture()
    clusters = bub.aggregate_gaps(decision)
    hm = bub.build_heatmap(clusters)
    assert "维度" in hm and "优先级权重" in hm
    # 行数 = 表头2 + 簇数
    lines = [line for line in hm.splitlines() if line.startswith("|")]
    assert len(lines) == 2 + len(clusters)


def test_build_heatmap_empty():
    assert "无显著缺口" in bub.build_heatmap([])


def test_render_brief_contains_sections():
    decision = _decision_fixture()
    clusters = bub.aggregate_gaps(decision)
    heatmap = bub.build_heatmap(clusters)
    profile = {
        "direction_anchors": [{"text": "大厂算法", "weight": "high"}],
        "education": {"level": "本科", "school_tier": "985", "major": "计算机"},
        "core_experiences": {"L2": [{"text": "推荐系统项目"}], "L3": []},
        "hard_negatives": [{"text": "不做外包"}],
    }
    scored = {
        "pipeline": {"direction_anchor": "推荐→搜索迁移"},
        "recommendations": {"tier_A": [
            {"match_reasons": ["已有推荐系统经验", "基础扎实"]}
        ]},
    }
    brief = bub.render_brief(profile, scored, decision, clusters, heatmap)
    for sec in ["# 技能升级概览", "## 1. 当前定位", "## 2. 核心缺口",
                "## 3. 升级方向", "## 4. 约束", "## 5. 缺口热力图",
                "## 6. 喂给外部 AI 的指令"]:
        assert sec in brief
    # 已覆盖基础应含 profile 的 L2 经历
    assert "推荐系统项目" in brief
    # 方向锚点应含 profile 锚点；pipeline 的新增 token 也应出现（去重后）
    assert "大厂算法" in brief
    assert "推荐" in brief and "搜索迁移" in brief
    # 反向约束应含 hard_negatives
    assert "不做外包" in brief
    # 不应凭空塞具体课程名（保持「不生成课程计划」边界）
    assert "coursera" not in brief.lower() and "udemy" not in brief.lower()


def test_render_with_real_example_shape():
    """锁定真实 boundary_profile 形态：anchors 为字符串列表、core_experiences
    为含 evidence_level 的 dict 列表、education 为 degree/school/major。"""
    profile = {
        "role_type": "AI产品经理",
        "direction_anchors": ["AI自动化评测", "RAG知识检索", "AI标注平台"],
        "education": {"degree": "硕士", "school": "示例985高校", "major": "计算机"},
        "core_experiences": [
            {"what_i_did": "从0到1搭建评测平台", "evidence_level": "L2",
             "scenario": "x", "signal_words": ["y"]},
            {"what_i_did": "RAG检索方案设计", "evidence_level": "L3",
             "scenario": "x", "signal_words": ["y"]},
        ],
        "hard_negatives": ["纯前端开发", "游戏策划"],
    }
    scored = {"pipeline": {"direction_anchor": "Agent工作流"}, "recommendations": {"tier_A": []}}
    decision = {"assessments": [{
        "title": "推荐算法", "company": "美团", "tier": "A", "positioning": "stretch",
        "gaps": ["缺少搜索排序与召回的工程经验"],
    }]}
    clusters = bub.aggregate_gaps(decision, scored)
    heatmap = bub.build_heatmap(clusters)
    brief = bub.render_brief(profile, scored, decision, clusters, heatmap)
    assert "AI产品经理" in brief
    assert "硕士 / 示例985高校 / 计算机" in brief
    assert "从0到1搭建评测平台" in brief and "RAG检索方案设计" in brief
    assert "纯前端开发" in brief and "游戏策划" in brief
    # pipeline 仅补充新增 token（Agent工作流），不重复已列锚点
    assert "Agent工作流" in brief
    assert brief.count("AI自动化评测") == 1


def test_main_writes_files():
    decision = _decision_fixture()
    with tempfile.TemporaryDirectory() as td:
        dec_path = os.path.join(td, "decision.json")
        with open(dec_path, "w", encoding="utf-8") as f:
            json.dump(decision, f, ensure_ascii=False)
        out = os.path.join(td, "out")
        rc = bub.main(["--decision", dec_path, "--out-dir", out])
        assert rc == 0
        assert os.path.exists(os.path.join(out, "upskill_brief.md"))
        assert os.path.exists(os.path.join(out, "upskill_brief.json"))
        with open(os.path.join(out, "upskill_brief.json"), encoding="utf-8") as f:
            data = json.load(f)
        assert data["cluster_count"] >= 1


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
