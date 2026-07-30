#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_upskill_brief.py — 方向性缺口 / 升级概览生成器（refined upskill）

设计定位（与「全包式学习计划」划清界限）：
- 本工具**只**做「聚合 + 格式化」，不搜网络资源、不生成具体课程/书单/时间表。
- 输入是既有的匹配/竞争力产物（scored_results / decision_context / boundary_profile），
  把散点的「岗位视角缺口」聚合成「候选人视角的方向性缺口概览」。
- 输出的 upskill_brief.md 是**给外部 AI 的 prompt 输入**——用户把它贴给 AI，
  让 AI 据此产出专业的详细学习计划。工具本身不越俎代庖。

纯 stdlib 实现，无 LLM 依赖，离线可测（见 tests/test_build_upskill_brief.py）。

数据流：
    boundary_profile.json  ─┐
    scored_results.json    ─┼─→ aggregate ─→ cluster ─→ heatmap + brief
    decision_context.json  ─┘

用法：
    python scripts/build_upskill_brief.py \
        --profile   profile.boundary.json \
        --scored    scored_results.json \
        --decision  decision_context.json \
        --out-dir   out/
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 维度分类（启发式，确定性，可测）
# ---------------------------------------------------------------------------
# 优先级：credential > tooling > hard > soft > domain > (默认兜底 hard)
# 说明：hard 必须排在 soft/domain 之前，否则「搜索/推荐」等既是领域词又是技能词的
# 根词会先命中 domain；hard 只放**低歧义的具体技能词**（算法/系统/工程…），
# 不放大而化之的「经验/技能/能力」，避免与 soft 冲突。
DIMENSION_KEYWORDS = {
    "credential": [
        "证书", "学历", "资格", "认证", "英语", "雅思", "托福", "六级", "cet6",
        "cet-6", "cet4", "cet-4", "gmat", "gre", "学位", "毕业证", "资格证",
        "持证", "pmp", "cpa", "法律资格",
    ],
    "tooling": [
        "python", "java", "go", "golang", "c++", "cpp", "rust", "sql", "k8s",
        "kubernetes", "docker", "linux", "hadoop", "spark", "flink", "tensorflow",
        "pytorch", "torch", "redis", "kafka", "mysql", "postgres", "clickhouse",
        "hive", "elasticsearch", "git", "maven", "react", "vue", "spring",
        "工具", "框架", "平台", "生态", "技术栈", "sdk", "api", "中间件", "编排",
        "调度", "监控", "日志",
    ],
    "hard": [
        "算法", "系统", "架构", "工程", "模型", "排序", "召回", "检索", "训练",
        "推理", "部署", "分布式", "高并发", "并发", "性能", "调优", "开发", "编码",
        "设计", "后端", "前端", "数据", "实现", "机器学习", "深度学习", "优化",
        "迁移", "扩散", "大模型", "llm", "agent", "多模态",
    ],
    "soft": [
        "沟通", "协作", "领导", "管理", "表达", "抗压", "推动", "协调", "团队",
        "演讲", "汇报", "影响力", "ownership", "主动", "跨团队", "跨部门", "owner",
        "软技能", "人际", "冲突", "说服", "组织", "带人", "mentoring", "mentor",
        "自驱", "驱动", "owner意识", "项目管理", "leadership",
    ],
    "domain": [
        "业务", "行业", "领域", "场景", "电商", "金融", "配送", "物流", "风控",
        "推荐", "搜索", "广告", "国际化", "海外", "本地生活", "内容", "社交",
        "游戏", "出行", "外卖", "到店", "供应链", "交易", "支付", "增长", "变现",
        "tob", "to b", "toc", "to c", "b端", "c端", "产业", "行业理解", "domain",
        "商业模式", "用户增长", "方向", "赛道",
    ],
    # 兜底层（默认）：未命中任何关键词的技能/经验类缺口
}

_DIMENSION_ORDER = ["credential", "tooling", "hard", "soft", "domain"]
_DIMENSION_LABEL = {
    "hard": "hard技能",
    "domain": "domain领域",
    "soft": "soft软技能",
    "tooling": "tooling工具链",
    "credential": "credential证书",
}


def classify_dimension(text: str) -> str:
    """把一段缺口文字归类到 5 个维度之一（确定性启发式）。

    顺序见 _DIMENSION_ORDER：credential > tooling > hard > soft > domain。
    hard 在循环内作为普通维度参与匹配；仅当完全无关键词命中时兜底为 hard。
    """
    t = (text or "").lower()
    for dim in _DIMENSION_ORDER:
        for kw in DIMENSION_KEYWORDS[dim]:
            if kw in t:
                return dim
    return "hard"


# ---------------------------------------------------------------------------
# N6 本地资源索引（owner 自管，未联网）
# ---------------------------------------------------------------------------
RESOURCE_DIM_MATCHERS = [
    ("hard", ("hard", "硬")),
    ("soft", ("soft", "软")),
    ("tooling", ("tool", "工具")),
    ("domain", ("domain", "领域", "业务")),
    ("credential", ("credential", "证书", "学历")),
]


def load_resource_index(path: str | None) -> dict:
    """解析 resource-index.md：## 标题 下的 - [t](url) — note 收集为 dim->list。零网络。"""
    out = {d: [] for d, _ in RESOURCE_DIM_MATCHERS}
    if not path or not os.path.exists(path):
        return out
    cur = None
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("## "):
                head = s[3:].lower()
                cur = None
                for dim, keys in RESOURCE_DIM_MATCHERS:
                    if any(k in head for k in keys):
                        cur = dim
                        break
            elif s.startswith("- ") and cur:
                m = re.match(r"\[(.+?)\]\(([^)]*)\)\s*(?:—\s*(.*))?$", s[2:])
                if m:
                    out[cur].append((m.group(1).strip(), m.group(2).strip(),
                                     (m.group(3) or "").strip()))
    return out


def map_clusters_to_resources(clusters: list[dict], index: dict) -> dict:
    """把缺口簇按 dimension 映射到本地资源。返回 dim->list[(t, url, note)]。"""
    out: dict[str, list] = {}
    for cl in clusters:
        res = index.get(cl.get("dimension")) or []
        if res:
            out.setdefault(cl["dimension"], [])
            out[cl["dimension"]].extend(res)
    return out


# ---------------------------------------------------------------------------
# 缺口聚合
# ---------------------------------------------------------------------------
_SEVERITY_WEIGHT = {"stretch": 3, "match": 2, "safe": 1}
_TIER_WEIGHT = {"A": 2, "B": 1, "C": 1}


def normalize_gap(text: str) -> str:
    """归一化缺口字符串：去空白、去结尾标点，便于精确去重。"""
    s = (text or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip("。.；;，,、 ")
    return s


def tokenize(text: str) -> set:
    """极简分词：英文按词、中文按字。用于近重合并的 token 重叠计算。"""
    s = (text or "").lower()
    # 抽取英文/数字连续词
    tokens = set(re.findall(r"[a-z0-9]+", s))
    # 中文单字
    tokens |= set(re.findall(r"[一-鿿]", s))
    return tokens


def _token_overlap(a: str, b: str) -> float:
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def aggregate_gaps(decision_context: dict, scored_results: dict | None = None):
    """从 decision_context + scored 中收集缺口，聚合成带维度/严重度/频数的簇。

    返回 list[dict]，每个簇：
        {
          "representative": str,        # 代表表述（最长/信息量最大）
          "dimension": str,             # 主维度（按簇内计数最多）
          "dimensions": dict,           # 各维度计数
          "count": int,                 # 覆盖的不同岗位数
          "weight": int,                # 优先级权重（Σ severity×tier）
          "jobs": list[str],            # 命中岗位（title@company）
          "tier_a": int,                # 命中 A 档岗位数
          "stretch": int,               # 命中 stretch 岗位数
          "sources": list[str],         # 原始表述去重列表
        }
    """
    # (normalized) -> 草稿；按「岗位」维度记账，避免同岗多条近重复表述重复计数
    raw: dict[str, dict] = {}

    assessments = (decision_context or {}).get("assessments", [])
    for a in assessments:
        tier = str(a.get("tier", "B")).upper()
        pos = str(a.get("positioning", "match")).lower()
        job_label = f"{a.get('title', '?')}@{a.get('company', '?')}"
        for g in a.get("gaps", []) or []:
            ng = normalize_gap(g)
            if not ng:
                continue
            dim = classify_dimension(ng)
            if ng not in raw:
                raw[ng] = {
                    "texts": set(),
                    "job_labels": set(),
                    "jobs_meta": {},   # job_label -> (tier, positioning)
                    "dim_counter": Counter(),
                }
            c = raw[ng]
            c["texts"].add(ng)
            c["job_labels"].add(job_label)
            c["jobs_meta"][job_label] = (tier, pos)
            c["dim_counter"][dim] += 1

    # 近重合并（同维度 + token 重叠 >= 0.5）
    clusters = []
    for ng, c in raw.items():
        merged = False
        for cl in clusters:
            # 仅当维度一致且表述 token 重叠足够才合并（近重复缺口）
            if _same_dimension(cl, c) and _token_overlap(cl["representative"], ng) >= 0.5:
                _merge_into(cl, ng, c)
                merged = True
                break
        if not merged:
            clusters.append(_finalize_cluster(ng, c))

    # 按优先级权重降序；同权重按覆盖岗位数降序
    clusters.sort(key=lambda x: (x["weight"], x["count"]), reverse=True)
    return clusters


def _finalize_cluster(ng: str, c: dict) -> dict:
    """从草稿算出簇的最终字段（count/tier_a/stretch/weight 均按「岗位」去重）。"""
    jobs_meta = c["jobs_meta"]
    tier_a = sum(1 for (t, _p) in jobs_meta.values() if t == "A")
    stretch = sum(1 for (_t, p) in jobs_meta.values() if p == "stretch")
    # 权重 = Σ(岗位严重度 × 岗位档位)，每个岗位只计一次（避免同岗多表述膨胀）
    weight = sum(
        _SEVERITY_WEIGHT.get(p, 2) * _TIER_WEIGHT.get(t, 1)
        for (t, p) in jobs_meta.values()
    )
    primary_dim = c["dim_counter"].most_common(1)[0][0]
    return {
        "representative": ng,
        "dimension": primary_dim,
        "dimensions": dict(c["dim_counter"]),
        "count": len(c["job_labels"]),
        "weight": weight,
        "jobs": sorted(c["job_labels"]),
        "tier_a": tier_a,
        "stretch": stretch,
        "sources": sorted(c["texts"]),
    }


def _same_dimension(cl: dict, c: dict) -> bool:
    cl_dim = cl["dimension"]
    c_dim = c["dim_counter"].most_common(1)[0][0]
    return cl_dim == c_dim


def _merge_into(cl: dict, ng: str, c: dict) -> None:
    """把一个草稿合并进已有簇（字段均以「岗位」去重，不重复计数）。"""
    cl["sources"] = sorted(set(cl["sources"]) | c["texts"])
    cl["jobs"] = sorted(set(cl["jobs"]) | c["job_labels"])
    # jobs_meta 以岗位为键去重合并（同岗同 tier/positioning 自然合并）
    merged_meta = dict(cl.get("jobs_meta", {}))
    merged_meta.update(c["jobs_meta"])
    cl["jobs_meta"] = merged_meta
    # 维度计数合并，重选代表表述（取最长、信息量最大）
    merged_dims = Counter(cl["dimensions"]) + c["dim_counter"]
    cl["dimensions"] = dict(merged_dims)
    cl["dimension"] = merged_dims.most_common(1)[0][0]
    if len(ng) > len(cl["representative"]):
        cl["representative"] = ng
    # 合并后按「岗位」重算 count/tier_a/stretch/weight（不再依赖 dim_counter）
    cl["count"] = len(cl["jobs"])
    cl["tier_a"] = sum(1 for (t, _p) in merged_meta.values() if t == "A")
    cl["stretch"] = sum(1 for (_t, p) in merged_meta.values() if p == "stretch")
    cl["weight"] = sum(
        _SEVERITY_WEIGHT.get(p, 2) * _TIER_WEIGHT.get(t, 1)
        for (t, p) in merged_meta.values()
    )


def build_heatmap(clusters: list[dict]) -> str:
    """生成 heatmap 表（按优先级权重降序）。"""
    if not clusters:
        return "_（无显著缺口）_"
    lines = [
        "| 维度 | 代表缺口 | 命中岗位 | A档 | stretch | 优先级权重 |",
        "|------|----------|----------|-----|----------|------------|",
    ]
    for cl in clusters:
        lines.append(
            f"| {_DIMENSION_LABEL.get(cl['dimension'], cl['dimension'])} "
            f"| {cl['representative'][:40]} "
            f"| {cl['count']} "
            f"| {cl['tier_a']} "
            f"| {cl['stretch']} "
            f"| {cl['weight']} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 概览 brief 渲染（纯数据驱动，确定性）
# ---------------------------------------------------------------------------
def _top_direction_anchors(profile: dict, n: int = 3) -> list[str]:
    """方向锚点：兼容 list[str] 与 list[dict{text,weight}] 两种形态。"""
    anchors = (profile or {}).get("direction_anchors", []) or []
    out: list[str] = []
    for a in anchors:
        t = a.get("text", "") if isinstance(a, dict) else str(a)
        if t:
            out.append(t)
    return out[:n]


_LEVEL_ORDER = {"L3": 3, "L2": 2, "L1": 1, "L0": 0}


def _covered_basis(profile: dict, scored_results: dict | None, n: int = 6) -> list[str]:
    """已覆盖基础：profile 的 core_experiences（按 evidence_level 取高证据） + tier_A 的 match_reasons 去重。

    兼容两种 core_experiences 形态：
      - list[dict]（含 what_i_did / evidence_level）—— 真实 boundary_profile 形态
      - dict{level: [items]} —— 旧形态
    """
    basis: list[str] = []
    core = (profile or {}).get("core_experiences", {}) or []
    if isinstance(core, list):
        sorted_core = sorted(
            (c for c in core if isinstance(c, dict)),
            key=lambda c: _LEVEL_ORDER.get(str(c.get("evidence_level", "L0")).upper(), 0),
            reverse=True,
        )
        for c in sorted_core:
            t = c.get("what_i_did", "")
            if t:
                basis.append(t)
    elif isinstance(core, dict):
        for level in ("L3", "L2", "L1", "L0"):
            for item in core.get(level, []) or []:
                t = item.get("text", "") if isinstance(item, dict) else str(item)
                if t:
                    basis.append(t)
    recs = (scored_results or {}).get("recommendations", {}) or {}
    seen = set()
    for job in recs.get("tier_A", []) or []:
        for r in job.get("match_reasons", []) or []:
            if r and r not in seen:
                seen.add(r)
                basis.append(r)
    return basis[:n]


def _upgrade_directions(clusters: list[dict]) -> list[tuple[str, list[str]]]:
    """按维度分组生成「方向性」升级方向（非具体课程）。"""
    by_dim: dict[str, list[str]] = {}
    for cl in clusters:
        by_dim.setdefault(cl["dimension"], []).append(cl["representative"])
    out = []
    for dim in ("hard", "domain", "tooling", "soft", "credential"):
        if dim in by_dim:
            out.append((_DIMENSION_LABEL.get(dim, dim), by_dim[dim]))
    return out


def render_brief(profile: dict, scored_results: dict | None,
                 decision_context: dict, clusters: list[dict],
                 heatmap: str, resource_map: dict | None = None) -> str:
    direction_anchors = _top_direction_anchors(profile)
    pipeline_anchor = ((scored_results or {}).get("pipeline", {}) or {}).get("direction_anchor", "")
    role_type = (profile or {}).get("role_type", "") or ""
    education = (profile or {}).get("education", {}) or {}
    if isinstance(education, dict):
        edu_str = " / ".join(str(v) for v in (
            education.get("degree"), education.get("school"), education.get("major")
        ) if v)
    else:
        edu_str = str(education) if education else ""
    basis = _covered_basis(profile, scored_results)
    hard_negatives = [(h.get("text", "") if isinstance(h, dict) else str(h))
                      for h in ((profile or {}).get("hard_negatives", []) or [])]
    hard_negatives = [h for h in hard_negatives if h]
    directions = _upgrade_directions(clusters)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    out = []
    out.append("# 技能升级概览（供 AI 制定详细学习计划用）")
    out.append("")
    out.append(f"> 由 `build_upskill_brief.py` 于 {now} 自动聚合生成。**方向性缺口/升级概览**，")
    out.append("> 不是最终学习计划。把它贴给外部 AI，让其产出具体课程/资源/时间表。")
    out.append("> 本工具**不**搜网络资源、**不**生成课程计划。")
    out.append("")
    out.append("## 1. 当前定位")
    out.append("")
    if role_type:
        out.append(f"- **角色定位**：{role_type}")
    anchor_parts = list(direction_anchors)
    if pipeline_anchor:
        # 只补 pipeline 里「相对 profile 锚点」新增的 token，避免重复罗列
        # 比较时统一小写，展示保留原大小写（避免 Agent→agent 丢信息）
        existing_lower = set()
        for a in direction_anchors:
            existing_lower |= set(t.lower() for t in re.findall(r"[一-鿿A-Za-z0-9]+", a or ""))
        new_toks = [t for t in re.findall(r"[一-鿿A-Za-z0-9]+", pipeline_anchor)
                    if t.lower() not in existing_lower]
        if new_toks:
            anchor_parts.append("；".join(new_toks))
    if anchor_parts:
        out.append("- **方向锚点**：" + "；".join(anchor_parts))
    if edu_str:
        out.append(f"- **学历**：{edu_str}")
    if basis:
        out.append("- **已覆盖（已有基础，避免 AI 重复从零教）**：")
        for b in basis:
            out.append(f"  - {b}")
    out.append("")
    out.append("## 2. 核心缺口（按优先级）")
    out.append("")
    if clusters:
        for i, cl in enumerate(clusters, 1):
            out.append(
                f"{i}. **[{_DIMENSION_LABEL.get(cl['dimension'], cl['dimension'])}]** "
                f"{cl['representative']} —— 命中 {cl['count']} 个岗位"
                f"（A档 {cl['tier_a']} / stretch {cl['stretch']}），优先级权重 {cl['weight']}"
            )
            if len(cl["sources"]) > 1:
                others = [s for s in cl["sources"] if s != cl["representative"]]
                out.append(f"   - 同簇原始表述：{'；'.join(others[:4])}")
    else:
        out.append("_（未检测到显著缺口）_")
    out.append("")
    out.append("## 3. 升级方向（方向性，非具体课程）")
    out.append("")
    if directions:
        for dim_label, reps in directions:
            out.append(f"- **{dim_label}**：" + "；".join(reps[:3]))
        out.append("")
        out.append("  （具体课程/路径/资源由外部 AI 依据上方缺口与基础补充）")
    else:
        out.append("_（暂无分组）_")
    out.append("")
    out.append("## 4. 约束")
    out.append("")
    if hard_negatives:
        out.append("- **反向约束（明确不投/不补的方向，来自 hard_negatives）**："
                   + "；".join(hard_negatives))
    out.append("- **待用户补充**：每周可用时间 ___ ；目标岗位类型 ___ ；计划周期 ___")
    out.append("")
    out.append("## 5. 缺口热力图（heatmap）")
    out.append("")
    out.append(heatmap)
    out.append("")
    out.append("## 6. 喂给外部 AI 的指令（复制下方即可）")
    out.append("")
    out.append("```")
    out.append("请基于以下「当前定位 + 核心缺口 + 升级方向 + 约束」为我制定一份专业的学习计划：")
    out.append("1) 给出 3-6 个月的主线升级路径（按缺口优先级排序）；")
    out.append("2) 每个方向标注「为什么补、补到什么程度算够」；")
    out.append("3) 不要从零教我已覆盖的基础；4) 给出可自测的里程碑。")
    out.append("（上方第 1-5 节即为输入）")
    out.append("```")
    out.append("")
    if resource_map:
        out.append("## 7. 本地资源（owner 自管，未联网）")
        out.append("")
        any_res = False
        for dim in ("hard", "domain", "tooling", "soft", "credential"):
            res = resource_map.get(dim) or []
            if res:
                any_res = True
                out.append(f"- **{_DIMENSION_LABEL.get(dim, dim)}**：")
                for (t, url, note) in res:
                    suffix = f" — {note}" if note else ""
                    out.append(f"  - [{t}]({url}){suffix}")
        if not any_res:
            out.append("_（资源索引为空；在 references/resource-index.md 自管收藏）_")
        out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# 文件加载 / 主流程
# ---------------------------------------------------------------------------
def _load_json(path: str | None) -> dict:
    if not path:
        return {}
    if not os.path.exists(path):
        print(f"[warn] 输入文件不存在，跳过：{path}", file=sys.stderr)
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="方向性缺口/升级概览生成器")
    ap.add_argument("--profile", help="boundary_profile.json 路径")
    ap.add_argument("--scored", help="scored_results.json 路径")
    ap.add_argument("--decision", help="decision_context.json 路径")
    ap.add_argument("--out-dir", default="out", help="输出目录（默认 out/）")
    ap.add_argument("--resource-index",
                    default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                         "references", "resource-index.md"),
                    help="本地资源索引 markdown（N6，未联网）")
    args = ap.parse_args(argv)

    profile = _load_json(args.profile)
    scored = _load_json(args.scored)
    decision = _load_json(args.decision)

    clusters = aggregate_gaps(decision, scored)
    heatmap = build_heatmap(clusters)
    resource_map = map_clusters_to_resources(clusters, load_resource_index(args.resource_index))
    brief = render_brief(profile, scored, decision, clusters, heatmap, resource_map)

    os.makedirs(args.out_dir, exist_ok=True)
    md_path = os.path.join(args.out_dir, "upskill_brief.md")
    json_path = os.path.join(args.out_dir, "upskill_brief.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(brief)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cluster_count": len(clusters),
            "clusters": clusters,
        }, f, ensure_ascii=False, indent=2)

    print(f"[ok] 概览 brief → {md_path}")
    print(f"[ok] 结构化簇 → {json_path}（{len(clusters)} 个缺口簇）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
