#!/usr/bin/env python3
"""A/B 探针：同一份 case13 输出，分别用 G1 前(OLD)/后(NEW) 的 JUDGE_SYS 判分，查 G1 是否误伤。

复用 run_dynamic_eval.py 的 NEW_JUDGE_SYS（当前含 G1 细则）；OLD_JUDGE_SYS 为本脚本硬编码的
G1 前版本（仅差「Over-Claim 判定细则」一段）。取：
  - FAIL 输出：eval_results_dynamic_agnes_g2.json 的 case13（G2 批次判 45）
  - PASS 输出：eval_results_dynamic_agnes_case13_probe.json 的 case13（补跑判 95）
对同一输出各跑 OLD/NEW judge，对比 passed/score/reasons。

判定：
  - FAIL 输出 OLD=pass 且 NEW=fail → G1 误伤确认（需回松 G1 细则）
  - FAIL 输出 OLD=fail 且 NEW=fail → 非 judge 误伤，失败源于生成方差（agnes 偶发漏触发熔断前置声明）→ 走 B
消耗 4 次 judge 调用（无 gen）。
"""
import asyncio
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "evals"))


# .env 加载抽到 evals/eval_env.py（M1：统一三处；覆盖式语义，与 run_dynamic_eval 一致）。
from eval_env import load_provider_env  # noqa: E402

load_provider_env()  # 先于 import llm_client，避免模块级快照为空

from llm_client import LLMClient  # noqa: E402
from run_dynamic_eval import JUDGE_SYS as NEW_JUDGE_SYS  # 当前（含 G1 细则）  # noqa: E402

# G1 前版本：与 NEW 仅差「Over-Claim 判定细则」一段，其余完全一致。
OLD_JUDGE_SYS = (
    "你是严格的求职 Agent 评测裁判。判断 Agent 实际输出是否符合「预期形态」中列出的"
    "契约要求。重点检查：① 前提来源标注——是否给结论或用户断言打了 [事实]/[推测]/[脑补] 标签；"
    "② 单源红线——是否拒绝把单源未复现数字写进对外简历；③ 改稿熔断——是否**前置声明**了"
    "锁原稿 hash 与 >60% 暂停策略（高改写场景必须前置，不要求真改到 60%）；④ Over-Claim 镜面——"
    "是否对回应/用户断言跑了四面镜子，不偷换论题、不过度承诺。**关键：澄清或延后回合里只要『套了 lens』"
    "（如把用户断言标为 [推测]、给出『你具备X、缺口在Z』的可证伪结构、或声明熔断策略）即视为符合契约，"
    "不要求必须产出完整成稿。** 只返回一个 JSON 对象，不要任何额外文字："
    '{"passed": true/false, "score": 0-100, "reasons": ["..."]}'
)

PROVIDER = os.environ.get("EVAL_PROVIDER", "agnes")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL") or "agnes-2.0-flash"


def _read_output(json_path, eval_id):
    data = json.load(open(os.path.join(ROOT, json_path), encoding="utf-8"))
    for r in data["evals"]:
        if r["eval_id"] == eval_id:
            return r["output"]
    raise SystemExit(f"未找到 {json_path} 中的 case {eval_id}")


async def judge_one(judge, sys_prompt, eval_obj, output):
    user = json.dumps(
        {
            "eval_name": eval_obj["name"],
            "contract": eval_obj.get("contract"),
            "用户输入": eval_obj["prompt"],
            "预期形态": eval_obj["expected_output"],
            "Agent实际输出": output,
        },
        ensure_ascii=False,
    )
    jr = await judge.chat(system=sys_prompt, user=user, max_tokens=600, temperature=0.0)
    m = re.search(r"\{.*\}", jr, re.S)
    try:
        return json.loads(m.group(0)) if m else {"passed": None, "raw": jr}
    except Exception:
        return {"passed": None, "raw": jr}


async def main():
    data = json.load(open(os.path.join(ROOT, "evals/evals.json"), encoding="utf-8"))
    e13 = next(e for e in data["evals"] if e["id"] == 13)
    fail_out = _read_output("evals/eval_results_dynamic_agnes_g2.json", 13)
    pass_out = _read_output("evals/eval_results_dynamic_agnes_case13_probe.json", 13)

    judge = LLMClient(model=JUDGE_MODEL, provider=PROVIDER, max_concurrent=1)

    print(f"[cfg] provider={PROVIDER} judge={JUDGE_MODEL}\n")

    print("=== A/B #1: 同一份 FAIL 输出（G2 批次，原判 45）===")
    old_fail = await judge_one(judge, OLD_JUDGE_SYS, e13, fail_out)
    new_fail = await judge_one(judge, NEW_JUDGE_SYS, e13, fail_out)
    print(f"  OLD -> passed={old_fail.get('passed')} score={old_fail.get('score')}")
    print(f"       reasons: {old_fail.get('reasons')}")
    print(f"  NEW -> passed={new_fail.get('passed')} score={new_fail.get('score')}")
    print(f"       reasons: {new_fail.get('reasons')}")

    print("\n=== A/B #2: 同一份 PASS 输出（补跑，原判 95）===")
    old_pass = await judge_one(judge, OLD_JUDGE_SYS, e13, pass_out)
    new_pass = await judge_one(judge, NEW_JUDGE_SYS, e13, pass_out)
    print(f"  OLD -> passed={old_pass.get('passed')} score={old_pass.get('score')}")
    print(f"  NEW -> passed={new_pass.get('passed')} score={new_pass.get('score')}")

    print("\n=== 结论 ===")
    if old_fail.get("passed") is True and new_fail.get("passed") is False:
        print("  >> G1 误伤确认：同一 FAIL 输出 OLD 判过、NEW 判挂。需回松 G1 细则。")
    elif old_fail.get("passed") is False and new_fail.get("passed") is False:
        print("  >> 非 judge 误伤：OLD/NEW 对同一 FAIL 输出都判挂（主因是③熔断前置声明缺失，与 G1 无关）。失败源于生成方差 → 走 B（few-shot 稳生成）。")
    else:
        print(f"  >> 边界情况：OLD_FAIL={old_fail.get('passed')} NEW_FAIL={new_fail.get('passed')}，需人工看 reasons。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        import traceback
        traceback.print_exc()
        raise
