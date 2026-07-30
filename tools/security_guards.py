#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""security_guards.py — 提交前 / CI 护栏（纯 stdlib，零依赖）。

本文件落地升级建议 U3：把安全从「仅查 .env」升到「权限级 + 个人数据 + 供应链」强执行，
对齐 supply-chain guards 思路，但适配本仓事实：
  - 本仓 .gitignore 此前只覆盖 .env/notes/data/seen_jobs.json，缺少 *.pdf /
    career_log*.json / draft*.tex（生成的 CV PDF、脱敏日志、草稿均含个人数据）。
  - 本仓当前无 package.json、无 settings.json（权限配置由接入的 Agent 框架承载），
    故对应检查为「存在才强制」的前瞻护栏，不臆造约束。

检查项：
  1. .gitignore 必须包含敏感/个人数据模式（见 REQUIRED_IGNORE）。
  2. git 已跟踪文件中不得出现 .env（防密钥泄露）。
  3. .agents/**/package.json（若存在）不得含生命周期脚本与 trustedDependencies。
  4. （若框架接入）.claude/settings.json 或 .agents/**/settings*.json 的权限 allow
     必须落在 ALLOWED_PERMISSIONS 白名单；放宽须在同 PR 显式加入。当前无此类文件则跳过。

返回违规列表；有违规则退出码 1。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# 必须出现在 .gitignore 的敏感/个人数据模式
REQUIRED_IGNORE = [
    ".env", "*.env", "*.env.local",
    "notes/",
    "data/",             # 覆盖 seen_jobs.json 及运行时生成物（含产出 PDF/缓存）
    "*.pdf",             # 生成的 CV/求职信 PDF 含个人数据
    "career_log*.json",  # career_log 导出（即便已脱敏也不入库）
    "draft*.tex",        # drafter_reviewer 草稿含个人简历
]

# 若框架接入 settings.json，权限 allow 必须落在白名单（放宽须同 PR 显式加入）
ALLOWED_PERMISSIONS = {
    "Bash(python:*)",
    "Bash(python3:*)",
    "Bash(pdftotext:*)",
    "Bash(pdfinfo:*)",
    "Bash(lualatex:*)",
    "Bash(xelatex:*)",
    "Bash(pdflatex:*)",
    "Bash(bun run:*)",
    "Bash(boss:*)",
    "Bash(bsk:*)",
}

# package.json 禁止的生命周期脚本（bun/npm install 会执行）
FORBIDDEN_SCRIPTS = {"preinstall", "install", "postinstall", "prepare", "prepack"}


def _gitignore_patterns(repo: str) -> set[str]:
    p = os.path.join(repo, ".gitignore")
    if not os.path.exists(p):
        return set()
    pats = set()
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                pats.add(line)
    return pats


def _tracked_files(repo: str) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", repo, "ls-files"],
                             capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return []
    return [ln for ln in out.stdout.splitlines() if ln]


def check_gitignore(repo: str, violations: list[str]) -> None:
    ignore = _gitignore_patterns(repo)
    for pat in REQUIRED_IGNORE:
        if pat not in ignore:
            violations.append(f".gitignore 缺少敏感/个人数据模式: {pat}")


def check_tracked_secrets(repo: str, violations: list[str]) -> None:
    for f in _tracked_files(repo):
        if (os.path.basename(f) == ".env" or f.endswith(".env")
                or f.endswith(".env.local") or "/.env" in f):
            violations.append(f"敏感文件已被 git 跟踪: {f}")


def check_package_manifests(repo: str, violations: list[str]) -> None:
    root = Path(repo)
    manifests = [p for p in root.glob(".agents/**/package.json")
                 if "node_modules" not in p.parts]
    if not manifests:
        return  # 本仓无 package.json，跳过（不误报）
    for manifest in manifests:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            violations.append(f"{manifest}: 无法读取/非法 JSON: {exc}")
            continue
        if not isinstance(data, dict):
            violations.append(f"{manifest}: 根节点非对象")
            continue
        scripts = data.get("scripts") or {}
        bad = FORBIDDEN_SCRIPTS & set(scripts)
        if bad:
            violations.append(
                f"{manifest}: 禁止的生命周期脚本 {sorted(bad)}（bun install 会执行）")
        if "trustedDependencies" in data:
            violations.append(
                f"{manifest}: 禁止 trustedDependencies（重启用生命周期脚本）")


def check_permission_allowlist(repo: str, violations: list[str]) -> None:
    root = Path(repo)
    settings = [root / ".claude" / "settings.json"]
    settings += list(root.glob(".agents/**/settings*.json"))
    settings = [p for p in settings if p.exists() and "node_modules" not in p.parts]
    if not settings:
        # 当前仓库未接入框架权限配置，前瞻护栏跳过（非臆想约束）
        return
    for path in settings:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            violations.append(f"{path}: 无法读取/非法 JSON: {exc}")
            continue
        if not isinstance(data, dict):
            continue
        allow = (data.get("permissions") or {}).get("allow")
        if not isinstance(allow, list):
            continue
        for entry in allow:
            if entry not in ALLOWED_PERMISSIONS:
                violations.append(
                    f"{path}: 权限未落在审查白名单: {entry!r}。"
                    "预审批权限在每个 fork 上免提示执行；若确有必要，须在同 PR 把该条目"
                    "加入 ALLOWED_PERMISSIONS。")


def check(repo: str) -> list[str]:
    """返回违规项列表（空 = 通过）。"""
    violations: list[str] = []
    check_gitignore(repo, violations)
    check_tracked_secrets(repo, violations)
    check_package_manifests(repo, violations)
    check_permission_allowlist(repo, violations)
    return violations


def main(argv=None) -> int:
    if argv:
        repo = argv[0]
    else:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    violations = check(repo)
    if violations:
        for v in violations:
            print(f"[guard] {v}", file=sys.stderr)
        print(f"[guard] 发现 {len(violations)} 项违规", file=sys.stderr)
        return 1
    print("[guard] OK：未发现敏感文件入库/个人数据泄露/供应链风险")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
