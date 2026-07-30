#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""visual_inspect.py — 编译后「逐页看 PDF」的确定性视觉巡检 + 源码级防孤行。

背景（诚实定位）：
  编译后会「逐页看 PDF」修孤行（orphan）、按相关性裁页。
  U1 的 build_cv 只做「编译 + ATS 文本校验」，缺像素级巡检。本模块补上，
  且刻意采用**本地确定性**路线，契合本仓 SECURITY.md 的「非沙箱、绝不外发数据」：
  不调用任何视觉 LLM（那会把 PDF 内容发往外部 API），而是用 PyMuPDF 抽
  文本块坐标，本地检测三类版式问题。

两条路径：
  A) 源码级预防 protect_headings()：给 \\section/\\subsection/\\subsubsection
     前插 \\needspace{4\\baselineskip}（LaTeX 标准防孤行惯用法）。零依赖、
     确定性、不改动内容只改排版，且不需要任何渲染库 —— 即使本机没装 PyMuPDF
     也能防孤行。
  B) 编译后坐标巡检 inspect_pdf()：用 PyMuPDF 抽每页文本块坐标，检测
     - orphan-heading：页底孤立标题（标题在页底、正文流到下一页）
     - overflow：文本块超出页边距（右/底溢出）
     - blank-gap：同页两文本块垂直间隙过大（异常空白）
     PyMuPDF 不可用时返回 backend="unavailable"，build 流程据此提示改用 A)。

注意：坐标启发式是「提示」而非「自动修」。build 流程只把它们作为 warning 暴露，
不替人改动内容（不越界替人决策）。如需要对孤行自动修复，用 A) 的预防式插入即可。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_HEADING_RE = re.compile(r"^\s*\\(sub){0,2}section\b")
_NEEDSPACE_PKG = "\\usepackage{needspace}"


def _looks_heading(text: str) -> bool:
    """启发式：短且不像句子结尾（不以句号/冒号等收尾）→ 疑似标题。"""
    t = text.strip()
    if not t or len(t) > 60:
        return False
    if t[-1] in ".。;；:：,，!！?？)）":
        return False
    return True


def protect_headings(tex: str, units: int = 4) -> str:
    """源码级防孤行：给各级 section 标题前插 \\needspace{units\\baselineskip}。

    - 幂等：已含 needspace 调用/宏包则不重复插入。
    - 不改内容，只注入排版保护，确定性、零依赖。
    """
    # 仅当真未声明 \usepackage{needspace} 时才注入；注释里提到 "needspace" 不应阻断
    if "\\usepackage{needspace}" not in tex:
        def _add_pkg(m: re.Match) -> str:
            return m.group(1) + "\n" + _NEEDSPACE_PKG
        # 匹配 \documentclass（可带 [options]{class}）；注意 options 里的 ] 也需容忍
        tex = re.sub(r"(\\documentclass(?:\[[^\]]*\])?\{[^}]*\})", _add_pkg, tex, count=1)
    lines = tex.split("\n")
    out: list[str] = []
    for line in lines:
        if _HEADING_RE.match(line) and "\\needspace" not in line:
            prev = out[-1] if out else ""
            if "\\needspace" not in prev:
                out.append(f"\\needspace{{{units}\\baselineskip}}")
        out.append(line)
    return "\n".join(out)


def inspect_pdf(pdf_path: str, constraints: dict | None = None) -> dict:
    """编译后坐标级视觉巡检。返回 {backend, pages, issues[], note}。

    issues 元素：{type, page, detail}；type ∈ orphan-heading | overflow | blank-gap。
    PyMuPDF 不可用时 backend="unavailable"，issues 为空并附 note。
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return {
            "backend": "unavailable",
            "pages": 0,
            "issues": [],
            "note": ("PyMuPDF 未安装，无法做坐标级视觉巡检；"
                     "已用 protect_headings() 做源码级防孤行（运行 "
                     "`pip install pymupdf` 后可启用像素级巡检）"),
        }

    cfg = (constraints or {}).get("visual", {})
    bottom_ratio = float(cfg.get("orphan_bottom_ratio", 0.85))
    gap_ratio = float(cfg.get("blank_gap_ratio", 0.22))
    margin_tol = float(cfg.get("margin_tolerance_pt", 5.0))

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return {"backend": "error", "pages": 0, "issues": [],
                "note": f"PyMuPDF 无法打开 PDF（文件损坏或非 PDF）：{e}"}
    npages = doc.page_count
    issues: list[dict] = []

    for pi in range(npages):
        page = doc[pi]
        rect = page.rect
        blocks = [b for b in page.get_text("blocks")
                  if isinstance(b, (tuple, list)) and len(b) >= 5 and b[4].strip()]
        # get_text("blocks") 按块号/插入序返回，未必按 y 排序；
        # 孤行/空白间隙检测依赖「从上到下」顺序，这里显式按 (y0, x0) 排序
        blocks.sort(key=lambda b: (b[1], b[0]))
        # 右/底溢出
        for b in blocks:
            x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
            if x1 > rect.width - margin_tol or y1 > rect.height - margin_tol:
                issues.append({
                    "type": "overflow",
                    "page": pi + 1,
                    "detail": (f"文本块超出页边距 x1={x1:.0f} y1={y1:.0f} "
                               f"(页宽{rect.width:.0f} 高{rect.height:.0f}): "
                               f"{txt[:30]!r}"),
                })
        # 孤行标题 / 同页空白间隙
        for i, b in enumerate(blocks):
            x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
            if (i == len(blocks) - 1) and (y1 / rect.height) >= bottom_ratio:
                # 末块且贴近页底；若下一页有正文 → 疑似孤行标题
                if pi + 1 < npages:
                    nblocks = [nb for nb in doc[pi + 1].get_text("blocks")
                               if isinstance(nb, (tuple, list)) and len(nb) >= 5
                               and nb[4].strip()]
                    nblocks.sort(key=lambda b: (b[1], b[0]))
                    if nblocks and _looks_heading(txt):
                        issues.append({
                            "type": "orphan-heading",
                            "page": pi + 1,
                            "detail": (f"疑似孤行标题（页底标题、正文流到下一页）: "
                                       f"{txt[:40]!r}"),
                        })
            if i + 1 < len(blocks):
                gap = blocks[i + 1][1] - y1
                if gap >= gap_ratio * rect.height:
                    issues.append({
                        "type": "blank-gap",
                        "page": pi + 1,
                        "detail": (f"同页文本块间隙过大 ({gap:.0f}pt ≈ "
                                   f"{gap / rect.height:.0%} 页高)，位于 "
                                   f"{txt[:25]!r} 之后"),
                    })
    doc.close()
    return {"backend": "fitz", "pages": npages, "issues": issues}


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="编译后 PDF 视觉巡检 / 源码级防孤行")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inspect", help="坐标级巡检已编译 PDF")
    pi.add_argument("--pdf", required=True, help="PDF 路径")
    pi.add_argument("--constraints", default=None, help="config/constraints.yaml（可选）")

    pp = sub.add_parser("protect", help="源码级给标题插 needspace 防孤行")
    pp.add_argument("--tex", required=True, help=".tex 路径（覆盖写回）")
    pp.add_argument("--units", type=int, default=4, help="needspace 行高倍数")

    args = p.parse_args()

    if args.cmd == "inspect":
        cons = None
        if args.constraints:
            from config_loader import load_constraints
            cons = load_constraints()
        r = inspect_pdf(args.pdf, cons)
        print(f"[visual_inspect] backend={r['backend']} pages={r['pages']}")
        if r.get("note"):
            print(f"  note: {r['note']}")
        if r["issues"]:
            print(f"  发现 {len(r['issues'])} 处版式问题：")
            for it in r["issues"]:
                print(f"    - [{it['type']}] p{it['page']}: {it['detail']}")
        else:
            print("  ✓ 未检测到孤行/溢出/异常空白（坐标启发式）")
    else:
        tex = Path(args.tex).read_text(encoding="utf-8")
        new = protect_headings(tex, units=args.units)
        Path(args.tex).write_text(new, encoding="utf-8")
        print(f"[visual_inspect] ✓ 已为标题插入 needspace 防孤行：{args.tex}")


if __name__ == "__main__":
    main()
