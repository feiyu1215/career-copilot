# -*- coding: utf-8 -*-
"""build_cv_docx / build_cv --fallback docx 单元测试（离线，无需 LaTeX）。"""
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
import sys  # noqa: E402

if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import build_cv  # noqa: E402
import build_cv_docx  # noqa: E402
import verify_ats  # noqa: E402

SAMPLE = {
    "sections": [
        {"title": "工作经历",
         "bullets": ["负责推荐系统排序模型迭代，CTR +5%",
                     "主导特征平台治理与稳定性建设"]},
        {"title": "项目经历", "bullets": ["AB 实验平台从0到1"]},
        {"title": "技能", "bullets": ["Python", "PyTorch", "推荐算法"]},
    ]
}


def _write_draft(d, name="draft.json"):
    p = d / name
    p.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    return p


def test_build_docx_creates_file_and_passes_ats(tmp_path):
    draft = _write_draft(tmp_path)
    out = tmp_path / "cv.docx"
    res = build_cv_docx.build_docx(
        draft, out, name="张三", email="zhangsan@example.com",
        phone="13800138000", inspect=True)
    assert Path(res["docx"]).exists()
    assert res["failures"] == [], res["failures"]


def test_build_docx_missing_contact_fails_ats(tmp_path):
    draft = _write_draft(tmp_path)
    out = tmp_path / "cv.docx"
    res = build_cv_docx.build_docx(
        draft, out, name="张三", email="", phone="", inspect=True)
    assert any("[A2]" in f for f in res["failures"]), res["failures"]


def test_tex_to_structured_flattens():
    tex = r"\section{工作经历}\begin{itemize}\item 负责推荐系统\end{itemize}"
    s = build_cv_docx._tex_to_structured(tex)
    assert s["sections"][0]["title"] == "正文"
    assert any("推荐系统" in b for b in s["sections"][0]["bullets"])


def test_build_fallback_docx_produces_docx(tmp_path, monkeypatch):
    # 即便引擎缺失也能产出 docx（非 LaTeX 降级）
    monkeypatch.setattr(build_cv, "find_latex_engine", lambda: None)
    draft = _write_draft(tmp_path)
    out = tmp_path / "cv.docx"
    res = build_cv.build(
        str(draft), out_pdf=str(out), name="李四",
        email="li@example.com", phone="13900139000", fallback="docx")
    assert Path(res["pdf"]).exists()
    assert res["engine"] == "docx-fallback"
    # ATS 文本层检查通过（联系方式齐全）
    assert res["failures"] == [], res["failures"]
    # verify_ats 直接校验 docx 也应通过
    failures, _ = verify_ats.run_checks(res["pdf"])
    assert failures == [], failures


def test_build_fallback_docx_skips_page_check(tmp_path, monkeypatch):
    monkeypatch.setattr(build_cv, "find_latex_engine", lambda: None)
    draft = _write_draft(tmp_path)
    out = tmp_path / "cv.docx"
    res = build_cv.build(
        str(draft), out_pdf=str(out), name="王五",
        email="w@example.com", phone="13700137000", fallback="docx")
    # docx 无 [A1] 页数检查，不应因页数失败
    assert not any(f.startswith("[A1]") for f in res["failures"]), res["failures"]
