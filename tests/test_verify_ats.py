"""verify_ats.py 合同化回归测试（用最小合法 PDF 合成样本自测，离线可跑）。

覆盖：
- 合法 2 页 CV（含邮箱/电话/关键词）：通过
- 3 页：触发 [A1]
- 缺联系方式：触发 [A2]
- 含 (cid 乱码：触发 [A3]
- JD 关键词缺失：仅 [W-A] 警告，不硬失败
- 关键词全命中：覆盖摘要 [W-A]，无未命中列表
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_ats.py"
spec = importlib.util.spec_from_file_location("verify_ats", SCRIPT)
va = importlib.util.module_from_spec(spec)
spec.loader.exec_module(va)


def _pdf_bytes(page_texts):
    """构造最小合法 PDF（pypdf 可读），每页一段 ASCII 文本。"""
    objs = {}
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    next_num = 4
    kids = []
    for text in page_texts:
        esc = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({esc}) Tj ET".encode("latin-1")
        cnum = next_num
        next_num += 1
        pnum = next_num
        next_num += 1
        objs[cnum] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
        objs[pnum] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(cnum).encode() + b" 0 R >>"
        )
        kids.append(pnum)
    objs[2] = (
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{k} 0 R".encode() for k in kids)
        + b"] /Count " + str(len(kids)).encode() + b" >>"
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    max_num = max(objs)
    out += f"xref\n0 {max_num + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for num in range(1, max_num + 1):
        if num in offsets:
            out += f"{offsets[num]:010d} 00000 n \n".encode()
        else:
            out += b"0000000000 65535 f \n"
    out += (
        f"trailer\n<< /Size {max_num + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


@pytest.fixture
def good_pdf(tmp_path):
    p = tmp_path / "good.pdf"
    p.write_bytes(_pdf_bytes([
        "Alice Wang\nalice.wang@example.com\n13800138000\nPython distributed risk control system design",
        "Second page\nMore experience with Python and risk control",
    ]))
    return str(p)


def test_valid_passes(good_pdf):
    failures, warnings = va.run_checks(good_pdf)
    assert failures == [], failures


def test_page_count_failure(tmp_path):
    p = tmp_path / "three.pdf"
    p.write_bytes(_pdf_bytes([
        "page1 alice@example.com 13800138000",
        "page2 content",
        "page3 content",
    ]))
    failures, _ = va.run_checks(str(p))
    assert any("[A1]" in f for f in failures), failures


def test_missing_contact_failure(tmp_path):
    p = tmp_path / "nocon.pdf"
    p.write_bytes(_pdf_bytes([
        "No contact info here just Python experience and risk control",
        "page2 content",
    ]))
    failures, _ = va.run_checks(str(p))
    assert any("[A2]" in f for f in failures), failures


def test_garbled_failure(tmp_path):
    p = tmp_path / "garbled.pdf"
    p.write_bytes(_pdf_bytes([
        "alice@example.com 13800138000 (cid:12) garbled text here",
        "page2 content",
    ]))
    failures, _ = va.run_checks(str(p))
    assert any("[A3]" in f for f in failures), failures


def test_keyword_missing_warns_not_fails(good_pdf):
    failures, warnings = va.run_checks(good_pdf, jd_keywords=["Python", "Go", "Kubernetes"])
    assert failures == [], failures
    assert any("[W-A]" in w and "Go" in w for w in warnings), warnings


def test_keyword_full_coverage_summary(good_pdf):
    failures, warnings = va.run_checks(good_pdf, jd_keywords=["Python", "risk"])
    assert failures == [], failures
    assert any("命中 2/2" in w for w in warnings), warnings
