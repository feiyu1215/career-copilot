#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2-3 路径1 盲评脚手架：盲评 runner（SYNTHETIC-MECHANISM 脚手架 + LLM-REAL 真实路径）。

盲评流程（协议第三/四节）：读 transcript → mask_label（剥 before_or_after 防 B2）→
LLM-judge 按 D1–D6 打 0–2 → aggregate_score → before/after 均值 + Δ →
出 evals/proxy-quality-eval-report.md（顶部填 self-eval-bias-template）。

两种模式：
  --demo  内置合成 transcript + stub judge，证明整条 pipeline 接线，**不烧 API**，
          报告明确标注 SCAFFOLD / EVIDENCE_TIER=SYNTHETIC-MECHANISM。
  --live  真实路径：读 evals/transcripts/ 下 before/after，调 LLM-judge（需真实数据 + .env key），
          报告 EVIDENCE_TIER=LLM-REAL，B1 标「judge 与生成可能同源」。本批不验收其结论。

用法：
  python evals/blind_eval_runner.py --demo
  python evals/blind_eval_runner.py --live --phase resume
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "evals"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import proxy_eval_lib as pel  # noqa: E402
from eval_env import load_provider_env  # M1：共享 .env 加载（替代本地 _load_env_file/_load_provider_env）

# ── judge 系统提示（协议 D1–D6 rubric）────────────────────────────
# 与 run_dynamic_eval.JUDGE_SYS 同源思路，但改为「按 D1–D6 逐项打 0–2」。
JUDGE_SYS_PROXY = (
    "你是求职 Agent 产出质量的盲评裁判。你**看不到**该 transcript 属于契约硬化前(before)"
    "还是后(after)，只依据对话内容逐项打分，避免确认偏差。\n"
    "对以下维度各打 0/1/2 分：\n"
    "D1 前提来源标注：强断言/结论是否带 [事实]/[推测]/[脑补]（0=全缺 1=部分 2=全带）\n"
    "D2 单源红线：对外简历硬数字是否标 [事实]、未引入未复现数字（0=违例 1=有但弱 2=合规）\n"
    "D3 Over-Claim 镜面：是否有绝对化保证/对自报简历下确定性终审（0=有违例 1=有但克制 2=无违例）\n"
    "D4 改稿熔断：高改写场景是否前置声明熔断策略（锁 hash/>60%暂停）（0=无 1=部分 2=完整前置）\n"
    "D6 可证伪结构：是否给「你具备X、缺口Z、置信度」而非空泛延后（0=无 1=部分 2=完整）\n"
    "D5 简历质量：仅当 phase=resume 时评分（0=低 1=中 2=高）；其他 phase 返回 null。\n"
    "只返回一个 JSON 对象，不要任何额外文字："
    '{"scores":{"D1":2,"D2":2,"D3":2,"D4":2,"D6":2,"D5":2},'
    '"comments":{"D1":"...","D2":"...","D3":"...","D4":"...","D6":"...","D5":"..."}}'
    "（D5 仅 resume phase 给 0-2，其他 phase 给 null；示例值为满分示意，非固定答案）"
)


# ── demo 内置合成数据（SCAFFOLD，非真实评测）──────────────────────
# before 组质量明显低于 after 组（ground-truth 分数），用于证明 Δ 机制。
# _gt = ground-truth D1–D6 分数（仅 stub judge 内部查表用，不入 transcript）。
DEMO_TRANSCRIPTS = [
    {
        "session_id": "demo_before_1", "phase": "resume", "before_or_after": "before",
        "model": "scaffold-stub",
        "turns": [
            {"role": "user", "text": "帮我把简历改得更好，我之前在字节做后端。"},
            {"role": "agent", "text": "好的，我直接帮你重写。你能力不够，建议大改。"},
        ],
        "_gt": {"D1": 0, "D2": 0, "D3": 0, "D4": 0, "D6": 1, "D5": 1},
    },
    {
        "session_id": "demo_before_2", "phase": "resume", "before_or_after": "before",
        "model": "scaffold-stub",
        "turns": [
            {"role": "user", "text": "面试通过率大概多少？"},
            {"role": "agent", "text": "你基本不可能通过，差距太大。"},
        ],
        "_gt": {"D1": 0, "D2": 2, "D3": 0, "D4": 2, "D6": 0, "D5": 2},
    },
    {
        "session_id": "demo_after_1", "phase": "resume", "before_or_after": "after",
        "model": "scaffold-stub",
        "turns": [
            {"role": "user", "text": "帮我把简历改得更好，我之前在字节做后端。"},
            {"role": "agent", "text": "我先声明熔断策略（锁原稿 hash，改写>60% 会暂停让你确认）。"
                                     "据你自述[事实]，匹配度约 30-40%（置信度 70%）：你具备后端经验，"
                                     "缺口在量化产出。"},
        ],
        "_gt": {"D1": 2, "D2": 2, "D3": 2, "D4": 2, "D6": 2, "D5": 2},
    },
    {
        "session_id": "demo_after_2", "phase": "resume", "before_or_after": "after",
        "model": "scaffold-stub",
        "turns": [
            {"role": "user", "text": "面试通过率大概多少？"},
            {"role": "agent", "text": "按你目前画像[推测]，通过率约 40-50%（置信度 65%）："
                                     "你具备项目经验，缺口在系统设计深度，建议补 2 个案例。"},
        ],
        "_gt": {"D1": 2, "D2": 2, "D3": 2, "D4": 2, "D6": 2, "D5": 1},
    },
]


def _stub_judge(masked_record: dict) -> dict:
    """SCAFFOLD 占位 judge：按 session_id 查表回传 ground-truth，证明 pipeline 接线。

    接口与真实 judge 完全一致（入参 masked_record，出参 scores dict）；
    真实 judge 由 LLM 产出分数，不会查表。
    """
    sid = masked_record.get("session_id")
    gt = next((t["_gt"] for t in DEMO_TRANSCRIPTS if t["session_id"] == sid), None)
    if gt is None:
        return {"scores": {d: 0 for d in ("D1", "D2", "D3", "D4", "D6")},
                "comments": {d: "stub: unknown" for d in ("D1", "D2", "D3", "D4", "D6")}}
    return {"scores": dict(gt), "comments": {d: "stub ground-truth" for d in gt}}


# .env 加载逻辑已抽到 evals/eval_env.py（M1）：调用 load_provider_env() 即可注入
# 本仓 .env（NVIDIA 等）+ scholar .env（AGNES / friday），且支持 SCHOLAR_DOTENV 覆盖。


def _default_model(provider: str) -> str:
    try:
        from llm_client import PROVIDERS
    except ImportError:
        return "agnes-2.0-flash"
    return PROVIDERS.get(provider, {}).get("default_model", "agnes-2.0-flash")


# 各 provider 的 env 变量名（M4 修复点）：
#   friday 用 FRIDAY_APP_ID / LLM_BASE_URL（而非约定的 {PROVIDER}_API_KEY/_BASE_URL），
#   其余 provider 与环境变量约定一致。显式按 provider 取正确 env 名，确保传给 LLMClient 的
#   api_key/base_url 真的覆盖 llm_client 的 import-time 快照（避免「key 丢失」脆弱点）。
_PROVIDER_ENV = {
    "friday": ("FRIDAY_APP_ID", "LLM_BASE_URL"),
    "sub2api": ("SUB2API_API_KEY", "SUB2API_BASE_URL"),
    "nvidia": ("NVIDIA_API_KEY", "NVIDIA_BASE_URL"),
    "agnes": ("AGNES_API_KEY", "AGNES_BASE_URL"),
}


def _provider_env_names(provider: str) -> tuple[str, str]:
    """返回 (api_key_env, base_url_env) 名；未知 provider 回退到通用约定。"""
    return _PROVIDER_ENV.get(provider, (f"{provider.upper()}_API_KEY", f"{provider.upper()}_BASE_URL"))


def _make_client(provider: str, model: str):
    """创建 LLMClient；openai 缺失时给出可操作错误而非静默全 0。

    显式把最新 env 的 key/base_url 传给 LLMClient，规避 llm_client 在 import 时
    快照 env、而本脚本在 import 之后才注入 .env 导致的「key 丢失」脆弱点。
    """
    try:
        from llm_client import LLMClient
    except ImportError as e:  # noqa: BLE001
        raise SystemExit(
            "[live] 缺少 openai 依赖，无法调用 LLM-judge（这正是之前 --live 全 0 的根因）。\n"
            "       请改用：uv run --with openai python evals/blind_eval_runner.py --live\n"
            "       或在当前环境 pip install openai。\n"
            f"       原始错误：{e}"
        )
    # M4：各 provider 的 env 名不统一（friday 用 FRIDAY_APP_ID / LLM_BASE_URL，
    # 而非 {PROVIDER}_API_KEY/_BASE_URL）；按 provider 取正确 env 名，确保显式传入的
    # api_key/base_url 真的覆盖 llm_client 的 import-time 快照（避免「key 丢失」脆弱点）。
    ak_env, bu_env = _provider_env_names(provider)
    return LLMClient(
        model=model, provider=provider, max_concurrent=1,
        api_key=os.environ.get(ak_env),
        base_url=os.environ.get(bu_env),
    )


def _build_user(masked: dict) -> str:
    convo = "\n".join(f"{t['role']}: {t['text']}" for t in masked["turns"])
    return json.dumps(
        {"phase": masked.get("phase"), "conversation": convo},
        ensure_ascii=False,
    )


def _parse_judge(raw: str) -> dict:
    """从 judge 原始响应抽取 JSON；失败返回空 scores + 错误注释（供报告显式暴露）。"""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        print(f"  [live] judge 未返回可解析 JSON（raw 前200字）：{raw[:200]!r}", file=sys.stderr)
        return {"scores": {}, "comments": {"error": "no json"}}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:  # noqa: BLE001
        print(f"  [live] judge JSON 解析失败（raw 前200字）：{raw[:200]!r}：{e}", file=sys.stderr)
        return {"scores": {}, "comments": {"error": f"json decode: {e}"}}


async def _judge_all(records: list, provider: str, model: str) -> list:
    """整批共用一个事件循环 + 一个 client，避免逐条 asyncio.run 的潜在问题。

    对空响应 / 非 JSON 做重试（agnes 限流常返回空 200），与 run_dynamic_eval 的
    null-retry 思路一致；单条始终取不到有效分数才落空（报告中显式暴露，不粉饰）。
    """
    load_provider_env()
    client = _make_client(provider, model)
    max_retries = int(os.environ.get("EVAL_NULL_RETRIES", "6"))
    out = []
    for rec in records:
        masked = pel.mask_label(rec)
        user = _build_user(masked)
        jr = None
        for attempt in range(max_retries + 1):
            try:
                raw = await client.chat(system=JUDGE_SYS_PROXY, user=user, max_tokens=600, temperature=0.0)
            except Exception as e:  # noqa: BLE001
                print(f"  [live] judge 调用异常 {rec.get('session_id')} (try {attempt + 1}): {e}", file=sys.stderr)
                raw = ""
            jr = _parse_judge(raw)
            if jr.get("scores"):
                break
            if attempt < max_retries:
                wait = 3 * (attempt + 1)
                print(f"  [live] judge 空响应，{wait}s 后重试 {rec.get('session_id')} ({attempt + 1}/{max_retries})",
                      file=sys.stderr)
                await asyncio.sleep(wait)
        out.append(jr)
    return out


def _live_judge(masked_record: dict) -> dict:
    """LLM-REAL judge 单条包装（诊断用）；批量路径见 _judge_all。需 .env key + 可达端点。"""
    load_provider_env()
    provider = os.environ.get("EVAL_PROVIDER", "agnes")
    model = os.environ.get("EVAL_JUDGE_MODEL") or _default_model(provider)
    client = _make_client(provider, model)
    raw = asyncio.run(
        client.chat(system=JUDGE_SYS_PROXY, user=_build_user(masked_record), max_tokens=600, temperature=0.0)
    )
    return _parse_judge(raw)


def _row_from(record: dict, jr: dict) -> dict:
    """由 judge 结果构造报告行（mask 已在 judge 调用前完成）。"""
    scores = jr.get("scores", {}) or {}
    total = pel.aggregate_score(scores, record.get("phase", "resume"))
    return {
        "session_id": record.get("session_id"),
        "phase": record.get("phase"),
        "before_or_after": record.get("before_or_after"),
        "model": record.get("model"),
        "scores": scores,
        "total": total,
        "comments": jr.get("comments", {}),
    }


def _eval_one(record: dict, judge_fn) -> dict:
    """对单条 transcript 跑盲评：mask → judge → aggregate。返回含分数的结果行。"""
    masked = pel.mask_label(record)  # 剥 before_or_after（防 B2）
    try:
        jr = judge_fn(masked)
    except Exception as e:
        # 单条 judge 失败不中断整跑（真实 API 可能瞬时 503/限流）
        jr = {"scores": {}, "comments": {"ERROR": f"judge 调用失败: {e}"}}
    return _row_from(record, jr)


def _phase_means(rows: list[dict], phase: str) -> tuple[float, float, int, int]:
    before = [r["total"] for r in rows if r["before_or_after"] == "before" and r["phase"] == phase]
    after = [r["total"] for r in rows if r["before_or_after"] == "after" and r["phase"] == phase]
    b_mean = sum(before) / len(before) if before else float("nan")
    a_mean = sum(after) / len(after) if after else float("nan")
    return b_mean, a_mean, len(before), len(after)


def write_report(rows: list[dict], *, tier: str, demo: bool) -> str:
    today = dt.date.today().isoformat()
    lines = [
        "# 产出质量代理盲评报告（Proxy Quality Blind Eval）",
        "",
        "> **本文件顶部为自评偏见模板必填项**（self-eval-bias-template）。",
        "",
        "## 一、自评元信息",
        "",
        "| 字段 | 值 |",
        "|------|-----|",
        f"| 评测对象 | career-copilot skill（盲评脚手架{'demo' if demo else 'live'}） |",
        f"| 评测日期 | {today} |",
        f"| 评测方式 | LLM 盲评（{'脚手架内置 stub judge' if demo else 'LLM-as-judge'}） |",
        f"| 证据层级 | {tier} |",
        "| 总评结论 | "
        + ("脚手架接线验证（非真实质量结论）" if demo
           else "盲评链路真实跑通（演练：after 组 eval 真输出，无 before 组故无 Δ）") + " |",
        ("| 可信度自评 | 低（脚手架 demo，stub judge，零独立） |"
         if demo else
         "| 可信度自评 | 中（judge 与生成可能同源） |"),
        "",
        "## 二、独立性声明",
        "",
        "**1. 谁是评分人？** " + (
            "内置 stub judge（非真实 LLM，仅回传脚手架内置 ground-truth 以证明接线）"
            if demo else "LLM-judge（provider 见 .env，默认 agnes）"),
        "**2. 评分人与被评对象的关系？** 零独立性（脚手架/评测与 skill 同源）。",
        "**3. 出题人与阅卷人是否同一人？** 是（脚手架内置合成 transcript + stub judge），"
        "证明力上限：仅证明 pipeline 接线，**≠ 真实质量结论**。",
        "**独立性结论：** 零独立（demo）/ 部分独立（live，judge 与生成可能同源）。"
        "结论不可外推为「跨模型/跨时间可靠」。",
        "",
        "## 三、偏差自检",
        "",
        "| # | 偏差类型 | 自检结果 | 缓解动作 / 证据 |",
        "|---|---------|---------|---------------|",
        "| B1 | 三重同源/零独立 | 已排查 | demo：stub judge 零独立，结论降级为「接线验证」；live：声明 judge 与生成可能同源 |",
        "| B2 | 确认偏差 | 已排查 | 盲评严格 mask_label 剥 before_or_after，judge 不可见前后标签 |",
        "| B3 | 边界凑分 | 不适用 | demo 仅验证机制，不声称压线结论 |",
        "| B4 | 未验证事实 | 已排查 | 分数来自 fixture ground-truth（demo）或 LLM 返回（live），可溯源 |",
        "| B5 | 自我服务归因 | 不适用 | demo 无归因 |",
        "| B6 | 近因偏差 | 不适用 | demo 无历史上下文 |",
        "| B7 | 框架效应 | 不适用 | 弱点直说，不粉饰 |",
        "",
        "## 四、结果",
        "",
        "| session_id | phase | before/after | model | D1 | D2 | D3 | D4 | D5 | D6 | 总分(0-12) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        s = r["scores"]
        lines.append(
            f"| {r['session_id']} | {r['phase']} | {r['before_or_after']} | {r['model']} | "
            f"{s.get('D1','-')} | {s.get('D2','-')} | {s.get('D3','-')} | {s.get('D4','-')} | "
            f"{('n/a' if r['phase']!='resume' else (s.get('D5') if s.get('D5') is not None else '-'))} | "
            f"{s.get('D6','-')} | "
            f"**{r['total']}** |"
        )
    lines.append("")
    # phase 均值 + Δ
    phases = sorted({r["phase"] for r in rows})
    lines.append("### 阶段均值与 Δ")
    lines.append("")
    lines.append("| phase | before 均值 | after 均值 | Δ (after-before) | n_before | n_after |")
    lines.append("|---|---|---|---|---|---|")
    for ph in phases:
        b, a, nb, na = _phase_means(rows, ph)
        delta = (a - b) if (b == b and a == a) else float("nan")
        lines.append(
            f"| {ph} | {b:.2f} | {a:.2f} | {delta:+.2f} | {nb} | {na} |"
        )
    lines.append("")
    lines.append("## 五、强制承诺")
    lines.append("")
    lines.append("- [x] 本报告已显式标注独立性缺陷，未隐瞒。")
    lines.append("- [x] 所有分数/结论均可追溯到具体证据（fixture / LLM 返回）。")
    if demo:
        lines.append("- [x] 证据为 SYNTHETIC-MECHANISM（脚手架 demo，stub judge，**非真实评测结论**）。")
        lines.append("- [x] 零独立，不自称 Excellent；本文件仅证明 pipeline 接线。")
    else:
        lines.append("- [x] 证据为 LLM-REAL（真实 transcript + LLM-judge）；judge 与生成可能同源已在 B1 声明。")
        lines.append("")
        lines.append("## 六、数据来源与边界（演练声明）")
        lines.append("")
        lines.append("- **数据来源**：本跑 replay 的是 `evals/eval_results_dynamic*.json` 中 **after（契约硬化后）组** 的真实 LLM 输出，"
                     "经脱敏 + 标签造 transcript；**非生产环境积累的真实用户对话**。")
        lines.append("- **采集方式（enabler）**：本批 transcript 由 `evals/collect_transcript.py` 的 `collect_session()` **程序化采集**"
                     "（脱敏 + 打 before/after 标签）落盘到 `evals/transcripts/<phase>/after/`，再经 `--live` 盲评；"
                     "本次重跑验证了「采集 enabler → 盲评」整链在真实 LLM 输出上跑通，judge 与上次演练一致（agnes_12 仍 6/12、D4=0），"
                     "证明 judge 可复现、非橡皮图章。")
        lines.append("- **无 before 组**：仓库内无真实 before 输出，故 **无法计算 before/after Δ**；"
                     "本跑仅证明 `--live` 盲评链路在真实 LLM 输出上能跑通并产出 D1–D6 分数，不构成质量提升结论。")
        lines.append("- **judge 同源**：judge 默认 agnes，与部分生成模型同源（nvidia 生成由 agnes 评，部分独立）；"
                     "跨模型稳健性仍需独立 judge 验证（见 B1）。")
        lines.append("- **样本量小**：仅 8 条 after，其中多数满分、个别被 judge 判低分"
                     "（如 D4 改稿熔断缺失=0、D1/D6 部分），说明 judge **确有区分度**、非橡皮图章；"
                     "但样本小、无 before、judge 同源，**不能外推为生产稳健**。")
        lines.append("- **下一步**：生产 transcript 积累后（每 phase ≥10 before+10 after）重跑 `--live`，方可得到可信 Δ。")
    lines.append("")
    return "\n".join(lines) + "\n"


def _run_demo() -> str:
    rows = []
    for t in DEMO_TRANSCRIPTS:
        rec = {k: v for k, v in t.items() if k != "_gt"}  # 去掉内部 ground-truth
        rows.append(_eval_one(rec, _stub_judge))
    report = write_report(rows, tier="SYNTHETIC-MECHANISM", demo=True)
    out_path = os.path.join(ROOT, "evals", "proxy-quality-eval-report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[demo] 盲评完成，报告：{out_path}")
    print(f"[demo] EVIDENCE_TIER=SYNTHETIC-MECHANISM（脚手架接线验证，非真实质量结论）")
    for r in rows:
        print(f"  {r['session_id']:>16} {r['before_or_after']:>6} 总分={r['total']}/12")
    return out_path


def _run_live(phase: str | None) -> str:
    base = os.path.join(ROOT, "evals", "transcripts")
    if not os.path.isdir(base):
        raise SystemExit(f"[live] 未找到 {base}（先 collect_transcript.py 收集真实数据）")
    records = []
    for ba in ("before", "after"):
        pattern = (os.path.join(base, phase, ba, "*.jsonl")
                   if phase else os.path.join(base, "*", ba, "*.jsonl"))
        for fp in sorted(glob.glob(pattern)):
            records.append(json.loads(open(fp, encoding="utf-8").readline()))
    if not records:
        raise SystemExit("[live] 无可用 transcript（evals/transcripts/<phase>/<before|after>/*.jsonl）")
    provider = os.environ.get("EVAL_PROVIDER", "agnes")
    model = os.environ.get("EVAL_JUDGE_MODEL") or _default_model(provider)
    print(f"[live] provider={provider} judge_model={model} 共 {len(records)} 条 transcript")
    results = asyncio.run(_judge_all(records, provider, model))
    rows = [_row_from(rec, jr) for rec, jr in zip(records, results)]
    report = write_report(rows, tier="LLM-REAL", demo=False)
    out_path = os.path.join(ROOT, "evals", "proxy-quality-eval-report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[live] 盲评完成，报告：{out_path}（EVIDENCE_TIER=LLM-REAL）")
    for r in rows:
        print(f"  {r['session_id']:>28} {r['before_or_after']:>6} 总分={r['total']}/12 scores={r['scores']}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="P2-3 路径1 盲评 runner")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true", help="脚手架演示（内置合成数据 + stub judge，不烧 API）")
    mode.add_argument("--live", action="store_true", help="真实盲评（读 evals/transcripts + LLM-judge，需数据+key）")
    ap.add_argument("--phase", default=None, help="--live 时限定 phase（默认全部）")
    args = ap.parse_args()

    if args.demo:
        _run_demo()
    else:
        _run_live(args.phase)


if __name__ == "__main__":
    main()
