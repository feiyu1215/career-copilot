#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""relevance_trim.py — 简历超页时「按相关性而非按时间」裁页。

背景（诚实定位）：
  「相关性加权裁剪」会在 CV 超出页数时，按与 JD 的相关度
  裁掉最不相关的条目，而不是简单地砍掉最旧的内容。U1 的 build_cv 只做
  「编译 + ATS 文本校验」，缺这一环。本模块补齐它。

设计原则（不越界替人决策）：
  - 只「裁」用户自己写过的真实条目（\\item 子弹点），绝不凭空编造或改写内容。
  - 全部确定性（无 LLM）：相关度 = 子弹点文本与 JD 关键词集合的命中数；
    为避免过度偏好长条目，裁切顺序 = (命中数升序, 条目长度降序)。
  - 这是「辅助 + 报告」：返回被裁条目的明细与理由，最终是否采用由人决定。
  - 仅在超过页数预算时才裁；未超预算或缺少 JD 关键词时原样返回（no-op）。

使用方式：
    python3 relevance_trim.py --draft draft.tex --keywords "Python,分布式,风控" --page-limit 2
    # 也可作为库：from relevance_trim import trim_draft_by_relevance
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# 拉丁词（含数字）
_LATIN = re.compile(r"[a-z0-9]+")
# CJK 单字（中文无空格，逐字作 token）
_CJK = re.compile(r"[一-鿿]")
# LaTeX 命令/符号（用于估算可见字符时剥离）
_CMD = re.compile(r"\\[a-zA-Z]+\*?|\\.|\s+")
# 子弹点边界
_ITEM = re.compile(r"\\item\b")


def _terms(text: str) -> set[str]:
    """把文本拆成小写 token 集合（拉丁词 + CJK 单字）。"""
    low = text.lower()
    out = set(_LATIN.findall(low))
    out.update(_CJK.findall(low))
    return out


def _visible_chars(text: str) -> int:
    """估算渲染后可见字符数：去注释、去 LaTeX 命令与空白。"""
    text = re.sub(r"(?<!\\)%.*", "", text)
    text = _CMD.sub("", text)
    return len(text.strip())


def score_bullet(bullet_text: str, jd_terms: set[str]) -> int:
    """子弹点与 JD 的相关度 = 命中的 JD 关键词（去重计数）。

    命中数为 0 表示与本条 JD 完全无关，是最优先裁切对象；命中越多越该保留。
    """
    return len(_terms(bullet_text) & jd_terms)


def _estimate_chars(text: str) -> int:
    """整篇草稿的可见字符估算（用于页数预算）。"""
    return _visible_chars(text)


def trim_draft_by_relevance(
    draft_text: str,
    jd_keywords: list[str] | None,
    page_limit: int = 2,
    chars_per_page: int = 3000,
) -> dict:
    """按相关性裁剪超页草稿。返回结构化结果（含被裁明细，供人复核）。

    - jd_keywords 为空 → 无法评分，原样返回并标记 skipped。
    - 草稿无 \\item → 无可裁单元，原样返回。
    - 未超预算 → 不裁，返回 kept 全量。
    - 超预算 → 反复裁掉「最不相关 / 同等相关下最长」的子弹点，直到预算内
      （且至少保留 1 个子弹点，避免裁光）。
    """
    result = {
        "changed": False,
        "skipped": False,
        "kept_items": 0,
        "dropped_items": 0,
        "dropped": [],          # [{snippet, score}]
        "est_chars_before": 0,
        "est_chars_after": 0,
        "text": draft_text,
    }

    if not jd_keywords:
        result["skipped"] = True
        result["reason"] = "缺少 JD 关键词，无法按相关性评分（保持原样）"
        result["est_chars_before"] = _estimate_chars(draft_text)
        result["est_chars_after"] = result["est_chars_before"]
        return result

    jd_terms = set()
    for kw in jd_keywords:
        jd_terms.update(_terms(kw))

    idxs = [m.start() for m in _ITEM.finditer(draft_text)]
    if not idxs:
        result["skipped"] = True
        result["reason"] = "草稿无 \\item 子弹点，无可裁单元（保持原样）"
        result["est_chars_before"] = _estimate_chars(draft_text)
        result["est_chars_after"] = result["est_chars_before"]
        return result

    preamble = draft_text[: idxs[0]]
    segments = []
    for i, s in enumerate(idxs):
        e = idxs[i + 1] if i + 1 < len(idxs) else len(draft_text)
        segments.append(draft_text[s:e])

    budget = page_limit * chars_per_page
    est = _estimate_chars(draft_text)
    result["est_chars_before"] = est

    dropped: list[dict] = []
    kept = list(segments)

    # 反复裁切，直到预算内或无可裁
    while est > budget and len(kept) > 1:
        # 计算各段得分（段首 \item 之后内容）
        scored = []
        for seg in kept:
            content = seg.split("\\item", 1)[1] if "\\item" in seg else seg
            scored.append((score_bullet(content, jd_terms), len(content), seg))
        # 裁切顺序：命中数升序（最不相关优先），同等下长度降序（先裁长）
        scored.sort(key=lambda t: (t[0], -t[1]))
        victim = scored[0][2]
        snippet = victim.split("\\item", 1)[1].strip()[:40] if "\\item" in victim else victim.strip()[:40]
        dropped.append({"snippet": snippet, "score": scored[0][0]})
        kept.remove(victim)
        est = _estimate_chars(preamble + "".join(kept))

    if dropped:
        result["changed"] = True
        new_text = preamble + "".join(kept)
        result["text"] = new_text
        result["dropped"] = dropped
        result["dropped_items"] = len(dropped)
        result["kept_items"] = len(kept)
        result["est_chars_after"] = _estimate_chars(new_text)
    else:
        result["est_chars_after"] = est
        result["kept_items"] = len(segments)

    return result


def main() -> None:
    p = argparse.ArgumentParser(description="按相关性（而非时间）裁剪超页简历草稿")
    p.add_argument("--draft", required=True, help="drafter_reviewer 产出的 .tex 草稿")
    p.add_argument("--keywords", help="JD 关键词，逗号分隔（相关性评分依据）")
    p.add_argument("--page-limit", type=int, default=2, help="页数预算（默认 2）")
    p.add_argument("--chars-per-page", type=int, default=3000,
                   help="每页可见字符估算（用于预算，默认 3000）")
    p.add_argument("--out", default=None, help="输出路径（默认覆盖草稿）")
    args = p.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()] \
        if args.keywords else None
    draft_text = Path(args.draft).read_text(encoding="utf-8")
    res = trim_draft_by_relevance(draft_text, keywords,
                                  page_limit=args.page_limit,
                                  chars_per_page=args.chars_per_page)

    if res["skipped"]:
        print(f"[relevance_trim] ⏭ 跳过：{res.get('reason', '')}")
    elif res["changed"]:
        out = args.out or args.draft
        Path(out).write_text(res["text"], encoding="utf-8")
        print(f"[relevance_trim] ✂ 裁掉 {res['dropped_items']} 条最不相关子弹点"
              f"（保留 {res['kept_items']}）；估算字符 {res['est_chars_before']}"
              f" → {res['est_chars_after']}（预算 {args.page_limit * args.chars_per_page}）")
        print("  被裁明细（score=与 JD 命中关键词数，0=完全无关）：")
        for d in res["dropped"]:
            print(f"    - [score={d['score']}] {d['snippet']!r}")
        print(f"   写入：{out}（请人工复核后再编译）")
    else:
        print(f"[relevance_trim] ✓ 未超预算，无需裁切（估算字符 {res['est_chars_after']}"
              f" ≤ 预算 {args.page_limit * args.chars_per_page}）")


if __name__ == "__main__":
    main()
