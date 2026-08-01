#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manage_template.py — U6 简历/求职信 LaTeX 模板注册（外观定制，非替人决策）。

用户可把自己喜欢的 LaTeX 简历/求职信模板放进来并命名；注册前先跑一次 lualatex
冒烟编译，编译不过则拒绝注册（避免「用到才发现模板坏了」）。

模板是一份**完整** LaTeX 文档，含以下占位符（编译前被替换）：
  __CV_BODY__   必填，简历/求职信正文落点（drafter_reviewer 的 LaTeX 正文）
  __CV_NAME__   选填，姓名（写入页眉，供 ATS [A2] 字面文本）
  __CV_EMAIL__  选填，邮箱
  __CV_PHONE__  选填，电话

注：模板只决定「你自己的简历长什么样」，工具不替你写内容、不替你决策——
纯粹是产出物的外观定制（产出的本就是你的简历）。模板存于 templates/（已 gitignore，
含个人排版风格，不入库）。

子命令：
  add    --name <slug> --path <template.tex>       注册模板（含冒烟编译）
  list                                              列出已注册模板
  remove --name <slug>                              删除模板
  render --name <slug> --body <body.tex> --out <out.tex>  仅展开占位符到 .tex（不编译）
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import tempfile
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from build_cv import _escape, compile_tex, find_latex_engine  # noqa: E402

# 模板仓库：存放用户自管 LaTeX 模板 + registry.json（均 gitignore）
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
REGISTRY = TEMPLATES_DIR / "registry.json"

# 占位符
REQUIRED_TOKEN = "__CV_BODY__"
OPTIONAL_TOKENS = {
    "name": "__CV_NAME__",
    "email": "__CV_EMAIL__",
    "phone": "__CV_PHONE__",
}
_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ============================================================
# 注册表读写
# ============================================================

def _registry_path() -> Path:
    return TEMPLATES_DIR / "registry.json"


def load_registry() -> dict:
    """返回 {name: {file, registered_at, smoke_ok}}；无文件则空 dict。"""
    p = _registry_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_registry(reg: dict) -> None:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    _registry_path().write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 模板校验 / 展开 / 冒烟编译
# ============================================================

def validate_template(text: str) -> list[str]:
    """返回错误列表（空 = 合法）。校验：完整文档 + 必填正文占位符。"""
    errors: list[str] = []
    if "\\documentclass" not in text or "\\begin{document}" not in text:
        errors.append(
            "模板必须是完整 LaTeX 文档（含 \\documentclass 与 \\begin{document}）")
    if REQUIRED_TOKEN not in text:
        errors.append(f"模板缺少必填占位符 {REQUIRED_TOKEN}（简历正文落点）")
    return errors


def expand_template(text: str, body: str, name: str = "",
                    email: str = "", phone: str = "") -> str:
    """把占位符替换为真实内容（姓名/邮箱/电话做 LaTeX 转义，正文不转义）。"""
    out = text.replace(REQUIRED_TOKEN, body)
    out = out.replace(OPTIONAL_TOKENS["name"], _escape(name))
    out = out.replace(OPTIONAL_TOKENS["email"], _escape(email))
    out = out.replace(OPTIONAL_TOKENS["phone"], _escape(phone))
    return out


def smoke_compile(text: str) -> tuple[bool, str]:
    """用哑正文跑一次 lualatex 冒烟编译；返回 (成功?, 说明)。无引擎则失败。"""
    engine = find_latex_engine()
    if engine is None:
        return False, "未找到 LaTeX 引擎（lualatex/xelatex/pdflatex），无法冒烟编译"
    dummy = expand_template(
        text,
        body="\\section{Experience}\nSmoke-test entry.",
        name="Smoke Test", email="smoke@example.com", phone="13800000000")
    work = tempfile.mkdtemp(prefix="tpl_smoke_")
    tex = Path(work) / "tpl_smoke.tex"
    tex.write_text(dummy, encoding="utf-8")
    try:
        compile_tex(str(tex), engine, out_dir=work)
    except RuntimeError as e:
        return False, f"冒烟编译失败：{e}"
    return True, "冒烟编译通过"


def load_registered_template(name: str) -> str:
    """读取已注册模板正文；未注册/文件缺失抛 ValueError。"""
    reg = load_registry()
    if name not in reg:
        raise ValueError(f"模板未注册：{name}（可用 `list` 查看已注册模板）")
    f = TEMPLATES_DIR / reg[name]["file"]
    if not f.exists():
        raise ValueError(f"模板文件缺失：{f}（请重新 add）")
    return f.read_text(encoding="utf-8")


# ============================================================
# 子命令实现
# ============================================================

def add_template(name: str, src_path: str) -> dict:
    """注册模板。返回 {ok, message, errors}。

    - 名字必须是 [A-Za-z0-9_-]+ slug。
    - 校验完整文档 + 必填占位符。
    - 冒烟编译不过则拒绝注册。
    """
    if not _SLUG_RE.match(name):
        return {"ok": False, "message": "模板名须为 [A-Za-z0-9_-]+",
                "errors": ["invalid_name"]}
    src = Path(src_path)
    if not src.exists():
        return {"ok": False, "message": f"源文件不存在：{src_path}",
                "errors": ["missing_file"]}

    text = src.read_text(encoding="utf-8")
    errors = validate_template(text)
    if errors:
        return {"ok": False, "message": "；".join(errors),
                "errors": errors}

    ok, msg = smoke_compile(text)
    if not ok:
        return {"ok": False, "message": msg, "errors": ["smoke_failed"]}

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    dest = TEMPLATES_DIR / f"{name}.tex"
    dest.write_text(text, encoding="utf-8")
    reg = load_registry()
    reg[name] = {
        "file": dest.name,
        "registered_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "smoke_ok": True,
    }
    save_registry(reg)
    return {"ok": True, "message": f"模板已注册：{dest}", "errors": []}


def remove_template(name: str) -> bool:
    reg = load_registry()
    if name not in reg:
        return False
    f = TEMPLATES_DIR / reg[name]["file"]
    if f.exists():
        f.unlink()
    del reg[name]
    save_registry(reg)
    return True


def list_templates() -> list[dict]:
    reg = load_registry()
    return [{"name": k, **v} for k, v in reg.items()]


def render_template(name: str, body: str, out_path: str,
                    name_field: str = "", email: str = "", phone: str = "") -> str:
    """展开已注册模板 + 正文到 .tex（不编译），返回输出路径。"""
    text = load_registered_template(name)
    rendered = expand_template(text, body, name=name_field,
                               email=email, phone=phone)
    out = Path(out_path)
    out.write_text(rendered, encoding="utf-8")
    return str(out)


# ============================================================
# CLI
# ============================================================

def main():
    p = argparse.ArgumentParser(description="U6 LaTeX 简历模板注册（外观定制）")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="注册模板（含冒烟编译）")
    p_add.add_argument("--name", required=True, help="模板名 [A-Za-z0-9_-]+")
    p_add.add_argument("--path", required=True, help="模板 .tex 源路径")

    sub.add_parser("list", help="列出已注册模板")

    p_rm = sub.add_parser("remove", help="删除模板")
    p_rm.add_argument("--name", required=True)

    p_render = sub.add_parser("render", help="展开模板+正文到 .tex（不编译）")
    p_render.add_argument("--name", required=True)
    p_render.add_argument("--body", required=True, help="正文 .tex 路径")
    p_render.add_argument("--out", required=True, help="输出 .tex 路径")
    p_render.add_argument("--cvname", default="", help="姓名（替换 __CV_NAME__）")
    p_render.add_argument("--email", default="", help="邮箱（替换 __CV_EMAIL__）")
    p_render.add_argument("--phone", default="", help="电话（替换 __CV_PHONE__）")

    args = p.parse_args()

    if args.cmd == "add":
        res = add_template(args.name, args.path)
        print(("✅ " if res["ok"] else "❌ ") + res["message"])
        sys.exit(0 if res["ok"] else 2)

    if args.cmd == "list":
        items = list_templates()
        if not items:
            print("（无已注册模板）")
            sys.exit(0)
        for it in items:
            print(f"- {it['name']}  [{it['file']}]  smoke_ok={it['smoke_ok']}  "
                  f"注册于 {it['registered_at']}")
        sys.exit(0)

    if args.cmd == "remove":
        if remove_template(args.name):
            print(f"已删除模板：{args.name}")
            sys.exit(0)
        print(f"模板不存在：{args.name}", file=sys.stderr)
        sys.exit(1)

    if args.cmd == "render":
        try:
            out = render_template(args.name, Path(args.body).read_text(encoding="utf-8"),
                                  args.out, name_field=args.cvname,
                                  email=args.email, phone=args.phone)
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(1)
        print(f"已展开：{out}")
        sys.exit(0)


if __name__ == "__main__":
    main()
