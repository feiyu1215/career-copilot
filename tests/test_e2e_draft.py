#!/usr/bin/env python3
"""
test_e2e_draft.py — Phase 3.3 端到端回归测试（其二）：生成 → 编译链路

验证 Tier2「草稿 → 模板展开 → LaTeX 编译」最后一公里不退化：
1. DrafterReviewer.draft 在 mock LLM 下产出 LaTeX 正文；
2. manage_template.expand_template 把 __CV_BODY__ 占位符**真实展开**（断言占位符消失、正文落入）；
3. build_cv.compile_tex 用本机 lualatex 真实编译为 PDF（断言产物存在）。

离线能力：draft/review 走 mock LLM（无网关依赖）。编译需要本机 LaTeX 引擎，
缺失时该步 skip（与计划「CI 需装 TeX Live」一致；本机 MiKTeX 已具备）。
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import llm_client          # noqa: E402
import manage_template     # noqa: E402
import build_cv            # noqa: E402
from drafter_reviewer import DrafterReviewer  # noqa: E402


# 最小完整 LaTeX 模板（ASCII，确保 lualatex 干净编译；本测试关注「链路」而非 CJK 渲染）
DRAFT_TEMPLATE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=1.8cm]{geometry}
\setlength{\parindent}{0pt}
\begin{document}
{\Large\bfseries __CV_NAME__}\\
\noindent __CV_EMAIL__ ~$\bullet$~ __CV_PHONE__\\[0.6em]
__CV_BODY__
\vfill
\end{document}
"""

# mock LLM 返回的正文（必须是合法 LaTeX 片段，且不得含 __CV_BODY__ 自身）
DRAFT_BODY = (
    r"\section{Experience}"
    r"\textbf{Search Recommendation Strategy} -- improved CTR by 12\%."
    r"\section{Skills}Python, Machine Learning, Recommender Systems."
)

PROFILE = {
    "role_type": "搜索推荐策略专家",
    "direction_anchors": ["搜索推荐", "算法策略"],
    "hard_negatives": ["纯运维"],
    "skills": ["搜索", "推荐"],
    "years_experience": 5,
    "english_evidence": {"level": "basic"},
    "education": {"tier": "medium"},
}
JD_TEXT = "负责搜索推荐策略优化，提升核心场景转化。"


class _DraftMockClient:
    """mock LLM：draft/review 都返回固定字符串（review 只需一个字符串意见）。"""

    def __init__(self, *a, **k):
        self.provider_name = "mock"
        self.model = "mock"
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def chat(self, system, user, temperature=0.0, max_tokens=2000):
        # review 的确定性契约由 drafter_reviewer.check_hard_contracts 跑（无需 LLM），
        # 这里 LLM 意见返回一段固定文本即可。
        return DRAFT_BODY if "草稿" in system or "Draft" in system else "LLM review: OK."


@pytest.fixture
def patch_llm(monkeypatch):
    monkeypatch.setattr(llm_client, "LLMClient", lambda *a, **k: _DraftMockClient(*a, **k))


def test_e2e_draft_expands_cv_body_and_compiles(patch_llm, tmp_path):
    # 1) draft（mock LLM）
    draft = asyncio.run(DrafterReviewer().draft(PROFILE, JD_TEXT))
    assert "__CV_BODY__" not in draft, "draft 正文不应含模板占位符"
    assert "Experience" in draft

    # 2) 模板展开：__CV_BODY__ 必须被真实替换（占位符消失 + 正文落入）
    rendered = manage_template.expand_template(
        DRAFT_TEMPLATE, draft, name="Test User",
        email="test@example.com", phone="13800000000")
    assert "__CV_BODY__" not in rendered, "模板展开后 __CV_BODY__ 应已被替换"
    assert DRAFT_BODY.split("\n")[0] in rendered or "Experience" in rendered
    assert "Test User" in rendered and "test@example.com" in rendered

    # 3) 真实编译（本机 lualatex）
    engine = build_cv.find_latex_engine()
    if engine is None:
        pytest.skip("本机无 LaTeX 引擎（lualatex/xelatex/pdflatex），跳过真实编译")

    tex_path = tmp_path / "cv.tex"
    tex_path.write_text(rendered, encoding="utf-8")
    pdf = build_cv.compile_tex(str(tex_path), engine, out_dir=str(tmp_path))
    assert Path(pdf).exists(), f"lualatex 编译未产出 PDF：{pdf}"


def test_e2e_review_structure(patch_llm):
    # review 双轨：确定性契约（无 LLM）+ LLM 意见；无论 draft 是否违规都返回结构化 dict
    report = asyncio.run(DrafterReviewer().review(DRAFT_BODY, PROFILE, JD_TEXT))
    assert "deterministic_violations" in report
    assert "llm_review" in report
    assert "passed" in report
    assert isinstance(report["deterministic_violations"], list)
