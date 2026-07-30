#!/usr/bin/env python3
"""
verify_lens.py — 对白 transcript 的软契约（lens）确定性检查

与 verify_output.py 互补：verify_output 检 pipeline 的 scored_results.json（结构化产物），
本脚本检「对白回合」的软契约（①③④：前提来源标注 / 单源红线 / Over-Claim 镜面），
这些契约发生在对话中，不进 scored_results.json。

设计原则（对齐 skill 哲学 addition-criteria.md）：
- 只做「标签存在性」确定性检查，绝不用正则判断「断言是否真的推测」（那是判断，留给人/prompt）。
- 默认 WARNING 模式（非阻断，保灵活性）；--strict 时 WARNING 升级为失败（可作门禁）。
- 显式暴露（契合「隐蔽 fallback 更危险」）。

输入：JSONL，每行 {"role":"agent"|"user","text":"..."}

退出码：
    0 = 无硬失败（WARNING 已显式暴露，非阻断）
    1 = 存在硬失败（如非法 JSONL / 缺字段），或 --strict 下存在 WARNING
"""

import json
import re
import sys
import argparse
from pathlib import Path

# 来源标签：断言必须携带其一，否则视为未标注来源
SOURCE_TAGS = ["[事实]", "[推测]", "[脑补]", "[来源]"]

# 强断言标记（命中且缺来源标签 → LENS-W1）
STRONG_MARKERS = [
    "高度匹配", "稳了", "必中", "完全胜任",
    "够了", "百分百能", "绝对匹配", "毫无悬念", "肯定行",
]

# 绝对化保证标记（命中且缺来源标签 → LENS-W3，Over-Claim 镜面）
# 注："肯定能过" 为绝对化保证语义，仅列于此（不重复进 STRONG_MARKERS），避免同句双 WARNING。
ABSOLUTE_MARKERS = [
    "绝对", "一定", "毫无悬念", "guaranteed", "必定",
    "100%能", "完全没问题", "肯定能过",
]

# 对外简历上下文（命中 + 硬数字 + 缺 [事实] → LENS-W2，单源红线）
RESUME_CTX = ["对外", "投递给", "发给HR", "对外简历", "投出去"]

_NUMBER_RE = re.compile(r"\d+(\.\d+)?\s*%|\d+\s*年")


def has_source_tag(text: str) -> bool:
    return any(tag in text for tag in SOURCE_TAGS)


def has_hard_number(text: str) -> bool:
    return bool(_NUMBER_RE.search(text))


def _snip(text: str, n: int = 40) -> str:
    t = text.replace("\n", " ")
    return t[:n] + ("…" if len(t) > n else "")


def load_transcript(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        print(f"FAIL [L0]: 文件不存在: {path}")
        sys.exit(1)
    turns = []
    for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"FAIL [L0]: 第 {ln} 行非合法 JSON: {e}")
            sys.exit(1)
        if "role" not in obj or "text" not in obj:
            print(f"FAIL [L0]: 第 {ln} 行缺 role/text 字段")
            sys.exit(1)
        turns.append(obj)
    return turns


def run_checks(turns: list[dict]) -> tuple[list[str], list[str]]:
    """返回 (failures, warnings)。
    - failures: 结构化硬失败（如输入损坏）；非空 = 退出码 1。
    - warnings: 软契约违反（LENS-W1/2/3），非致命但显式暴露。
    """
    failures: list[str] = []
    warnings: list[str] = []

    for idx, turn in enumerate(turns):
        if turn.get("role") != "agent":
            continue  # 仅检查 agent 回合；user 回合不归 agent 负责
        text = turn.get("text", "")

        # LENS-W1: 强断言缺来源标签（前提来源标注）
        if any(m in text for m in STRONG_MARKERS) and not has_source_tag(text):
            warnings.append(
                f"[LENS-W1] turn[{idx}] 含强断言但缺来源标签"
                f"（[事实]/[推测]/[脑补]/[来源]）：{_snip(text)}"
            )

        # LENS-W2: 对外简历硬数字缺 [事实]（单源红线）
        if any(c in text for c in RESUME_CTX) and has_hard_number(text) and "[事实]" not in text:
            warnings.append(
                f"[LENS-W2] turn[{idx}] 对外简历含硬数字但缺 [事实] 标注：{_snip(text)}"
            )

        # LENS-W3: 绝对化保证缺来源标签（Over-Claim 镜面）
        if any(m in text for m in ABSOLUTE_MARKERS) and not has_source_tag(text):
            warnings.append(
                f"[LENS-W3] turn[{idx}] 含绝对化保证但缺来源标签"
                f"（Over-Claim 镜面）：{_snip(text)}"
            )

    return failures, warnings


def main():
    parser = argparse.ArgumentParser(
        description="对白 transcript 软契约确定性检查（warning 模式）"
    )
    parser.add_argument("--input", required=True, help="transcript.jsonl 路径")
    parser.add_argument("--strict", action="store_true",
                        help="WARNING 升级为失败（可作门禁）")
    args = parser.parse_args()

    turns = load_transcript(args.input)
    failures, warnings = run_checks(turns)

    if failures:
        print(f"❌ {len(failures)} 项硬失败:\n")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)

    if not warnings:
        print("✅ 对白契约检查通过（无 WARNING）")
        sys.exit(0)

    print(f"⚠️ {len(warnings)} 项 lens WARNING（非致命，但已显式暴露）：")
    for w in warnings:
        print(f"  {w}")
    sys.exit(1 if args.strict else 0)


if __name__ == "__main__":
    main()
