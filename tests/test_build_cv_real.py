#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_build_cv_real.py — build_cv 的 *真实* 编译闭环测试（非 monkeypatch）。

本机已安装 MiKTeX（D:\\Program Files\\MiKTeX\\miktex\bin\x64\\），lualatex/xelatex/
pdflatex 均可用。本测试用真实引擎把 .tex 编译成 PDF，再用 verify_ats 做文本层 +
硬不变量校验，证明「编译 → ATS」链路在本环境确实可跑通，而不是只能 mock。

无 LaTeX 引擎的环境（如 CI 无 TeX）自动 skip，不阻塞。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import build_cv  # noqa: E402
import verify_ats  # noqa: E402

# 1 页文档用到的 ATS 约束覆盖（仓库默认 page_count=2，此处按真实 1 页 CV 放宽）
_ONE_PAGE_ATS = {"ats": {"page_count": 1, "require_contact": True, "forbid_garbled": True}}


@pytest.fixture
def latex_available():
    engine = build_cv.find_latex_engine()
    if engine is None:
        pytest.skip("本机未安装 LaTeX 引擎（lualatex/xelatex/pdflatex 均不可用），跳过真实编译测试")
    return engine


def test_find_latex_engine_real(latex_available):
    # 真实引擎确实存在（不是 mock）
    assert latex_available in ("lualatex", "xelatex", "pdflatex")
    assert shutil.which(latex_available)


def test_compile_real_produces_pdf(latex_available, tmp_path):
    body = r"\section{Experience}Worked on distributed systems and risk control."
    tex = tmp_path / "draft.tex"
    tex.write_text(body, encoding="utf-8")
    wrapped_tex = tmp_path / "cv_wrapped.tex"
    wrapped_tex.write_text(
        build_cv.wrap_into_document(body, name="John Doe",
                                    email="john@example.com", phone="13800138000"),
        encoding="utf-8",
    )
    pdf = build_cv.compile_tex(str(wrapped_tex), latex_available, out_dir=str(tmp_path))
    assert Path(pdf).exists()
    raw = Path(pdf).read_bytes()
    assert raw[:5] == b"%PDF-", "产出不是合法 PDF（缺少 %PDF 头）"


def test_build_real_pipeline(latex_available, tmp_path):
    # 真实端到端：.tex 草稿 → 编译 → ATS 校验，返回无 [A#] 硬失败
    body = (
        r"\section{Experience}"
        r"\begin{itemize}\item Built risk-control pipelines."
        r"\item Optimized distributed job matching.\end{itemize}"
    )
    draft = tmp_path / "draft.tex"
    draft.write_text(body, encoding="utf-8")
    out_pdf = tmp_path / "cv.pdf"
    res = build_cv.build(
        str(draft), out_pdf=str(out_pdf),
        name="John Doe", email="john@example.com", phone="13800138000",
        constraints=_ONE_PAGE_ATS,
    )
    assert Path(res["pdf"]).exists()
    assert res["engine"] in ("lualatex", "xelatex", "pdflatex")
    assert res["failures"] == [], f"ATS 硬失败：{res['failures']}"
    # 文本层能抽出资讯方式（[A2] 字面文本，非图标）
    text, pages, _ = verify_ats.read_pdf(str(out_pdf))
    assert "john@example.com" in text
    assert "13800138000" in text
    assert pages == 1


def test_ats_on_real_pdf(latex_available, tmp_path):
    body = r"\section{Skills}Python, distributed systems, risk control."
    draft = tmp_path / "draft.tex"
    draft.write_text(body, encoding="utf-8")
    out_pdf = tmp_path / "cv.pdf"
    build_cv.build(str(draft), out_pdf=str(out_pdf),
                   name="John Doe", email="john@example.com", phone="13800138000",
                   constraints=_ONE_PAGE_ATS)
    failures, warnings = verify_ats.run_checks(
        str(out_pdf), jd_keywords=["Python", "risk"], constraints=_ONE_PAGE_ATS)
    assert failures == [], f"ATS 硬失败：{failures}"
    # 关键词覆盖为 advisory，至少应报告命中情况
    assert any("关键词覆盖" in w for w in warnings)
