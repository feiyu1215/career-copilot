#!/usr/bin/env python3
"""P2-3 路径2：合成 before/after 提示消融对比。

方法学（因果隔离）：对同一组 4 个 contract_adherence 用例，分别用两套 system 调同一
model + 同一 judge：
  system_after  = SKILL.md + 3 references（契约硬化后，运行时真实上下文）
  system_before = 裸顾问提示（无任何契约指令——前提来源标注 / 单源红线 / 改稿熔断 / Over-Claim 镜面 全部移除）

增量价值 = 把「契约指令本身」对 judge 通过率的贡献，从「模型本来就听话」中分离出来。

诚实标注（不粉饰）：
  - 这是 SYNTHETIC 提示消融基线，不是历史『契约前的真实 skill 输出快照』（无可重建、不可伪造）；
  - 不是真实用户代理：无 production transcript，仅复用 evals.json 的 4 个契约用例；
  - M4 跨模型回归（agnes 3/3 + nvidia 4/4）+ P1-2 已覆盖软契约在真实模型上的稳健性，
    本跑增量有限，价值在因果隔离而非新增可靠性证据；
  - agnes 跨 run 方差已知（case13 95↔45、case14 known_variance），repeat=2 给稳定性信号但不消除。

复用 run_dynamic_eval 的 run_one / JUDGE_SYS(G1 硬化) / SYSTEM_REFS / load_env，避免逻辑分叉。
import run_dynamic_eval 时其 `if __name__=="__main__"` 守卫不会触发 main()，仅执行顶层
env 加载 + 常量 + 函数定义，正好为本脚本准备好 LLMClient 所需的环境变量。

用法（在 career-copilot-copy 根目录）：
  uv run --with openai --python <managed-python> python evals/run_ablation.py
  EVAL_PROVIDER=agnes EVAL_REPEAT=2 EVAL_OUT=evals/before_after_contrast.json \
      python evals/run_ablation.py
"""
import asyncio
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# 复用 run_dynamic_eval：import 时仅跑顶层（load_env + 常量 + 函数定义），不触发 main()
# 注意：只用其常量（SYSTEM_REFS / JUDGE_SYS / read），run_one 在本文件本地实现以支持空结果重试。
from llm_client import PROVIDERS, LLMClient  # noqa: E402
from run_dynamic_eval import JUDGE_SYS, SYSTEM_REFS, read  # noqa: E402

PROVIDER = os.environ.get("EVAL_PROVIDER", "agnes")
_PROV_CFG = PROVIDERS.get(PROVIDER, {})
GEN_MODEL = os.environ.get("EVAL_GEN_MODEL") or _PROV_CFG.get("default_model", "agnes-2.0-flash")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL") or _PROV_CFG.get("default_model", "agnes-2.0-flash")
REPEAT = int(os.environ.get("EVAL_REPEAT", "2"))
# 生成空/异常重试次数（默认 0 = 原行为）：用于把 before 基线里 5/8 的 null 跑成有效数据，得到干净基线。
NULL_RETRIES = int(os.environ.get("EVAL_NULL_RETRIES", "0"))
OUT_PATH = os.environ.get("EVAL_OUT", "evals/before_after_contrast.json")
print(f"[cfg] provider={PROVIDER} gen={GEN_MODEL} judge={JUDGE_MODEL} repeat={REPEAT} "
      f"null_retries={NULL_RETRIES}", file=sys.stderr)

# 裸顾问基线：只给一个「有帮助的求职顾问」角色，移除全部 4 条契约指令。
# 这是合成控制组，用于隔离『契约指令』的因果贡献。
SYSTEM_BEFORE = (
    "你是一名求职顾问，帮助用户做岗位匹配、简历优化、面试准备与职业规划。"
    "请根据用户输入，给出你认为有帮助的建议和判断。"
)

# after = 运行时真实上下文（SKILL.md + 3 references，契约硬化后）
SYSTEM_AFTER = "\n\n".join(f"# {os.path.basename(r)}\n{read(r)}" for r in SYSTEM_REFS)


async def run_one(e, system, gen, judge):
    """生成（带空/异常重试） + judge 一次。复用 run_dynamic_eval 的 JUDGE_SYS 与 judge 逻辑。

    生成空/异常（限流/失败）→ 按 NULL_RETRIES 重试；全部失败 → verdict.passed=None，不中断整跑。
    重试只针对 generation；judge 失败在下方 try/except 兜底（记 passed=None）。
    """
    print(f"  -> 生成 [{e['id']}] {e['name']} ...", flush=True)
    out = None
    last_ex = None
    for attempt in range(1 + NULL_RETRIES):
        try:
            out = await gen.chat(system=system, user=e["prompt"], max_tokens=1500, temperature=0.0)
            if out:
                break
            print(f"  [WARN] [{e['id']}] 生成返回空（限流/失败），attempt {attempt + 1}/{1 + NULL_RETRIES}", flush=True)
        except BaseException as ex:
            last_ex = ex
            print(f"  [ERR] [{e['id']}] 生成异常：{ex!r} attempt {attempt + 1}/{1 + NULL_RETRIES}", flush=True)
        # 退避：空/异常后等限流冷却再试，避免连续撞墙（间隔随尝试数增长）。
        if not out and attempt < NULL_RETRIES:
            await asyncio.sleep(3 * (attempt + 1))
    if not out:
        return None, {"passed": None, "score": None,
                      "reasons": [f"generation failed after {1 + NULL_RETRIES} attempts: {last_ex!r}"
                                  if last_ex else "generation returned empty after retries"]}
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


def _agg(runs):
    """聚合一次模式的多次重复：passed_rate / agg_score / stable / per_run。

    passed_rate = 有效 run 中 passed=True 的比例（生成空/异常 passed=None 不计入分母，
    但单独保留在 per_run 中暴露毛刺）。stable = 有效 run 的 passed 取值是否一致。
    """
    per_run = [{"passed": r["verdict"].get("passed"), "score": r["verdict"].get("score")} for r in runs]
    valid = [r["verdict"] for r in runs if r["verdict"].get("passed") is not None]
    passed_vals = [v.get("passed") for v in valid]
    scores = [v.get("score") for v in valid if v.get("score") is not None]
    passed_count = sum(1 for p in passed_vals if p is True)
    passed_rate = (passed_count / len(passed_vals)) if passed_vals else None
    agg_score = round(sum(scores) / len(scores)) if scores else None
    stable = (len(set(passed_vals)) <= 1) if passed_vals else None
    return {
        "runs": len(runs),
        "passed_rate": passed_rate,
        "agg_score": agg_score,
        "stable": stable,
        "per_run": per_run,
    }


async def run_mode(e, system, gen, judge, mode):
    print(f"  [{mode}] 生成 [{e['id']}] {e['name']} ...", flush=True)
    runs = []
    for i in range(REPEAT):
        if REPEAT > 1:
            print(f"    [{mode} repeat {i + 1}/{REPEAT}]", flush=True)
        out, verdict = await run_one(e, system, gen, judge)
        runs.append({"output": out, "verdict": verdict})
        print(f"    [{mode}] <- [{e['id']}] passed={verdict.get('passed')} "
              f"score={verdict.get('score')}", flush=True)
    return runs


def _runs_from_merge(prev_contrasts, eval_id, mode):
    """从已有对比 JSON 的 per_run 重建 runs（output 置 None，_agg 只用 verdict）。"""
    for c in prev_contrasts:
        if c["eval_id"] == eval_id:
            per_run = c.get(mode, {}).get("per_run", [])
            return [{"output": None, "verdict": {"passed": pr.get("passed"), "score": pr.get("score")}} for pr in per_run]
    return []


async def main():
    data = json.load(open(os.path.join(ROOT, "evals/evals.json"), encoding="utf-8"))
    target = [e for e in data["evals"] if e.get("type") == "contract_adherence"]
    # 分块跑：EVAL_ONLY_IDS 只跑指定 id（如 "11,12"），用于前台避开沙箱前台超时上限。
    only = {int(x) for x in os.environ.get("EVAL_ONLY_IDS", "").split(",") if x.strip()}
    if only:
        target = [e for e in target if e["id"] in only]
    # 单侧跑：EVAL_ONLY_MODE ∈ {both,before,after}，只跑一侧、另一侧从 EVAL_MERGE_FROM 合并，
    # 用于精准补跑某一侧的 null 而不重滚另一侧已好的数据。
    only_mode = os.environ.get("EVAL_ONLY_MODE", "both")

    gen = LLMClient(model=GEN_MODEL, provider=PROVIDER, max_concurrent=2)
    judge = LLMClient(model=JUDGE_MODEL, provider=PROVIDER, max_concurrent=2)

    merge_from = os.environ.get("EVAL_MERGE_FROM", "")
    prev_contrasts = None
    if merge_from and os.path.exists(os.path.join(ROOT, merge_from)):
        prev_contrasts = json.load(open(os.path.join(ROOT, merge_from), encoding="utf-8")).get("contrasts", [])

    contrasts = []
    for e in target:
        if only_mode in ("both", "before"):
            before_runs = await run_mode(e, SYSTEM_BEFORE, gen, judge, "before")
        else:
            before_runs = _runs_from_merge(prev_contrasts, e["id"], "before") if prev_contrasts else []
        if only_mode in ("both", "after"):
            after_runs = await run_mode(e, SYSTEM_AFTER, gen, judge, "after")
        else:
            after_runs = _runs_from_merge(prev_contrasts, e["id"], "after") if prev_contrasts else []
        b = _agg(before_runs)
        a = _agg(after_runs)
        delta_passed = None
        if b["passed_rate"] is not None and a["passed_rate"] is not None:
            delta_passed = round(a["passed_rate"] - b["passed_rate"], 3)
        delta_score = None
        if b["agg_score"] is not None and a["agg_score"] is not None:
            delta_score = a["agg_score"] - b["agg_score"]
        contrasts.append({
            "eval_id": e["id"],
            "name": e["name"],
            "contract": e.get("contract"),
            "known_variance": e.get("known_variance", False),
            "before": b,
            "after": a,
            "delta_passed_rate": delta_passed,
            "delta_score": delta_score,
            "prompt": e["prompt"],
            "expected_output": e["expected_output"],
        })

    # 分块合并：把 EVAL_MERGE_FROM 中「当前未跑」的用例并回来（prev_contrasts 已在上方加载）。
    if prev_contrasts is not None:
        done_ids = {c["eval_id"] for c in contrasts}
        for c in prev_contrasts:
            if c["eval_id"] not in done_ids:
                contrasts.append(c)
        contrasts.sort(key=lambda c: c["eval_id"])

    def _rate(mode_key):
        rates = [c[mode_key]["passed_rate"] for c in contrasts if c[mode_key]["passed_rate"] is not None]
        return round(sum(rates) / len(rates), 3) if rates else None

    summary = {
        "n_contract_cases": len(contrasts),
        "before_overall_pass_rate": _rate("before"),
        "after_overall_pass_rate": _rate("after"),
        "delta_overall_pass_rate": (
            round(_rate("after") - _rate("before"), 3)
            if _rate("after") is not None and _rate("before") is not None else None
        ),
    }

    result = {
        "skill_name": "career-copilot",
        "ablation_type": "prompt-ablation synthetic baseline",
        "honest_caveats": [
            "SYNTHETIC 提示消融基线：before=人为构造的『裸顾问 system（无契约）』，"
            "不是历史『契约前的真实 skill 输出快照』（无可重建，不可伪造）。",
            "不是真实用户代理：无 production transcript，仅复用 evals.json 的 4 个契约用例。",
            "M4 跨模型回归（agnes 3/3 + nvidia 4/4）+ P1-2 已覆盖软契约在真实模型上的稳健性；"
            "本跑增量有限，价值在因果隔离『契约指令』对 judge 通过率的贡献。",
            "agnes 跨 run 方差已知（case13 95↔45、case14 known_variance），repeat=2 给稳定性信号但不消除。",
        ],
        "provider": PROVIDER,
        "gen_model": GEN_MODEL,
        "judge_model": JUDGE_MODEL,
        "repeat": REPEAT,
        "methodology": "同一 4 用例 × {after(SKILL.md+references) vs before(裸顾问)} × 同 judge，隔离契约指令因果贡献。",
        "summary": summary,
        "contrasts": contrasts,
    }
    out_path = os.path.join(ROOT, OUT_PATH)
    json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("saved ->", out_path)

    print("\n=== before/after 提示消融对比 ===")
    for c in contrasts:
        print(f"  id={c['eval_id']} {c['name']} [{ 'KV' if c['known_variance'] else 'core' }]: "
              f"before={c['before']['passed_rate']} after={c['after']['passed_rate']} "
              f"Δpass={c['delta_passed_rate']} Δscore={c['delta_score']}")
    print(f"  OVERALL: before={summary['before_overall_pass_rate']} "
          f"after={summary['after_overall_pass_rate']} "
          f"Δpass={summary['delta_overall_pass_rate']}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        if os.environ.get("EVAL_SKIP_ON_ERROR"):
            print("[skip] LLM 不可达 / 运行异常，按 EVAL_SKIP_ON_ERROR 跳过", file=sys.stderr)
            sys.exit(0)
        import traceback
        traceback.print_exc()
        raise
