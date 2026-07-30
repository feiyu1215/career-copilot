"""check_env.py 单测（Phase 5.1 新增的 LaTeX 引擎 + python-docx 检测）。"""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_env.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("check_env", SCRIPT)
ce = importlib.util.module_from_spec(spec)
sys.modules["check_env"] = ce
spec.loader.exec_module(ce)


def test_detect_latex_engine_found_first_candidate(monkeypatch):
    # lualatex 优先（与 build_cv 优先级一致）
    monkeypatch.setattr(
        ce.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "lualatex" else None
    )
    assert ce.detect_latex_engine() == "lualatex"


def test_detect_latex_engine_falls_through(monkeypatch):
    # lualatex/xelatex 缺失，pdflatex 命中
    def fake_which(name):
        return f"/usr/bin/{name}" if name == "pdflatex" else None

    monkeypatch.setattr(ce.shutil, "which", fake_which)
    assert ce.detect_latex_engine() == "pdflatex"


def test_detect_latex_engine_missing(monkeypatch):
    monkeypatch.setattr(ce.shutil, "which", lambda name: None)
    assert ce.detect_latex_engine() is None


def test_main_reports_latex_label(monkeypatch, capsys):
    # 注入一个可用引擎，确保 LaTeX 检测项出现在状态表里（不依赖真实环境）
    monkeypatch.setattr(
        ce.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "lualatex" else None
    )
    with pytest.raises(SystemExit):
        ce.main()  # 网络多半不可达 → 退出码非 0，但不得崩溃
    out = capsys.readouterr().out
    assert "LaTeX" in out
    assert "python-docx" in out
