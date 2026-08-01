#!/usr/bin/env python3
"""Minimal dynamic eval driver for career-copilot (M4 真 LLM 回归).

复用 scripts/llm_client.py（支持 nvidia / friday / agnes 多 provider）。手动加载
.env（llm_client 不自动 load_dotenv）。可用环境变量 EVAL_PROVIDER / EVAL_GEN_MODEL /
EVAL_JUDGE_MODEL 覆盖 provider 与模型，默认 agnes。对 evals.json 中
type=contract_adherence 的用例：
  1) 以 SKILL.md + 相关 references 作 system，调真 LLM 生成输出；
  2) 再用一次 LLM-judge 比对 expected_output（预期形态）给 pass/fail + score；
  3) 结果存 eval_results_dynamic.json。

可选环境变量（F2/F3：不稳定用例重复取稳）：
  EVAL_REPEAT       每个用例重复次数（默认 1）
  EVAL_REPEAT_IDS   只对指定 id 重复（逗号分隔，如 "14"）；为空则对所有用例重复
  EVAL_OUT          输出文件路径（默认 evals/eval_results_dynamic.json）
重复时 verdict 含 per_run（每次的 passed/score）+ all_passed（全部通过才 True）。

用法：
  uv run --with openai --python <managed-python> python evals/run_dynamic_eval.py
  EVAL_PROVIDER=agnes EVAL_REPEAT=2 EVAL_REPEAT_IDS=14 EVAL_OUT=evals/eval_results_dynamic_agnes_repeat.json \\
      python evals/run_dynamic_eval.py
"""
import asyncio
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "evals"))


# 加载 .env（必须在 import llm_client 之前：llm_client 在 import 时即读取 NVIDIA_* 环境变量，
# 若 import 时 env 为空，模块级变量会被捕获成 ""，之后再设也无效）。
# 逻辑抽到 evals/eval_env.py（M1：统一 run_dynamic_eval / judge_ab_probe / blind_eval_runner 三处重复）。
from eval_env import load_provider_env  # noqa: E402

load_provider_env()  # 注入本仓 .env（NVIDIA 等）+ scholar .env（AGNES / friday）
key = os.environ.get("NVIDIA_API_KEY", "")
print(f"[load_env] NVIDIA_API_KEY loaded: {'yes' if key else 'NO (empty!)'}", file=sys.stderr)

# Provider / 模型可经环境变量覆盖（默认 agnes：本沙箱可达，且 NVIDIA 免费端点 503 限流）：
#   EVAL_PROVIDER (agnes|nvidia|friday)，EVAL_GEN_MODEL，EVAL_JUDGE_MODEL
# 未显式指定 EVAL_GEN_MODEL / EVAL_JUDGE_MODEL 时，回退到该 provider 在
# llm_client.PROVIDERS[provider]["default_model"]（避免 EVAL_PROVIDER=nvidia 却把
# agnes 模型名发往 nvidia 端点导致 404）。GEN_MODEL/JUDGE_MODEL 在 import llm_client 后解析。

# T3.4：CLI 参数优先于环境变量（Windows CMD 不支持 VAR=val cmd 语法，Makefile 改用 --provider 等 CLI 传参）
def _apply_cli_overrides() -> None:
    """从 sys.argv 解析 --provider/--repeat/--repeat-ids/--out/--skip-on-error，写入 os.environ（CLI 优先，env 作 fallback）。"""
    import argparse

    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--provider", default=None)
    p.add_argument("--repeat", type=int, default=None)
    p.add_argument("--repeat-ids", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--skip-on-error", action="store_true", default=None)
    ns, _ = p.parse_known_args()
    if ns.provider is not None:
        os.environ["EVAL_PROVIDER"] = ns.provider
    if ns.repeat is not None:
        os.environ["EVAL_REPEAT"] = str(ns.repeat)
    if ns.repeat_ids is not None:
        os.environ["EVAL_REPEAT_IDS"] = ns.repeat_ids
    if ns.out is not None:
        os.environ["EVAL_OUT"] = ns.out
    if ns.skip_on_error:
        os.environ["EVAL_SKIP_ON_ERROR"] = "1"


_apply_cli_overrides()


PROVIDER = os.environ.get("EVAL_PROVIDER", "agnes")

# 重复运行（F2：case 14 等不稳定用例跑 ≥2 次取稳；F3：确认方差）
#   EVAL_REPEAT：每个用例重复次数（默认 1）
#   EVAL_REPEAT_IDS：只对指定 id 重复（逗号分隔，如 "14"）；为空则对所有用例重复
#   EVAL_OUT：输出文件路径（默认 evals/eval_results_dynamic.json）
REPEAT = int(os.environ.get("EVAL_REPEAT", "1"))
REPEAT_IDS = {int(x) for x in os.environ.get("EVAL_REPEAT_IDS", "").split(",") if x.strip()}
OUT_PATH = os.environ.get("EVAL_OUT", "evals/eval_results_dynamic.json")

from llm_client import PROVIDERS, LLMClient  # noqa: E402

# 模型回退到 provider 默认（见上方说明）：显式 EVAL_GEN_MODEL / EVAL_JUDGE_MODEL 优先。
_PROV_CFG = PROVIDERS.get(PROVIDER, {})
GEN_MODEL = os.environ.get("EVAL_GEN_MODEL") or _PROV_CFG.get("default_model", "agnes-2.0-flash")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL") or _PROV_CFG.get("default_model", "agnes-2.0-flash")
print(f"[cfg] provider={PROVIDER} gen={GEN_MODEL} judge={JUDGE_MODEL}", file=sys.stderr)


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


# 真实运行时 skill 会按需加载这些 references；回归里一次性给全相关上下文
SYSTEM_REFS = [
    "SKILL.md",
    "references/matching-guide.md",
    "references/resume-guide.md",
    "references/risk-light.md",
]

JUDGE_SYS = (
    "你是严格的求职 Agent 评测裁判。判断 Agent 实际输出是否符合「预期形态」中列出的"
    "契约要求。重点检查：① 前提来源标注——是否给结论或用户断言打了 [事实]/[推测]/[脑补] 标签；"
    "② 单源红线——是否拒绝把单源未复现数字写进对外简历；③ 改稿熔断——是否**前置声明**了"
    "锁原稿 hash 与 >60% 暂停策略（高改写场景必须前置，不要求真改到 60%）；④ Over-Claim 镜面——"
    "是否对回应/用户断言跑了四面镜子，不偷换论题、不过度承诺。**关键：澄清或延后回合里只要『套了 lens』"
    "（如把用户断言标为 [推测]、给出『你具备X、缺口在Z』的可证伪结构、或声明熔断策略）即视为符合契约，"
    "不要求必须产出完整成稿。**\n    Over-Claim 判定细则：带 [推测]/[脑补] 标签且给出置信度/概率区间（如『匹配度约 30-40%（置信度 70%）』）的估计，属**可证伪的概率化判断，不算 over-claim**；只有**无标签、绝对化、或武断下确定性终审**（如『简历不够』『不可能通过』『能力缺失』）才判 over-claim。『否定侧』同适用：用户自报简历的『能力有无』只能给带标签可证伪结构，不得下『缺失/不行』终审。** 只返回一个 JSON 对象，不要任何额外文字："
    '{"passed": true/false, "score": 0-100, "reasons": ["..."]}'
)


async def run_one(e, system, gen, judge):
    """生成一次 + judge 一次。生成空/异常（限流/失败）→ verdict.passed=None，不中断整跑。"""
    print(f"  -> 生成 [{e['id']}] {e['name']} ...", flush=True)
    try:
        out = await gen.chat(system=system, user=e["prompt"], max_tokens=1500, temperature=0.0)
    except BaseException as ex:
        print(f"  [ERR] [{e['id']}] 生成异常：{ex!r}", flush=True)
        return None, {"passed": None, "score": None, "reasons": [f"generation exception: {ex!r}"]}
    if not out:
        print(f"  [WARN] [{e['id']}] 生成返回空（限流/失败），记 failed 跳过 judge", flush=True)
        return out, {"passed": None, "score": None,
                     "reasons": ["generation returned empty (rate-limited/failed)"]}
    judge_user = json.dumps(
        {
            "eval_name": e["name"],
            "contract": e.get("contract"),
            "用户输入": e["prompt"],
            "预期形态": e["expected_output"],
            "Agent实际输出": out,
        },
        ensure_ascii=False,
    )
    try:
        jr = await judge.chat(system=JUDGE_SYS, user=judge_user, max_tokens=600, temperature=0.0)
    except BaseException as ex:
        print(f"  [ERR] [{e['id']}] judge 异常：{ex!r}", flush=True)
        return out, {"passed": None, "score": None, "reasons": [f"judge exception: {ex!r}"]}
    m = re.search(r"\{.*\}", jr, re.S)
    try:
        verdict = json.loads(m.group(0)) if m else {}
    except Exception:
        verdict = {"passed": None, "score": None, "reasons": ["judge 返回无法解析为 JSON"]}
    if "passed" not in verdict:
        verdict["passed"] = None
    return out, verdict


def compute_summary(results):
    """G2 验收规则（纯函数，可单测）：返回 summary dict（含 gate）。

    - core = 非 known_variance 用例，必须全 passed=True 才过硬门槛。
    - known_variance 用例不计入硬门槛，但要求 judge 跨 run stable；
      stable=False = eval 自身故障 → 应 FAIL；stable=None（毛刺未验证）不阻断。
    """
    core = [r for r in results if not r.get("known_variance")]
    kv = [r for r in results if r.get("known_variance")]
    core_pass = all(r["verdict"].get("passed") is True for r in core)
    kv_unstable = any(r["verdict"].get("stable") is False for r in kv)
    kv_stable_n = sum(1 for r in kv if r["verdict"].get("stable") is True)
    kv_unstable_n = sum(1 for r in kv if r["verdict"].get("stable") is False)
    kv_unverified_n = sum(1 for r in kv if r["verdict"].get("stable") is None)
    gate = "PASS" if (core_pass and not kv_unstable) else "FAIL"
    return {
        "core": {"total": len(core), "passed": sum(1 for r in core if r["verdict"].get("passed") is True),
                 "gate_included": True},
        "known_variance": {"total": len(kv), "stable": kv_stable_n, "unstable": kv_unstable_n,
                           "unverified": kv_unverified_n},
        "gate": gate,
    }


async def main():
    data = json.load(open(os.path.join(ROOT, "evals/evals.json"), encoding="utf-8"))
    target = [e for e in data["evals"] if e.get("type") == "contract_adherence"]
    only = {int(x) for x in os.environ.get("EVAL_ONLY_IDS", "").split(",") if x.strip()}
    if only:
        target = [e for e in target if e["id"] in only]

    system = "\n\n".join(f"# {os.path.basename(r)}\n{read(r)}" for r in SYSTEM_REFS)
    gen = LLMClient(model=GEN_MODEL, provider=PROVIDER, max_concurrent=2)
    judge = LLMClient(model=JUDGE_MODEL, provider=PROVIDER, max_concurrent=2)

    results = []
    for e in target:
        n = REPEAT if (not REPEAT_IDS or e["id"] in REPEAT_IDS) else 1
        runs = []
        for i in range(n):
            if n > 1:
                print(f"  [repeat {i + 1}/{n}]", flush=True)
            out, verdict = await run_one(e, system, gen, judge)
            runs.append({"output": out, "verdict": verdict})
            print(f"  <- [{e['id']}] passed={verdict.get('passed')} score={verdict.get('score')}", flush=True)

        if n == 1:
            results.append({
                "eval_id": e["id"],
                "name": e["name"],
                "contract": e.get("contract"),
                "known_variance": e.get("known_variance", False),
                "prompt": e["prompt"],
                "output": runs[0]["output"],
                "verdict": runs[0]["verdict"],
            })
            continue

        valid = [r["verdict"] for r in runs if r["verdict"].get("passed") is not None]
        agg_passed = all(v["passed"] for v in valid) if valid else None
        scores = [v.get("score") for v in valid if v.get("score") is not None]
        agg_score = round(sum(scores) / len(scores)) if scores else None
        passed_vals = [r["verdict"].get("passed") for r in runs if r["verdict"].get("passed") is not None]
        stable = (len(set(passed_vals)) <= 1) if passed_vals else None
        results.append({
            "eval_id": e["id"],
            "name": e["name"],
            "contract": e.get("contract"),
            "known_variance": e.get("known_variance", False),
            "prompt": e["prompt"],
            "output": runs[0]["output"],
            "verdict": {
                "passed": agg_passed,
                "score": agg_score,
                "reasons": (valid[0].get("reasons", []) if valid else []),
                "runs": len(runs),
                "all_passed": agg_passed,
                "stable": stable,
                "per_run": [{"passed": r["verdict"].get("passed"), "score": r["verdict"].get("score")} for r in runs],
            },
        })

    summary = compute_summary(results)
    print(f"[gate] core={summary['core']['passed']}/{summary['core']['total']} "
          f"known_variance: stable={summary['known_variance']['stable']} "
          f"unstable={summary['known_variance']['unstable']} "
          f"unverified={summary['known_variance']['unverified']} → {summary['gate']}")

    out_path = os.path.join(ROOT, OUT_PATH)
    json.dump(
        {
            "skill_name": "career-copilot",
            "methodology": f"dynamic-llm (provider={PROVIDER}: gen={GEN_MODEL} + judge={JUDGE_MODEL}) + llm-judge"
                           + (f" + repeat={REPEAT}" if REPEAT > 1 else ""),
            "summary": summary,
            "evals": results,
        },
        open(out_path, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    print("saved ->", out_path)
    sys.exit(0 if summary["gate"] == "PASS" else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        if os.environ.get("EVAL_SKIP_ON_ERROR"):
            print("[skip] LLM 不可达 / 运行异常，按 EVAL_SKIP_ON_ERROR 跳过门禁（exit 0）", file=sys.stderr)
            sys.exit(0)
        import traceback
        traceback.print_exc()
        raise
