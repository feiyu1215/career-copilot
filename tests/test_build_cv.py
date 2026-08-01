# -*- coding: utf-8 -*-
"""build_cv 单元测试：在没有 TeX 引擎的机器上也能验证逻辑（编排 + 包裹 + 缺引擎显式报错）。

不依赖真实 lualatex/pdflatex：编译与 verify_ats 调用均被 monkeypatch 替换。
"""
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import build_cv  # noqa: E402


def test_wrap_into_document_adds_preamble_for_body():
    # body 视为 drafter 产出的合法 LaTeX，原样嵌入（不转义，避免破坏 \section 等命令）
    body = "\\section{Experience}\nsome text"
    out = build_cv.wrap_into_document(body, name="张三", email="a@b.com", phone="138")
    assert "\\begin{document}" in out
    assert "\\documentclass" in out
    assert "张三" in out
    assert body in out  # 正文原样保留
    # 联系方式的 & 被转义，避免 LaTeX 编译报错（同时满足 ATS [A2] 字面文本）
    assert "a@b.com" in out
    assert "138" in out


def test_wrap_into_document_escapes_user_fields():
    # 用户提供的纯文本字段（姓名）中的 & 必须被转义，否则编译报错
    out = build_cv.wrap_into_document("\\section{X}", name="Tom & Jerry")
    assert "Tom \\& Jerry" in out


def test_wrap_into_document_passthrough_full_doc():
    full = ("\\documentclass{article}\n\\begin{document}\n"
            "\\section{X}\n\\end{document}\n")
    assert build_cv.wrap_into_document(full) == full


def test_find_latex_engine_none(monkeypatch):
    monkeypatch.setattr(build_cv.shutil, "which", lambda _x: None)
    assert build_cv.find_latex_engine() is None


def test_find_latex_engine_prefers_lualatex(monkeypatch):
    # 只让 xelatex 可用，应返回 xelatex（候选顺序中位于 lualatex 之后）
    def fake_which(cmd):
        return "xelatex" if cmd == "xelatex" else None
    monkeypatch.setattr(build_cv.shutil, "which", fake_which)
    assert build_cv.find_latex_engine() == "xelatex"


def test_build_raises_when_no_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(build_cv, "find_latex_engine", lambda: None)
    draft = tmp_path / "draft.tex"
    draft.write_text("\\section{E}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="未找到 LaTeX 引擎"):
        build_cv.build(str(draft))


def test_build_orchestration(monkeypatch, tmp_path):
    # 解耦真实编译与 ATS：用哑实现替换
    def fake_engine():
        return "xelatex"

    def fake_compile(tex_path, engine, out_dir=None):
        out_dir = out_dir or str(Path(tex_path).parent)
        pdf = Path(out_dir) / (Path(tex_path).stem + ".pdf")
        pdf.write_text("%PDF-1.4 dummy", encoding="utf-8")
        return str(pdf)

    monkeypatch.setattr(build_cv, "find_latex_engine", fake_engine)
    monkeypatch.setattr(build_cv, "compile_tex", fake_compile)
    monkeypatch.setattr(build_cv, "run_checks", lambda pdf, keywords, **_kw: ([], ["W1"]))
    # 隔离视觉巡检：避免单测依赖 PyMuPDF 是否安装（未装会追加 [V0] 警告，破坏断言）
    monkeypatch.setattr(build_cv, "inspect_pdf",
                        lambda *a, **k: {"backend": "mock", "issues": []})

    draft = tmp_path / "draft.tex"
    draft.write_text("\\section{Experience}\nsome body", encoding="utf-8")
    out = tmp_path / "cv.pdf"

    res = build_cv.build(str(draft), out_pdf=str(out), keywords=["Python"],
                         name="李四", email="l@x.com")

    assert res["engine"] == "xelatex"
    assert res["failures"] == []
    assert res["warnings"] == ["W1"]
    assert out.exists()
    # 包裹后写入的 pdf 内容来自哑实现
    assert out.read_text(encoding="utf-8").startswith("%PDF")


def test_build_suggests_relevance_trim_only_when_over_page(monkeypatch, tmp_path):
    # 隔离真实编译 / ATS / 视觉巡检，专注验证「超页才建议相关性裁切」逻辑
    monkeypatch.setattr(build_cv, "find_latex_engine", lambda: "xelatex")

    def fake_compile(*a, **k):
        p = tmp_path / "cv.pdf"
        p.write_text("%PDF-1.4 dummy", encoding="utf-8")
        return str(p)

    monkeypatch.setattr(build_cv, "compile_tex", fake_compile)
    monkeypatch.setattr(build_cv, "inspect_pdf",
                        lambda *a, **k: {"backend": "fitz", "pages": 1, "issues": []})

    draft = tmp_path / "draft.tex"
    draft.write_text("\\section{Experience}\nsome body", encoding="utf-8")

    # 超页（页数 3 > 期望 2）→ 应给出 [V-suggest] 提示
    monkeypatch.setattr(
        build_cv, "run_checks",
        lambda pdf, keywords, **_kw: (
            ["[A1] 页数 = 3，期望 2（CV 应严格 2 页）"], []))
    res_over = build_cv.build(str(draft), keywords=["Python"])
    assert any(w.startswith("[V-suggest]") for w in res_over["warnings"])

    # 仅「太短」（页数 1 < 期望 2）→ 不应给出 [V-suggest]（裁切无意义）
    monkeypatch.setattr(
        build_cv, "run_checks",
        lambda pdf, keywords, **_kw: (
            ["[A1] 页数 = 1，期望 2（CV 应严格 2 页）"], []))
    res_under = build_cv.build(str(draft), keywords=["Python"])
    assert not any(w.startswith("[V-suggest]") for w in res_under["warnings"])


def test_redact_demo_text_masks_email_and_phone():
    # [7.1-c] 演示模式正文掩码：真实邮箱 / 手机被虚拟占位替换
    text = "邮箱 a.real@corp.com 手机 13812345678"
    out = build_cv._redact_demo_text(text)
    assert "a.real@corp.com" not in out
    assert "13812345678" not in out
    assert build_cv.REDACT_DEMO_EMAIL in out
    assert build_cv.REDACT_DEMO_PHONE in out


def _fake_compile_capture(tex_path, engine, out_dir=None):
    """哑编译：把 wrapped.tex 内容回报给调用方，并在 out_dir 写出伪 PDF。"""
    out_dir = out_dir or str(Path(tex_path).parent)
    captured = _fake_compile_capture.state
    captured["tex"] = Path(tex_path).read_text(encoding="utf-8")
    pdf = Path(out_dir) / (Path(tex_path).stem + ".pdf")
    pdf.write_text("%PDF-1.4 dummy", encoding="utf-8")
    return str(pdf)


_fake_compile_capture.state = {}


def test_build_cleans_work_dir(monkeypatch, tmp_path):
    # [7.1-a] 编译后 work 临时目录必须被清理，避免真实 PII 残留在 .tex/.aux/.log
    created = {}
    orig_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(prefix="tmp", dir=None):
        p = orig_mkdtemp(prefix=prefix, dir=str(tmp_path) if dir is None else dir)
        created["path"] = p
        return p

    monkeypatch.setattr(build_cv.tempfile, "mkdtemp", spy_mkdtemp)
    monkeypatch.setattr(build_cv, "find_latex_engine", lambda: "xelatex")
    monkeypatch.setattr(build_cv, "compile_tex", _fake_compile_capture)
    monkeypatch.setattr(build_cv, "run_checks", lambda pdf, keywords, **_kw: ([], []))

    draft = tmp_path / "draft.tex"
    draft.write_text("\\section{Experience}\nsome body", encoding="utf-8")
    out = tmp_path / "cv.pdf"
    build_cv.build(str(draft), out_pdf=str(out), name="张三", email="z@s.com", phone="138")

    assert created, "build() 应创建 work 临时目录"
    assert not Path(created["path"]).exists(), "work 临时目录应被清理"
    assert out.exists()


def test_build_redact_demo_substitutes_contact(monkeypatch, tmp_path):
    # [7.1-c] redact_demo=True：页眉联系方式与正文中的真实 PII 均被虚拟值替换
    _fake_compile_capture.state = {}
    monkeypatch.setattr(build_cv, "find_latex_engine", lambda: "xelatex")
    monkeypatch.setattr(build_cv, "compile_tex", _fake_compile_capture)
    monkeypatch.setattr(build_cv, "run_checks", lambda pdf, keywords, **_kw: ([], []))

    draft = tmp_path / "draft.tex"
    draft.write_text(
        "\\section{Experience}\n联系我：real@secret.com 手机 13900001111",
        encoding="utf-8")
    build_cv.build(str(draft), name="真实姓名", email="real@secret.com",
                   phone="13900001111", redact_demo=True)

    tex = _fake_compile_capture.state["tex"]
    assert build_cv.REDACT_DEMO_NAME in tex
    assert build_cv.REDACT_DEMO_EMAIL in tex
    assert build_cv.REDACT_DEMO_PHONE in tex
    # 真实 PII 不应出现在最终产物源码中
    assert "真实姓名" not in tex
    assert "real@secret.com" not in tex
    assert "13900001111" not in tex


def test_build_cover_cleans_work_dir(monkeypatch, tmp_path):
    # [7.1-a] build_cover 同样需清理 work 临时目录
    created = {}
    orig_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(prefix="tmp", dir=None):
        p = orig_mkdtemp(prefix=prefix, dir=str(tmp_path) if dir is None else dir)
        created["path"] = p
        return p

    monkeypatch.setattr(build_cv.tempfile, "mkdtemp", spy_mkdtemp)
    monkeypatch.setattr(build_cv, "find_latex_engine", lambda: "xelatex")
    monkeypatch.setattr(build_cv, "compile_tex", _fake_compile_capture)
    monkeypatch.setattr(build_cv, "run_checks", lambda pdf, k, **_kw: ([], []))

    cover = tmp_path / "cover.tex"
    cover.write_text("Dear HR, body", encoding="utf-8")
    out = tmp_path / "cover.pdf"
    build_cv.build_cover(str(cover), out_pdf=str(out), name="张三",
                         email="z@s.com", phone="138")

    assert created, "build_cover() 应创建 work 临时目录"
    assert not Path(created["path"]).exists(), "build_cover 的 work 目录应被清理"
    assert out.exists()
