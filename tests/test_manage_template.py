# -*- coding: utf-8 -*-
"""U6 模板注册单元测试：校验 / 展开 / 冒烟编译 / 增删查，不依赖真实 TeX 引擎。

编译与引擎定位均被 monkeypatch；注册表与模板落盘指向临时目录。
"""
import importlib
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import manage_template as mt  # noqa: E402


GOOD_TPL = (
    "\\documentclass{article}\n\\begin{document}\n"
    "\\centerline{__CV_NAME__ \\bullet __CV_EMAIL__ \\bullet __CV_PHONE__}\n"
    "__CV_BODY__\n\\end{document}\n"
)
BAD_TPL_NO_BODY = (
    "\\documentclass{article}\n\\begin{document}\n"
    "no body token here\n\\end{document}\n"
)
BAD_TPL_NOT_FULL = "\\section{X}\n__CV_BODY__\n"


@pytest.fixture
def isolated_templates(tmp_path, monkeypatch):
    """把模板仓库重定向到临时目录，并 stub 引擎/编译。"""
    monkeypatch.setattr(mt, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(mt, "find_latex_engine", lambda: "lualatex")
    monkeypatch.setattr(mt, "compile_tex",
                        lambda tex, engine, out_dir=None: str(
                            Path(out_dir or Path(tex).parent)
                            / (Path(tex).stem + ".pdf")))
    return tmp_path


def test_validate_template_good():
    assert mt.validate_template(GOOD_TPL) == []


def test_validate_template_missing_body_token():
    errs = mt.validate_template(BAD_TPL_NO_BODY)
    assert any("__CV_BODY__" in e for e in errs)


def test_validate_template_not_full_document():
    errs = mt.validate_template(BAD_TPL_NOT_FULL)
    assert any("完整 LaTeX 文档" in e for e in errs)


def test_expand_template_substitutes_and_escapes():
    out = mt.expand_template(GOOD_TPL, body="\\section{E}",
                             name="Tom & Jerry", email="a@b.com", phone="138")
    assert "\\section{E}" in out
    assert "__CV_BODY__" not in out
    assert "Tom \\& Jerry" in out  # 姓名 & 被转义
    assert "a@b.com" in out
    assert "138" in out


def test_add_template_rejects_bad_name(isolated_templates):
    src = isolated_templates / "t.tex"
    src.write_text(GOOD_TPL, encoding="utf-8")
    res = mt.add_template("bad name!", str(src))
    assert res["ok"] is False
    assert "模板名" in res["message"]


def test_add_template_rejects_invalid_template(isolated_templates):
    src = isolated_templates / "t.tex"
    src.write_text(BAD_TPL_NO_BODY, encoding="utf-8")
    res = mt.add_template("mine", str(src))
    assert res["ok"] is False
    assert "__CV_BODY__" in res["message"]
    assert "mine" not in mt.load_registry()


def test_add_template_rejects_smoke_failure(isolated_templates, monkeypatch):
    monkeypatch.setattr(mt, "compile_tex",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("boom")))
    src = isolated_templates / "t.tex"
    src.write_text(GOOD_TPL, encoding="utf-8")
    res = mt.add_template("mine", str(src))
    assert res["ok"] is False
    assert res["errors"] == ["smoke_failed"]
    assert "mine" not in mt.load_registry()


def test_add_template_success_and_list(isolated_templates):
    src = isolated_templates / "t.tex"
    src.write_text(GOOD_TPL, encoding="utf-8")
    res = mt.add_template("mine", str(src))
    assert res["ok"] is True
    assert (isolated_templates / "mine.tex").exists()
    items = mt.list_templates()
    assert any(it["name"] == "mine" for it in items)


def test_render_template_expands_registered(isolated_templates, tmp_path):
    src = isolated_templates / "t.tex"
    src.write_text(GOOD_TPL, encoding="utf-8")
    mt.add_template("mine", str(src))
    out = tmp_path / "out.tex"
    mt.render_template("mine", "\\section{Exp}", str(out),
                       name_field="张三", email="z@x.com")
    txt = out.read_text(encoding="utf-8")
    assert "\\section{Exp}" in txt
    assert "张三" in txt


def test_remove_template(isolated_templates):
    src = isolated_templates / "t.tex"
    src.write_text(GOOD_TPL, encoding="utf-8")
    mt.add_template("mine", str(src))
    assert mt.remove_template("mine") is True
    assert "mine" not in mt.load_registry()
    assert mt.remove_template("nope") is False


def test_add_template_real_smoke_compile(tmp_path):
    """真实 lualatex 冒烟编译（无引擎则 skip）；注册后清理，不留产物。"""
    if mt.find_latex_engine() is None:
        pytest.skip("本机无 LaTeX 引擎")
    src = tmp_path / "t.tex"
    src.write_text(GOOD_TPL, encoding="utf-8")
    try:
        res = mt.add_template("realtest", str(src))
        assert res["ok"] is True
    finally:
        mt.remove_template("realtest")
