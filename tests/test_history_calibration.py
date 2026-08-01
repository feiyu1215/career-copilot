"""Phase 6.2 面试复盘 → 匹配模型修正：离线测试（无 LLM / 无网络）。

做法：
- 单元层：直接验证 analyze_career_history / compute_history_delta / _apply_history_calibration
  （复盘信号解析、方向加权/降权、就地修改 stage1_score）。
- 端到端层：复用 test_e2e_regression 的确定性 mock LLM，跑真实六阶段 run_pipeline，
  用回归 fixture（8 个真实 JD）+ 合成 career_log.jsonl，断言：
    * 传 --history 时 history_calibration.enabled=True，且相关方向岗位分数按预期方向变化；
    * 不传 --history 时 enabled=False 且分数与基线完全一致（向后兼容）。
"""

import asyncio
import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import smart_score  # noqa: E402

FIX = REPO / "tests" / "fixtures"


# ---------- 自包含的确定性 mock LLM（与 test_e2e_regression 同构，避免跨测试导入）----------

def _score_for(title: str) -> int:
    """确定性、跨进程稳定的伪评分（与管线解耦但保持一致）。"""
    import hashlib
    h = int.from_bytes(hashlib.md5(title.encode("utf-8")).digest()[:4], "big")
    return 40 + (h % 60)  # 40..99


class _Sem:
    def __init__(self, v):
        self._value = v


class _DeterministicClient:
    """行为确定、无网络的 LLMClient 替身（按文案路由到各 stage）。"""

    def __init__(self, *a, **k):
        self.provider_name = "mock"
        self.model = k.get("model", "mock")
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.semaphore = _Sem(k.get("max_concurrent", 4))

    async def chat(self, system, user, temperature=0.0, max_tokens=150):
        self.total_input_tokens += len(system) + len(user)
        if "请严格排出" in user or "全局顺序" in user:
            resp = self._rerank(user)
        elif "求职匹配顾问" in system:
            resp = self._stage1(user)
        elif "行业猎头" in system:
            resp = self._stage2(user)
        else:
            resp = "calibration_knowledge"
        self.total_output_tokens += len(resp)
        return resp

    def _stage1(self, user):
        import re
        m = re.search(r"\*\*标题\*\*：(.+)", user)
        title = m.group(1).strip() if m else "unknown"
        return __import__("json").dumps({"score": _score_for(title), "reasoning": "确定性回归"})

    def _stage2(self, user):
        import json
        import re
        rows = re.findall(r"### 岗位 \d+（(JOB_\d+)）\s*\*\*标题\*\*：(.+)", user)
        scored = sorted(rows, key=lambda r: -_score_for(r[1]))
        out = []
        for rank, (jid, title) in enumerate(scored, 1):
            s = _score_for(title)
            tier = "A" if s >= 90 else ("B" if s >= 75 else "C")
            out.append({"job_id": jid, "rank": rank, "tier": tier, "score": float(s),
                        "match_reasons": ["匹配"], "risks": [], "advice": ""})
        return json.dumps(out, ensure_ascii=False)

    def _rerank(self, user):
        import json
        import re
        rows = re.findall(r"### \d+\. (.+)（(JOB_\d+)）", user)
        scored = sorted(rows, key=lambda r: -_score_for(r[0]))
        out = []
        for rank, (title, jid) in enumerate(scored, 1):
            out.append({"job_id": jid, "rank": rank,
                        "score": float(_score_for(title)),
                        "one_line_reason": "确定性回归"})
        return json.dumps(out, ensure_ascii=False)


def _build_args(tmp_path: Path) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        summary=str(FIX / "regression_summary.txt"),
        profile=str(FIX / "regression_profile.json"),
        jobs=str(FIX / "regression_jobs.txt"),
        top_k=8,
        stage1_model="mock",
        stage2_model="mock",
        concurrency=4,
        provider=None,
        resume=False,
        output=str(tmp_path / "out.json"),
        include_intern=False,
        include_outsource=False,
        max_year_requirement=20,
        jd_trust_report=False,
        stage2_concurrency=2,
        suppress_summary_notify=True,
        behavior_profile=None,
        wecom=None,
    )


def _write_history(tmp_path: Path) -> str:
    """合成 career_log.jsonl：

    - strong_points=["推荐"] → boost_terms 含 "推荐"（命中 JOB1/JOB3）
    - role="用户增长产品经理" 三次面试 2 败 1 过 → 通过率 1/3 < 0.5
      → low_pass_directions 含 "用户增长产品经理"（命中 JOB2）
    """
    p = tmp_path / "career_log.jsonl"
    events = [
        {"type": "interview_done", "company": "X", "role": "某推荐岗",
         "result": "pass", "strong_points": ["推荐"], "weak_points": [], "learnings": []},
        {"type": "interview_done", "company": "Y", "role": "用户增长产品经理", "result": "fail"},
        {"type": "interview_done", "company": "Z", "role": "用户增长产品经理", "result": "fail"},
        {"type": "interview_done", "company": "W", "role": "用户增长产品经理", "result": "pass"},
    ]
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    return str(p)


def _run_with(tmp_path: Path, history_path=None) -> dict:
    args = _build_args(tmp_path)
    args.history = history_path
    smart_score.LLMClient = lambda *a, **k: _DeterministicClient(*a, **k)
    return asyncio.run(smart_score.run_pipeline(args))


# ============================================================
# 单元层
# ============================================================

def test_analyze_career_history(tmp_path):
    hp = _write_history(tmp_path)
    a = smart_score.analyze_career_history(hp)
    assert "推荐" in a["boost_terms"]
    assert "用户增长产品经理" in a["low_pass_directions"]
    assert a["n_interviews"] == 4


def test_compute_history_delta_boost(tmp_path):
    hp = _write_history(tmp_path)
    a = smart_score.analyze_career_history(hp)
    job = {"title": "搜索推荐算法专家 - 推荐策略部", "department": "", "full_text": "负责推荐策略"}
    delta, reason = smart_score.compute_history_delta(job, a)
    assert delta == 4.0
    assert "推荐" in reason


def test_compute_history_delta_penalty(tmp_path):
    hp = _write_history(tmp_path)
    a = smart_score.analyze_career_history(hp)
    job = {"title": "用户增长产品经理 - 增长部", "department": "", "full_text": ""}
    delta, reason = smart_score.compute_history_delta(job, a)
    assert delta == -8.0
    assert "用户增长产品经理" in reason


def test_compute_history_delta_empty_analysis():
    job = {"title": "x", "department": "", "full_text": ""}
    delta, reason = smart_score.compute_history_delta(
        job, {"boost_terms": [], "low_pass_directions": []})
    assert delta == 0.0
    assert reason == ""


def test_apply_history_calibration_mutates(tmp_path):
    hp = _write_history(tmp_path)
    jobs = [
        {"title": "搜索推荐算法专家", "stage1_score": 80.0},
        {"title": "用户增长产品经理", "stage1_score": 80.0},
        {"title": "无关岗位", "stage1_score": 80.0},
    ]
    smart_score._apply_history_calibration(jobs, hp)
    assert jobs[0]["stage1_score"] == 84.0
    assert jobs[0]["history_delta"] == 4.0
    assert jobs[1]["stage1_score"] == 72.0
    assert jobs[1]["history_delta"] == -8.0
    assert jobs[2]["stage1_score"] == 80.0
    assert jobs[2]["history_delta"] == 0.0


# ============================================================
# 端到端层（确定性 mock LLM，复用回归 fixture）
# ============================================================

def test_run_pipeline_history_on_changes_scores(tmp_path):
    hp = _write_history(tmp_path)
    out_on = _run_with(tmp_path / "on", hp)
    out_off = _run_with(tmp_path / "off", None)

    # 开关正确
    assert out_on["pipeline"]["history_calibration"]["enabled"] is True
    assert out_off["pipeline"]["history_calibration"]["enabled"] is False
    # 信号解析正确
    assert "推荐" in out_on["pipeline"]["history_calibration"]["boost_terms"]
    assert "用户增长产品经理" in out_on["pipeline"]["history_calibration"]["low_pass_directions"]

    # 分数按预期方向变化（与未传 --history 的基线对比）
    off_map = {j["title"]: j["score"] for j in out_off["stage1_all_scores"]}
    on_map = {j["title"]: j["score"] for j in out_on["stage1_all_scores"]}

    job1 = next(t for t in on_map if "搜索推荐算法专家" in t)
    job3 = next(t for t in on_map if "推荐系统工程师" in t)
    job2 = next(t for t in on_map if "用户增长产品经理" in t)

    assert on_map[job1] == off_map[job1] + 4.0   # 推荐方向加权
    assert on_map[job3] == off_map[job3] + 4.0   # 推荐方向加权
    assert on_map[job2] == off_map[job2] - 8.0   # 低通过率方向降权


def test_run_pipeline_history_off_is_baseline_identical(tmp_path):
    """不传 --history 时，分数与「传一个空复盘」完全一致（向后兼容，零副作用）。"""
    empty = tmp_path / "empty_log.jsonl"
    empty.write_text("", encoding="utf-8")
    out_none = _run_with(tmp_path / "none", None)
    out_empty = _run_with(tmp_path / "empty", str(empty))
    none_map = {j["title"]: j["score"] for j in out_none["stage1_all_scores"]}
    empty_map = {j["title"]: j["score"] for j in out_empty["stage1_all_scores"]}
    assert none_map == empty_map
    assert out_none["pipeline"]["history_calibration"]["enabled"] is False
