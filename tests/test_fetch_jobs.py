"""m8 回归测试：fetch_jobs.fetch_all_jobs 不应把「正常空尾页」误计为失败页。

此前成功提取但为空的尾页（分页终止信号）会被计入 failed_pages；
只有导航失败 / 提取失败才应计入。通过捕获 stdout 中的「失败页面」行验证。
"""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_jobs.py"
spec = importlib.util.spec_from_file_location("fetch_jobs_test", SCRIPT)
fj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fj)


def test_empty_tail_pages_not_counted_as_failed(tmp_path, capsys):
    fj.time.sleep = lambda *a, **k: None
    fj.navigate_to_page = lambda url: True
    seq = [("JOB one text", True), ([], True), ([], True)]  # p1 有岗, p2/p3 空 → 终止
    it = iter(seq)
    fj.extract_jobs_from_page = lambda sel: next(it)
    out = tmp_path / "jobs.txt"
    total = fj.fetch_all_jobs("http://x?p={page}", total_pages=10, output_file=str(out), delay=0)
    captured = capsys.readouterr().out
    assert total >= 1
    # 空尾页是正常分页终止，不应出现在失败页面列表
    assert "失败页面" not in captured, captured


def test_nav_failure_counted(tmp_path, capsys):
    fj.time.sleep = lambda *a, **k: None
    fj.navigate_to_page = lambda url: False  # 始终导航失败
    fj.extract_jobs_from_page = lambda sel: ([], True)
    out = tmp_path / "jobs.txt"
    fj.fetch_all_jobs("http://x?p={page}", total_pages=10, output_file=str(out), delay=0)
    captured = capsys.readouterr().out
    # 连续 5 次导航失败 → 停止，5 个失败页应被记录（与空尾页区分）
    assert "失败页面（5 页）" in captured, captured
    assert out.exists()
