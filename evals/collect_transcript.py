#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2-3 路径1 盲评脚手架：transcript 采集 CLI（SYNTHETIC-MECHANISM 工具，无 API）。

读一条真实 transcript（JSONL，每行 {"role","text"}），脱敏 + 打元数据标签，
落盘到 evals/transcripts/<phase>/<before|after>/<session_id>.jsonl（协议第二节落盘约定）。

用法：
  python evals/collect_transcript.py --input t.jsonl --phase resume \
      --before-or-after after --model agnes-2.0-flash --session-id s1
  python evals/collect_transcript.py --input t.jsonl --phase match \
      --before-or-after before --model nvidia-x --session-id s2 --no-redact

隐私红线：默认脱敏（复用 proxy_eval_lib.redact_text → career_log.SENSITIVE_PATTERNS）；
仅当你已人工确认输入无 PII 才用 --no-redact。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "evals"))

import proxy_eval_lib as pel  # noqa: E402

_VALID_PHASES = ("match", "interview", "resume", "memory")
_VALID_BOA = ("before", "after")


def collect_session(
    turns: list[dict],
    *,
    phase: str,
    before_or_after: str,
    model: str,
    session_id: str,
    redact: bool = True,
    out_root: str | None = None,
) -> tuple[str, dict, int]:
    """把一轮会话的 turns（[{role,text}, ...]）脱敏 + 打元数据标签 + 落盘。

    落盘位置：``<out_root>/<phase>/<before_or_after>/<session_id>.jsonl``；
    ``out_root`` 默认 ``ROOT/evals/transcripts``。

    返回 ``(out_path, record, n_redacted)``：
    - ``out_path``：落盘绝对路径
    - ``record``：统一 record 结构（见 ``proxy_eval_lib.build_record``）
    - ``n_redacted``：被脱敏命中的 turn 数（``redact=False`` 时恒为 0）

    供 skill session-end 直接调用（无需先落盘 JSONL 中间文件），
    也供未来平台的 hook 程序化采集生产 transcript，使 ``--live`` 盲评可积累真数据。
    """
    if phase not in _VALID_PHASES:
        raise SystemExit(f"[collect] 非法 phase：{phase!r}（可选 {_VALID_PHASES}）")
    if before_or_after not in _VALID_BOA:
        raise SystemExit(f"[collect] 非法 before_or_after：{before_or_after!r}（可选 {_VALID_BOA}）")
    if not turns:
        raise SystemExit("[collect] turns 为空")

    n_redacted = 0
    if redact:
        n_redacted = sum(
            1 for ln in turns if pel.redact_text(ln.get("text", "")) != ln.get("text", "")
        )

    rec = pel.build_record(
        turns, session_id=session_id, phase=phase,
        before_or_after=before_or_after, model=model, redact=redact,
    )

    root = out_root or os.path.join(ROOT, "evals", "transcripts")
    out_dir = os.path.join(root, phase, before_or_after)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{session_id}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out_path, rec, n_redacted


def _read_jsonl(path: str) -> list[dict]:
    lines = []
    with open(path, encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                raise SystemExit(f"[collect] 第 {i} 行非法 JSON：{e}")
            if "role" not in obj or "text" not in obj:
                raise SystemExit(f"[collect] 第 {i} 行缺 role/text 字段：{raw[:80]}")
            lines.append(obj)
    if not lines:
        raise SystemExit("[collect] 输入为空")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="盲评 transcript 采集（脱敏 + 标签 + 落盘）")
    ap.add_argument("--input", required=True, help="输入 JSONL（每行 {role,text}）")
    ap.add_argument("--phase", required=True, choices=list(_VALID_PHASES),
                    help="会话阶段")
    ap.add_argument("--before-or-after", required=True, choices=list(_VALID_BOA),
                    help="契约硬化前(before)/后(after)")
    ap.add_argument("--model", required=True, help="实际生成用的 provider/model")
    ap.add_argument("--session-id", required=True, help="会话唯一 id")
    ap.add_argument("--no-redact", action="store_true", help="跳过脱敏（仅人工确认无 PII 时用）")
    ap.add_argument("--out-root", default=None,
                    help="落盘根目录（默认 ROOT/evals/transcripts）；测试或重定向时用")
    args = ap.parse_args()

    lines = _read_jsonl(args.input)
    out_path, rec, n_redacted = collect_session(
        lines, phase=args.phase, before_or_after=args.before_or_after,
        model=args.model, session_id=args.session_id,
        redact=not args.no_redact, out_root=args.out_root,
    )

    print(f"[collect] 落盘：{out_path}")
    print(f"  session_id={args.session_id} phase={args.phase} "
          f"before_or_after={args.before_or_after} model={args.model}")
    print(f"  turns={len(rec['turns'])} 脱敏命中={n_redacted if not args.no_redact else '已跳过(--no-redact)'}")


if __name__ == "__main__":
    main()
