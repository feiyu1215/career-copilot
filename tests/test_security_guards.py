# -*- coding: utf-8 -*-
"""security_guards 单元测试：用临时目录验证各项检查，不依赖 git/网络。"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))

import security_guards as sg  # noqa: E402


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_check_gitignore_missing_rule(tmp_path):
    _write(tmp_path / ".gitignore", ".env\nnotes/\n")
    v = []
    sg.check_gitignore(str(tmp_path), v)
    # 缺少 data/ / *.pdf / career_log*.json / draft*.tex
    assert any("data/" in x for x in v)
    assert any("*.pdf" in x for x in v)


def test_check_gitignore_all_present(tmp_path):
    ig = "\n".join(sg.REQUIRED_IGNORE)
    _write(tmp_path / ".gitignore", ig + "\n")
    v = []
    sg.check_gitignore(str(tmp_path), v)
    assert v == []


def test_check_package_manifests_forbidden_script(tmp_path):
    m = tmp_path / ".agents" / "skills" / "x" / "package.json"
    _write(m, json.dumps({"scripts": {"postinstall": "evil"}}))
    v = []
    sg.check_package_manifests(str(tmp_path), v)
    assert any("postinstall" in x for x in v)


def test_check_package_manifests_clean(tmp_path):
    m = tmp_path / ".agents" / "skills" / "x" / "package.json"
    _write(m, json.dumps({"scripts": {"build": "tsc"}}))
    v = []
    sg.check_package_manifests(str(tmp_path), v)
    assert v == []


def test_check_package_manifests_none_present(tmp_path):
    v = []
    sg.check_package_manifests(str(tmp_path), v)
    assert v == []


def test_check_permission_allowlist_skip_when_absent(tmp_path):
    v = []
    sg.check_permission_allowlist(str(tmp_path), v)
    assert v == []


def test_check_permission_allowlist_rejects_unknown(tmp_path):
    s = tmp_path / ".claude" / "settings.json"
    _write(s, json.dumps({"permissions": {"allow": ["Bash(rm -rf:*)"]}}))
    v = []
    sg.check_permission_allowlist(str(tmp_path), v)
    assert any("Bash(rm -rf:*)" in x for x in v)


def test_check_permission_allowlist_allows_known(tmp_path):
    s = tmp_path / ".claude" / "settings.json"
    _write(s, json.dumps({"permissions": {"allow": ["Bash(python:*)"]}}))
    v = []
    sg.check_permission_allowlist(str(tmp_path), v)
    assert v == []
