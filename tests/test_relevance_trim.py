# -*- coding: utf-8 -*-
"""relevance_trim 单元测试：相关性加权裁剪（确定性、无 LLM、不替人写内容）。"""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import relevance_trim as rt  # noqa: E402


def test_score_bullet_counts_jd_hits():
    # 生产路径：jd_terms 由 _terms(kw) 逐关键词拆字得到（CJK 逐字、拉丁词整体）
    # 注意：英文 "distributed" 不会与中文 "分布式" 互命中（跨语言是已知启发式局限）
    jd_en = rt._terms("python") | rt._terms("distributed")
    assert rt.score_bullet("Used Python for distributed systems", jd_en) == 2
    jd_zh = rt._terms("分布式") | rt._terms("风控")
    # "负责分布式风控模块" 含 分/布/式/风/控 共 5 个 CJK 命中
    assert rt.score_bullet("负责分布式风控模块", jd_zh) == 5
    assert rt.score_bullet("Played ping pong on weekends", jd_en) == 0


def test_trim_skips_without_keywords():
    draft = "\\begin{itemize}\\item A\\item B\\end{itemize}"
    res = rt.trim_draft_by_relevance(draft, None)
    assert res["skipped"] is True
    assert res["text"] == draft


def test_trim_skips_without_items():
    draft = "\\section{X}\nSome paragraph without bullets."
    res = rt.trim_draft_by_relevance(draft, ["Python"])
    assert res["skipped"] is True
    assert res["text"] == draft


def test_trim_drops_least_relevant_and_keeps_order():
    # 预算调小，强制裁切；其中一条与 JD 完全无关（score 0）应被优先裁
    draft = (
        "\\begin{itemize}\n"
        "\\item Led Python distributed system serving 1M QPS\n"      # 相关
        "\\item Built risk-control module with Python\n"            # 相关
        "\\item Won company ping-pong tournament\n"                 # 无关 score 0
        "\\item Optimized distributed cache latency by 40%\n"       # 相关
        "\\end{itemize}\n"
    )
    jd = ["Python", "分布式", "风控"]
    # 把 chars_per_page 设很小，确保超预算触发裁切
    res = rt.trim_draft_by_relevance(draft, jd, page_limit=2, chars_per_page=40)
    assert res["changed"] is True
    assert res["dropped_items"] >= 1
    # 被裁里必须有那条无关的 ping-pong
    snippets = [d["snippet"] for d in res["dropped"]]
    assert any("ping-pong" in s for s in snippets)
    # 保留的条目顺序应保持原始相对顺序（相关条目仍在）
    assert "Led Python distributed" in res["text"]
    assert "risk-control" in res["text"]
    # 被裁条目不再出现在结果中
    assert "ping-pong" not in res["text"]


def test_trim_noop_under_budget():
    draft = "\\begin{itemize}\n\\item Short relevant bullet about Python\n\\end{itemize}\n"
    res = rt.trim_draft_by_relevance(draft, ["Python"], page_limit=2, chars_per_page=3000)
    assert res["changed"] is False
    assert res["dropped_items"] == 0
    assert res["text"] == draft


def test_trim_never_drops_all_items():
    # 极端小预算不应裁光，至少保留 1 条
    draft = "\\begin{itemize}\n\\item A about Python\n\\item B about Python\n\\end{itemize}\n"
    res = rt.trim_draft_by_relevance(draft, ["Python"], page_limit=1, chars_per_page=1)
    assert res["kept_items"] >= 1
