#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cv.py — 把 drafter_reviewer 产出的 LaTeX 草稿编译为可投递 PDF，并跑 ATS 校验闭环。

本文件落地升级建议 U1（补齐「编译 → verify_ats」最后一公里）。
事实依据：drafter_reviewer.py 的 draft/revise 子命令只写出 draft.tex（LaTeX 正文
文本），scripts/ 内从未调用 lualatex/xelatex/pdflatex，verify_ats.py 也只对已有 PDF
抽文本层校验 —— 链路在「编译」一环断开，用户拿到的是 .tex 而非可投递材料。

流程：
  1. 读取 draft.tex（drafter_reviewer 产物；可能是正文，也可能是已完整的 LaTeX 文档）。
  2. 若非完整文档，用最小 article 模板包裹（含姓名/联系方式页眉，供 ATS [A2] 字面文本）。
  3. 定位 LaTeX 引擎（lualatex > xelatex > pdflatex）；缺失则明确报错，不静默降级。
  4. 编译为 PDF（两次以确保交叉引用/页眉稳定）。
  5. 调用 verify_ats.run_checks 做 ATS 文本层 + 硬不变量校验。
  6. 输出 PDF 路径 + (failures, warnings)；存在 [A#] 硬失败则非零退出。

退出码：
  0 = 编译成功且 ATS 通过（含仅 [W] 警告）
  1 = ATS 硬失败
  2 = 缺少 LaTeX 引擎 / 编译失败（明确暴露，不静默降级）
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from verify_ats import run_checks  # noqa: E402
from visual_inspect import protect_headings, inspect_pdf  # noqa: E402

ENGINE_CANDIDATES = ("lualatex", "xelatex", "pdflatex")

# [7.1-c] 演示 / 截图 / eval 用虚拟联系方式：生成产物不含真实 PII。
# 虚拟邮箱 / 电话满足 ATS [A2]「联系方式字面文本」约束，故 redact-demo 模式
# 产出的 PDF 仍能通过 ATS 校验（仅联系方式为占位，便于公开分享 / 测试）。
REDACT_DEMO_NAME = "示例用户 (Demo User)"
REDACT_DEMO_EMAIL = "demo@example.com"
REDACT_DEMO_PHONE = "138-0000-0000"

# 仅用于 redact-demo 模式下的正文掩码（保守：邮箱 / 中国大陆手机 / 国际手机）。
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CN_MOBILE = re.compile(r"1[3-9]\d{9}")
# 国际/座机风格：3~15 位数字，可含 + / 空格 / 连字符，且前后非数字（避免误伤年份）
_INT_PHONE = re.compile(r"(?<![\d+])(?:\+?\d[\d\s-]{5,15}\d)(?![\d-])")


def _redact_demo_text(text: str) -> str:
    """把正文中的真实邮箱 / 电话替换为虚拟占位（仅 redact-demo 模式调用）。"""
    text = _RE_EMAIL.sub(REDACT_DEMO_EMAIL, text)
    text = _CN_MOBILE.sub(REDACT_DEMO_PHONE, text)
    text = _INT_PHONE.sub(REDACT_DEMO_PHONE, text)
    return text


def _resolve_constraints(constraints, template):
    """返回传给 run_checks 的约束字典。

    若指定已注册模板且 config/constraints.yaml 的 ats.templates[模板] 含覆盖项
    （如 page_count），则合并覆盖（仅本次 build 生效，不污染全局单一事实源）。
    例如 cn-compact 期望 1 页，而全局 ats.page_count=2，不覆盖会误报 [A1]。
    """
    if not template:
        return constraints
    try:
        from config_loader import load_constraints
    except Exception:
        return constraints
    base = dict(load_constraints() if constraints is None else constraints)
    override = (base.get("ats", {}) or {}).get("templates", {}) or {}
    tpl = override.get(template)
    if isinstance(tpl, dict):
        merged = dict(base.get("ats", {}) or {})
        merged.update(tpl)
        base["ats"] = merged
    return base


def find_latex_engine() -> str | None:
    """返回首个可用的 LaTeX 引擎；都没有则返回 None（调用方必须显式报错，不可静默降级）。"""
    for engine in ENGINE_CANDIDATES:
        if shutil.which(engine):
            return engine
    return None


def _is_full_document(body: str) -> bool:
    return "\\begin{document}" in body and "\\documentclass" in body


def _escape(s: str) -> str:
    for ch in ("&", "%", "#", "_", "{", "}"):
        s = s.replace(ch, "\\" + ch)
    return s


def wrap_into_document(body: str, name: str = "", email: str = "",
                       phone: str = "") -> str:
    """把 LaTeX 正文包成可编译文档。若已是完整文档（含 documentclass+document 环境）则原样返回。"""
    if _is_full_document(body):
        return body
    contact = ""
    parts = []
    if email:
        parts.append(_escape(email))
    if phone:
        parts.append(_escape(phone))
    if parts:
        contact = "\n\\centerline{" + " $\\bullet$ ".join(parts) + "}\n"
    header = f"\\centerline{{\\Large\\bfseries {_escape(name)}}}\\par\n" if name else ""
    return (
        "\\documentclass[11pt,a4paper]{article}\n"
        "\\usepackage[utf8]{inputenc}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage{hyperref}\n"
        "\\pagestyle{empty}\n"
        "\\begin{document}\n"
        f"{header}{contact}\n"
        f"{body}\n"
        "\\end{document}\n"
    )


def compile_tex(tex_path: str, engine: str, out_dir: str | None = None) -> str:
    """编译 .tex 为 PDF（两次以稳定交叉引用/页眉）。返回 PDF 路径。"""
    out_dir = out_dir or str(Path(tex_path).parent)
    for _ in range(2):
        proc = subprocess.run(
            [engine, "-interaction=nonstopmode", "-halt-on-error",
             "-output-directory", out_dir, tex_path],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"LaTeX 编译失败（{engine}）：\n"
                f"{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
            )
    pdf = Path(out_dir) / (Path(tex_path).stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(f"编译未产出 PDF：{pdf}")
    return str(pdf)


def _as_docx(path):
    """把任意输出路径规范化为 .docx 路径。"""
    p = str(path)
    if p.lower().endswith(".docx"):
        return p
    if p.lower().endswith(".pdf"):
        return p[:-4] + ".docx"
    return p + ".docx"


def build(draft_tex: str, out_pdf: str | None = None,
          keywords: list[str] | None = None, name: str = "",
          email: str = "", phone: str = "",
          constraints: dict | None = None,
          template: str | None = None,
          protect: bool = True,
          inspect: bool = True,
          fallback: str = "none",
          redact_demo: bool = False) -> dict:
    """编排：包裹 → 定位引擎 → 编译 → ATS 校验 → 视觉巡检。

    返回 {pdf, engine, failures, warnings, visual_issues}。

    constraints 可覆盖 config/constraints.yaml 的 ats 段（如真实 1 页 CV 临时放宽
    page_count）；默认 None 使用仓库单一事实源。
    template 为已注册模板名（U6）；指定则用该模板展开正文。
    protect：编译前给标题插 needspace 防孤行（源码级，确定性，不改内容）。
    inspect：编译后用 PyMuPDF 做坐标级视觉巡检（孤行/溢出/空白），仅作 warning
        暴露，绝不替人改内容（不越界替人决策）。PyMuPDF 不可用时退化为提示。
    """
    draft_path = Path(draft_tex)
    if not draft_path.exists():
        raise FileNotFoundError(f"草稿不存在: {draft_tex}")

    if redact_demo:
        # [7.1-c] 演示 / 截图 / eval 模式：用虚拟联系方式替换真实 PII（正文掩码见下）
        name, email, phone = REDACT_DEMO_NAME, REDACT_DEMO_EMAIL, REDACT_DEMO_PHONE

    # 非 LaTeX 降级路径：docx（无引擎也能产出可投递材料）
    want_docx = (fallback == "docx") or (out_pdf and str(out_pdf).lower().endswith(".docx"))
    if want_docx:
        from build_cv_docx import build_docx, _tex_to_structured
        out_docx = _as_docx(out_pdf or "cv.docx")
        check_constraints = _resolve_constraints(constraints, template)
        if draft_path.suffix.lower() == ".json":
            build_docx(str(draft_path), out_docx, name=name, email=email,
                       phone=phone, constraints=check_constraints, inspect=False)
        else:
            tex = draft_path.read_text(encoding="utf-8")
            if redact_demo:
                tex = _redact_demo_text(tex)
            build_docx(_tex_to_structured(tex), out_docx, name=name, email=email,
                       phone=phone, constraints=check_constraints, inspect=False)
        # 复用与 LaTeX 路径相同的 ATS 文本层检查（docx 跳过 [A1] 页数）
        failures, warnings = run_checks(out_docx, keywords, constraints=check_constraints)
        return {"pdf": out_docx, "engine": "docx-fallback",
                "failures": failures, "warnings": warnings, "visual_issues": []}

    body = draft_path.read_text(encoding="utf-8")
    if redact_demo:
        body = _redact_demo_text(body)
    if template:
        # 懒导入避免循环：manage_template 在模块顶部 import 本模块
        from manage_template import expand_template, load_registered_template
        tpl = load_registered_template(template)
        wrapped = expand_template(tpl, body, name=name, email=email, phone=phone)
    else:
        wrapped = wrap_into_document(body, name=name, email=email, phone=phone)

    # 源码级防孤行（确定性排版保护，不改内容）
    if protect:
        wrapped = protect_headings(wrapped)

    engine = find_latex_engine()
    if engine is None:
        raise RuntimeError(
            "未找到 LaTeX 引擎（lualatex/xelatex/pdflatex 均不可用）。\n"
            "请先安装 TeX 发行版（TeX Live / MiKTeX）后再运行本脚本。\n"
            "（未静默降级：没有引擎无法产出可投递 PDF。）"
        )

    # 编译全程在 work 临时目录进行；PDF 移出后立即清理，避免真实联系方式残留在
    # .tex/.aux/.log 中间产物中（[7.1-a] PII 保护）。
    work = tempfile.mkdtemp(prefix="build_cv_")
    try:
        wrapped_tex = Path(work) / "cv_wrapped.tex"
        wrapped_tex.write_text(wrapped, encoding="utf-8")

        pdf = compile_tex(str(wrapped_tex), engine, out_dir=work)
        target = out_pdf or str(draft_path.parent / (draft_path.stem + ".pdf"))
        # shutil.move 可跨盘移动（Windows 下 os.replace 跨盘会失败），保证产物落到目标路径
        shutil.move(pdf, target)

        # 模板级约束覆盖：如 cn-compact 期望 1 页，全局 ats.page_count=2，
        # 需按模板名从 config/constraints.yaml 的 ats.templates 取覆盖，否则误报 [A1]。
        check_constraints = _resolve_constraints(constraints, template)

        failures, warnings = run_checks(target, keywords, constraints=check_constraints)

        # 编译后视觉巡检（坐标级；仅 warning 暴露，不替人改内容）
        visual_issues: list[dict] = []
        if inspect:
            vis = inspect_pdf(target, constraints)
            if vis["backend"] == "unavailable":
                warnings.append(
                    f"[V0] 视觉巡检后端不可用：{vis.get('note', '')}"
                )
            else:
                for it in vis["issues"]:
                    warnings.append(f"[{it['type']}] p{it['page']}: {it['detail']}")
                visual_issues = vis["issues"]
            # backend == "error"（PDF 损坏等）不附加 warning，避免误伤正常流程

        # 超页且提供了 JD 关键词 → 提示可用相关性裁剪（不自动裁，留人决策）
        # 注意：[A1] 在「页数≠期望」时触发，仅当页数 > 期望（真正超页）才建议裁切
        import re as _re
        for f in failures:
            if f.startswith("[A1]"):
                m = _re.search(r"页数\s*=\s*(\d+).*?期望\s*(\d+)", f)
                if m and int(m.group(1)) > int(m.group(2)) and keywords:
                    warnings.append(
                        "[V-suggest] 简历超页且提供了 JD 关键词：可运行 "
                        "`python scripts/relevance_trim.py --draft <草稿> "
                        "--keywords <JD关键词>` 按相关性（而非时间）裁掉最不相关条目，"
                        "请人工复核后再编译"
                    )
                break

        return {"pdf": target, "engine": engine,
                "failures": failures, "warnings": warnings,
                "visual_issues": visual_issues}
    finally:
        # [7.1-a] 无论编译 / ATS / 巡检成功与否，都清理含真实 PII 的中间目录
        shutil.rmtree(work, ignore_errors=True)


# 随包 shipping 的求职信模板（用户未注册 cover-letter 时回退使用）
COVER_FALLBACK_TEMPLATE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=1.8cm]{geometry}
\usepackage{xcolor}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.7em}
\begin{document}

{\Large\bfseries __CV_NAME__}\\
\noindent __CV_EMAIL__ ~$\bullet$~ __CV_PHONE__\\[0.6em]
{\color{gray}\today}\par\vspace{0.4em}

__CV_BODY__

\vfill
\end{document}
"""


def _render_cover(body: str, template: str | None, name: str, email: str, phone: str) -> str:
    """求职信正文 → 完整 LaTeX。优先用已注册模板，回退到随包 shipping 模板。"""
    if template:
        try:
            from manage_template import expand_template, load_registered_template
            return expand_template(load_registered_template(template), body,
                                   name=name, email=email, phone=phone)
        except ValueError:
            pass  # 未注册 → 回退
    # 回退 1：仓库内 templates/cover-letter.tex
    shipped = Path(__file__).resolve().parent.parent / "templates" / "cover-letter.tex"
    if shipped.exists():
        from manage_template import expand_template
        return expand_template(shipped.read_text(encoding="utf-8"), body,
                               name=name, email=email, phone=phone)
    # 回退 2：内置常量
    return expand_template(COVER_FALLBACK_TEMPLATE, body, name=name, email=email, phone=phone)


def build_cover(cover_tex: str | Path, out_pdf: str | Path | None = None,
                name: str = "", email: str = "", phone: str = "",
                constraints: dict | None = None,
                template: str = "cover-letter",
                protect: bool = True, inspect: bool = False,
                redact_demo: bool = False) -> dict:
    """编译求职信为 PDF 并跑轻量 ATS 校验。

    返回 {pdf, engine, failures, warnings, visual_issues}。

    与 build() 的差异：
    - 默认用 cover-letter 模板（半页三段式）；
    - 封面 ≤1 页，约束覆盖 page_count=1，避免误报 [A1]；
    - 不跑相关性裁剪建议（求职信不涉及 JD 关键词裁剪）。
    """
    draft_path = Path(cover_tex)
    if not draft_path.exists():
        raise FileNotFoundError(f"求职信草稿不存在: {cover_tex}")
    if redact_demo:
        name, email, phone = REDACT_DEMO_NAME, REDACT_DEMO_EMAIL, REDACT_DEMO_PHONE
    body = draft_path.read_text(encoding="utf-8")
    if redact_demo:
        body = _redact_demo_text(body)
    wrapped = _render_cover(body, template, name, email, phone)
    if protect:
        wrapped = protect_headings(wrapped)

    engine = find_latex_engine()
    if engine is None:
        raise RuntimeError(
            "未找到 LaTeX 引擎（lualatex/xelatex/pdflatex 均不可用）。\n"
            "请先安装 TeX 发行版（TeX Live / MiKTeX）后再运行本脚本。"
        )

    # 编译全程在 work 临时目录进行；PDF 移出后立即清理，避免真实联系方式残留在
    # .tex/.aux/.log 中间产物中（[7.1-a] PII 保护）。
    work = tempfile.mkdtemp(prefix="build_cover_")
    try:
        wrapped_tex = Path(work) / "cover_wrapped.tex"
        wrapped_tex.write_text(wrapped, encoding="utf-8")

        pdf = compile_tex(str(wrapped_tex), engine, out_dir=work)
        target = out_pdf or str(draft_path.parent / (draft_path.stem + ".pdf"))
        shutil.move(pdf, target)

        # 封面 ≤1 页：覆盖 page_count，避免误报 [A1]
        cover_constraints = dict(_resolve_constraints(constraints, template))
        ats = dict(cover_constraints.get("ats", {}) or {})
        ats["page_count"] = 1
        cover_constraints["ats"] = ats

        failures, warnings = run_checks(target, None, constraints=cover_constraints)
        return {"pdf": target, "engine": engine,
                "failures": failures, "warnings": warnings, "visual_issues": []}
    finally:
        # [7.1-a] 无论编译成功与否，都清理含真实 PII 的中间目录
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    p = argparse.ArgumentParser(
        description="编译 LaTeX 简历草稿为 PDF 并跑 ATS 校验闭环")
    p.add_argument("--draft", required=True, help="drafter_reviewer 产出的 .tex 草稿")
    p.add_argument("--out", default=None, help="输出 PDF 路径（默认与草稿同目录同名 .pdf）")
    p.add_argument("--keywords", help="JD 关键词，逗号分隔（可选，用于 ATS 覆盖检查）")
    p.add_argument("--name", default="", help="姓名（写入页眉，供 ATS [A2]）")
    p.add_argument("--email", default="", help="邮箱（写入页眉，供 ATS [A2]）")
    p.add_argument("--phone", default="", help="电话（写入页眉，供 ATS [A2]）")
    p.add_argument("--template", default=None,
                   help="已注册模板名（U6）；指定则用该模板展开正文")
    p.add_argument("--no-protect", dest="protect", action="store_false",
                   help="关闭编译前源码级防孤行（默认开启）")
    p.add_argument("--no-inspect", dest="inspect", action="store_false",
                   help="关闭编译后视觉巡检（默认开启）")
    p.add_argument("--with-cover", default=None,
                   help="求职信草稿 .tex；指定则与 --draft 一并编译（产出 <草稿同名>.cover.pdf）")
    p.add_argument("--fallback", choices=["none", "docx"], default="none",
                   help="LaTeX 引擎缺失时的降级路径（docx：用 python-docx 生成 .docx）")
    p.add_argument("--redact-demo", dest="redact_demo", action="store_true",
                   help="[7.1-c] 演示/截图/eval 模式：用虚拟联系方式替换真实 PII，"
                        "产物不含真实邮箱/电话，便于公开分享与测试")
    args = p.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()] \
        if args.keywords else None
    try:
        res = build(args.draft, out_pdf=args.out, keywords=keywords,
                    name=args.name, email=args.email, phone=args.phone,
                    template=args.template, protect=args.protect,
                    inspect=args.inspect, fallback=args.fallback,
                    redact_demo=args.redact_demo)
    except RuntimeError as e:
        print(f"[build_cv] ❌ {e}", file=sys.stderr)
        sys.exit(2)

    if res["failures"]:
        print(f"[build_cv] ❌ ATS 检查 {len(res['failures'])} 项失败（PDF={res['pdf']}）：")
        for f in res["failures"]:
            print(f"  - {f}")
        for w in res["warnings"]:
            print(f"  ⚠ {w}")
        sys.exit(1)

    print(f"[build_cv] ✅ 编译+ATS 通过：{res['pdf']}（引擎 {res['engine']}）")
    for w in res["warnings"]:
        print(f"  ⚠ {w}")

    # 求职信：与简历一并编译（软附加，封面失败不阻断简历产出）
    if args.with_cover:
        try:
            cres = build_cover(args.with_cover, name=args.name,
                               email=args.email, phone=args.phone,
                               redact_demo=args.redact_demo)
            flag = "✅" if not cres["failures"] else "⚠"
            print(f"[build_cv] {flag} 求职信编译：{cres['pdf']}（引擎 {cres['engine']}）")
            for w in cres["warnings"]:
                print(f"  ⚠ {w}")
            for f in cres["failures"]:
                print(f"  - {f}")
        except Exception as e:  # 封面失败不阻断简历产出
            print(f"[build_cv] ⚠ 求职信编译失败（不影响简历）：{e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
