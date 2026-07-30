"""verify_fetch_quality.py（Phase 4.3 门禁 CLI）的阈值告警测试。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import verify_fetch_quality as vq


def _write(path, records):
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def _good():
    return [
        {"title": "后端工程师", "company": "美团", "url": "https://zhipin.com/job/1"},
        {"title": "算法工程师", "company": "阿里", "url": "https://job.x.com/2"},
    ]


def _bad():
    return [
        {"title": "", "company": "美团", "url": "https://x.com/1"},       # QG1
        {"title": "职位", "company": "腾讯", "url": "www.example.com"},   # QG5 + QG4
    ]


def _noisy():  # 全缺薪资/地点/JD → warning_rate=1.0
    return [{"title": "后端工程师", "company": "美团", "url": "https://x.com/1"}]


def test_good_exits_0(tmp_path):
    f = tmp_path / "good.json"
    _write(f, _good())
    assert vq.main(["--input", str(f)]) == 0


def test_bad_exits_1(tmp_path):
    f = tmp_path / "bad.json"
    _write(f, _bad())
    assert vq.main(["--input", str(f)]) == 1


def test_allow_missing_company(tmp_path):
    f = tmp_path / "m.json"
    _write(f, [{"title": "后端工程师", "url": "https://x.com/1"}])
    assert vq.main(["--input", str(f), "--allow-missing-company"]) == 0


def test_warning_threshold_non_fatal(tmp_path):
    f = tmp_path / "n.json"
    _write(f, _noisy())
    assert vq.main(["--input", str(f), "--max-warning-rate", "0.5"]) == 0


def test_warning_threshold_fatal(tmp_path):
    f = tmp_path / "n.json"
    _write(f, _noisy())
    assert vq.main(["--input", str(f), "--max-warning-rate", "0.5",
                    "--warnings-fatal"]) == 1


def test_unreadable_input_exits_2(tmp_path):
    f = tmp_path / "missing.json"
    assert vq.main(["--input", str(f)]) == 2
