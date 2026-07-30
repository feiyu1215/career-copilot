"""job_common.py 离线单测（纯 stdlib，不依赖真实抓取 / scipy）。

覆盖：
- load_portals / enabled_portals（含默认兜底）
- SeenJobs 持久去重（URL 精确 + 标题归一哈希，跨运行语义）
- detect_mass_posting（同公司刷屏阈值）
- build_referral_links（LinkedIn 链接生成）
- save_jobs_format / load_jobs_format（v1 存读往返）
"""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "job_common.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("job_common", SCRIPT)
jc = importlib.util.module_from_spec(spec)
sys.modules["job_common"] = jc
spec.loader.exec_module(jc)


# --- 门户注册表 ----------------------------------------------------------
def test_load_portals_default_when_missing(tmp_path):
    data = jc.load_portals(tmp_path / "nope.yaml")
    assert "portals" in data
    assert jc.enabled_portals(data)  # 内嵌默认至少 boss/catdesk/linkedin


def test_enabled_portals_respects_flag(tmp_path):
    cfg = {"portals": {
        "a": {"enabled": True}, "b": {"enabled": False}, "c": {"enabled": True}}}
    assert jc.enabled_portals(cfg) == ["a", "c"]


# --- 持久去重（复合身份键）---------------------------------------------
def test_seen_jobs_url_and_title_dedup(tmp_path):
    p = tmp_path / "seen_jobs.json"
    s = jc.SeenJobs.load(p)
    assert not s.seen(url="u1")
    s.add(url="u1", title="推荐算法工程师", company="某厂", source="boss")
    assert s.seen(url="u1")
    # 同公司同岗不同地点重发：同一复合键，应去重
    assert s.seen(title="推荐算法工程师", company="某厂", source="boss")
    s.save()
    # 跨运行：重新 load 应记得（稳定路径，文件不丢）
    s2 = jc.SeenJobs.load(p)
    assert s2.seen(url="u1")
    assert s2.seen(title="推荐算法工程师", company="某厂", source="boss")


def test_seen_jobs_distinct_titles_not_collapsed(tmp_path):
    s = jc.SeenJobs.load(tmp_path / "seen.json")
    s.add(title="后端开发")
    assert not s.seen(title="前端开发")


def test_seen_jobs_different_company_same_title_not_merged(tmp_path):
    """用户核心诉求：不同公司即使岗位名完全相同，也必须保留为两条，不能错误合并。"""
    s = jc.SeenJobs.load(tmp_path / "seen.json")
    s.add(title="后端开发工程师", company="腾讯", source="boss")
    # 字节的同名岗位：应为「未见」，保留
    assert not s.seen(title="后端开发工程师", company="字节", source="boss")
    # 同公司同岗：才去重
    assert s.seen(title="后端开发工程师", company="腾讯", source="boss")
    # 同公司但不同地点（如北京 vs 上海）视作不同投递，保留
    s.add(title="后端开发工程师", company="腾讯", source="boss", location="北京")
    assert not s.seen(title="后端开发工程师", company="腾讯", source="boss", location="上海")


def test_seen_jobs_persist_across_runs_on_stable_path(tmp_path):
    """「跨运行持久去重」必须真的跨 run 生效：用同一个稳定路径两次 load/save。"""
    p = tmp_path / "data" / "seen_jobs.json"
    s1 = jc.SeenJobs.load(p)
    s1.add(url="https://boss/zhipin/123", title="算法工程师", company="美团", source="boss")
    s1.save()
    # 模拟「下一次运行」：全新对象，从同一稳定路径加载
    s2 = jc.SeenJobs.load(p)
    assert s2.seen(url="https://boss/zhipin/123")
    assert s2.seen(title="算法工程师", company="美团", source="boss")
    # 而不同公司的同名岗位仍应被当作新岗位
    assert not s2.seen(title="算法工程师", company="阿里", source="boss")


# --- mass-posting --------------------------------------------------------
def test_detect_mass_posting_flags_spammy_company():
    recs = [{"company": "刷屏厂", "title": f"岗{i}"} for i in range(6)]
    recs += [{"company": "正常厂", "title": "唯一岗"}]
    flagged = jc.detect_mass_posting(recs, threshold=5)
    assert len(flagged) == 1
    assert flagged[0]["key"] == "刷屏厂"
    assert flagged[0]["count"] == 6


def test_detect_mass_posting_below_threshold():
    recs = [{"company": "x", "title": f"岗{i}"} for i in range(3)]
    assert jc.detect_mass_posting(recs, threshold=5) == []


# --- 内推链接 ------------------------------------------------------------
def test_build_referral_links():
    links = jc.build_referral_links("字节跳动", "算法")
    assert links["people_search"].startswith(
        "https://www.linkedin.com/search/results/people/?keywords=")
    assert links["jobs_search"].startswith(
        "https://www.linkedin.com/search/results/content/?keywords=")
    # 公司/岗位应出现在查询参数中（经 URL 编码，故允许 % 形式）
    assert "字节" in links["people_search"] or "%" in links["people_search"]


def test_build_linkedin_websearch_queries_intern():
    qs = jc.build_linkedin_websearch_queries("算法", "上海", "intern")
    assert any("site:linkedin.com/jobs" in q and "实习" in q for q in qs)


# --- v1 存读往返 ---------------------------------------------------------
def test_save_load_jobs_format_roundtrip(tmp_path):
    blocks = [
        "[URL]https://x.com/j1[/URL]\n算法工程师\n字节\n20K",
        "[URL]https://x.com/j2[/URL]\n后端工程师\n美团",
    ]
    out = tmp_path / "jobs_raw.txt"
    n = jc.save_jobs_format(blocks, out, "2026-07-26T00:00:00")
    assert n == 2
    back = jc.load_jobs_format(out)
    assert len(back) == 2
    assert "算法工程师" in back[0]
    assert "美团" in back[1]


def test_load_jobs_format_missing_file(tmp_path):
    assert jc.load_jobs_format(tmp_path / "missing.txt") == []


# --- Phase 4.1：抓取健康度 / BOSS 专项风控 --------------------------------

def test_health_check_boss_bot_blocked():
    hc = jc.health_check(0, 0, 0, portal="boss", bot_blocked=True)
    assert hc["silent_rot"] is True
    assert any(("风控" in w) or ("限流" in w) for w in hc["warnings"])


def test_health_check_boss_ok_no_extra_warning():
    hc = jc.health_check(12, 0, 0, portal="boss", bot_blocked=False)
    assert hc["ok"] is True
    assert hc["warnings"] == []


def test_health_check_non_boss_ignores_bot_blocked():
    # 仅 boss 门户接入专项风控；其它门户即便 bot_blocked 也不加专项告警
    hc = jc.health_check(5, 0, 0, portal="linkedin", bot_blocked=True)
    assert hc["ok"] is True
    assert hc["warnings"] == []


def test_scrape_health_triggers_after_threshold(tmp_path):
    p = tmp_path / "scrape_health.json"
    sh = jc.ScrapeHealth.load(p, threshold=3)
    assert sh.record("boss", 0)["suspected_blocked"] is False
    assert sh.record("boss", 0)["suspected_blocked"] is False
    r3 = sh.record("boss", 0)
    assert r3["suspected_blocked"] is True
    assert r3["consecutive_empty"] == 3
    # 持久化后跨运行仍记得连续计数
    sh.save()
    sh2 = jc.ScrapeHealth.load(p, threshold=3)
    r4 = sh2.record("boss", 5)  # 成功抓取 → 连续计数重置
    assert r4["consecutive_empty"] == 0
    assert r4["suspected_blocked"] is False


def test_scrape_health_success_resets(tmp_path):
    p = tmp_path / "scrape_health.json"
    sh = jc.ScrapeHealth.load(p, threshold=2)
    sh.record("boss", 0)
    r = sh.record("boss", 10)
    assert r["consecutive_empty"] == 0
    assert r["suspected_blocked"] is False


# --- Phase 4.2：轻量 HTML 树解析（供 shixiseng/nowcoder）-------------------
def test_parse_html_tree_basic():
    root = jc.parse_html_tree("<div class='a'><span class='b'>hi</span></div>")
    spans = jc.html_find_by_class(root, "b")
    assert len(spans) == 1
    assert spans[0].full_text() == "hi"


def test_html_find_anchors():
    root = jc.parse_html_tree("<a href='/x/1'>A</a><a href='/y/2'>B</a>")
    anchors = jc.html_find_anchors(root, "/x/")
    assert len(anchors) == 1
    assert anchors[0].full_text() == "A"


def test_html_text_by_class_nearest():
    html = "<div class='card'><a class='title' href='/j/1'>工程师</a>" \
           "<span class='company-name'>腾讯</span></div>"
    root = jc.parse_html_tree(html)
    card = jc.html_find_by_class(root, "card")[0]
    assert jc.html_text_by_class(card, "company") == "腾讯"
    assert jc.html_first_anchor(card, "/j/").full_text() == "工程师"


def test_html_tree_tolerates_unclosed_tags():
    # 容忍未闭合/错序标签，不抛异常
    root = jc.parse_html_tree("<div class='x'><a href='/p/1'>T")
    a = jc.html_find_anchors(root, "/p/")
    assert len(a) == 1 and a[0].full_text() == "T"


# --- Phase 4.2：默认门户含 shixiseng(启用) 与 nowcoder(关闭) ----------------
def test_default_portals_includes_shixiseng_and_nowcoder():
    data = jc.load_portals(Path("/nonexistent-portals.yaml"))  # 触发内嵌默认
    portals = data["portals"]
    assert "shixiseng" in portals and portals["shixiseng"]["enabled"] is True
    assert "nowcoder" in portals and portals["nowcoder"]["enabled"] is False
    assert portals["nowcoder"]["kind"] == "nowcoder"


# --- Phase 4.3：抓取结果质量守门（逐条准入校验）---------------------------

def _good(title, company, url, **kw):
    return {"title": title, "company": company, "url": url, **kw}


def test_quality_gate_accepts_valid_record():
    rec = _good("后端工程师", "美团", "https://zhipin.com/job/123")
    g = jc.quality_gate([rec])
    assert g["stats"]["accepted"] == 1
    assert g["stats"]["rejected"] == 0
    assert g["accepted"] == [rec]


def test_quality_gate_rejects_missing_title():
    rec = _good("", "美团", "https://x.com/j/1")
    g = jc.quality_gate([rec])
    assert g["stats"]["rejected"] == 1
    assert g["stats"]["by_code"].get("QG1") == 1


def test_quality_gate_rejects_missing_company_by_default():
    rec = _good("后端工程师", "", "https://x.com/j/1")
    g = jc.quality_gate([rec])
    assert g["stats"]["by_code"].get("QG2") == 1


def test_quality_gate_allows_missing_company_when_relaxed():
    rec = _good("后端工程师", "", "https://x.com/j/1")
    g = jc.quality_gate([rec], require_company=False)
    assert g["stats"]["accepted"] == 1
    assert "QG2" not in g["stats"]["by_code"]


def test_quality_gate_rejects_placeholder_title():
    rec = _good("职位", "美团", "https://x.com/j/1")
    g = jc.quality_gate([rec])
    assert g["stats"]["by_code"].get("QG5") == 1


def test_quality_gate_rejects_invalid_url():
    rec = _good("后端工程师", "美团", "www.example.com")
    g = jc.quality_gate([rec])
    assert g["stats"]["by_code"].get("QG4") == 1


def test_quality_gate_rejects_url_with_whitespace():
    rec = _good("后端工程师", "美团", "https://x.com/j/1 你好")
    g = jc.quality_gate([rec])
    assert g["stats"]["by_code"].get("QG4") == 1


def test_quality_gate_rejects_no_identity():
    rec = _good("", "", "")  # 既无标题也无公司也无 URL
    g = jc.quality_gate([rec], require_company=False)
    assert g["stats"]["by_code"].get("QG3") == 1


def test_quality_gate_drops_intra_batch_duplicates():
    rec = _good("后端工程师", "美团", "https://x.com/j/1")
    g = jc.quality_gate([rec, dict(rec), _good("算法工程师", "阿里", "https://x.com/j/2")])
    assert g["stats"]["accepted"] == 2
    assert g["stats"]["duplicate_rejected"] == 1
    assert g["stats"]["by_code"].get("QG6") == 1


def test_quality_gate_duplicate_detection_can_be_disabled():
    rec = _good("后端工程师", "美团", "https://x.com/j/1")
    g = jc.quality_gate([rec, dict(rec)], drop_duplicates=False)
    assert g["stats"]["accepted"] == 2


def test_quality_gate_soft_warnings_do_not_reject():
    rec = _good("后端工程师", "美团", "https://x.com/j/1")  # 缺薪资/地点/JD
    g = jc.quality_gate([rec])
    assert g["stats"]["accepted"] == 1
    assert g["stats"]["warnings"].get("W-Q1") == 1
    assert g["stats"]["warnings"].get("W-Q2") == 1
    assert g["stats"]["warnings"].get("W-Q3") == 1


def test_quality_gate_non_dict_record_rejected():
    g = jc.quality_gate(["不是字典"])
    assert g["stats"]["rejected"] == 1


def test_quality_gate_accept_rate_and_stats():
    recs = [
        _good("后端工程师", "美团", "https://x.com/j/1"),
        _good("", "腾讯", "https://x.com/j/2"),  # QG1 拦截
        _good("算法工程师", "阿里", "https://x.com/j/3"),
    ]
    g = jc.quality_gate(recs)
    assert g["stats"]["total"] == 3
    assert g["stats"]["accepted"] == 2
    assert g["stats"]["rejected"] == 1
    assert abs(g["stats"]["accept_rate"] - 2 / 3) < 1e-9

