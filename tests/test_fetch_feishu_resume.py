"""T15 验收测试：fetch_jobs_feishu.py 增强（重试 / 断点续传 / UA 配置化）

注：Playwright 浏览器无法在本环境运行，故重试/检查点/续传逻辑通过
注入假的 navigate/fetch 闭包（与 run() 中真实闭包同签名）来单测，
覆盖「模拟中途 Ctrl+C → --resume 从断点继续」的验收场景。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import fetch_jobs_feishu as fj
from fetch_jobs_feishu import (
    FeishuJobCrawler,
    FeishuCheckpoint,
    fetch_with_retry,
    _load_user_agent,
    DEFAULT_USER_AGENT,
)


# ──────────────────────────────────────────────
# 1) 单 JD 重试（指数退避 + jitter）
# ──────────────────────────────────────────────

def test_retry_succeeds_on_third_attempt():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    out = asyncio.run(fetch_with_retry(flaky, retries=3, base_delay=0.001))
    assert out == "ok"
    assert calls["n"] == 3


def test_retry_returns_none_after_exhausting():
    calls = {"n": 0}

    async def always_fail():
        calls["n"] += 1
        raise RuntimeError("boom")

    out = asyncio.run(fetch_with_retry(always_fail, retries=3, base_delay=0.001))
    assert out is None
    assert calls["n"] == 3


# ──────────────────────────────────────────────
# 2) 检查点 round-trip
# ──────────────────────────────────────────────

def test_checkpoint_round_trip(tmp_path):
    cp_path = str(tmp_path / "ckpt.json")
    items = [{"id": "1", "title": "a"}, {"id": "2", "title": "b"}]
    cp = FeishuCheckpoint(page_no=3, job_items=items, fetched_detail_ids=["1"])
    FeishuCheckpoint.save(cp_path, cp)
    assert FeishuCheckpoint.exists(cp_path)
    loaded = FeishuCheckpoint.load(cp_path)
    assert loaded.page_no == 3
    assert loaded.job_items == items
    assert loaded.fetched_detail_ids == ["1"]


# ──────────────────────────────────────────────
# 3) User-Agent 从 config/pipeline.yaml 读取
# ──────────────────────────────────────────────

def test_user_agent_top_level(tmp_path):
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text("user_agent: CustomUA/1.0\n", encoding="utf-8")
    assert _load_user_agent(str(cfg)) == "CustomUA/1.0"


def test_user_agent_under_feishu_section(tmp_path):
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text("feishu:\n  user_agent: FeishuUA/2.0\n", encoding="utf-8")
    assert _load_user_agent(str(cfg)) == "FeishuUA/2.0"


def test_user_agent_default_when_missing(tmp_path):
    assert _load_user_agent(str(tmp_path / "nope.yaml")) == DEFAULT_USER_AGENT


# ──────────────────────────────────────────────
# 4) 断点续传：模拟 Ctrl+C → --resume 继续
# ──────────────────────────────────────────────

def _make_crawler(cp_path):
    # limit=5 使每页 5 条 == limit，不会误判「到底」
    c = FeishuJobCrawler(url="https://x.jobs.feishu.cn", limit=5)
    c.checkpoint_path = cp_path
    c.latest_sig = "sig"  # 真实环境由浏览器拦截填充；测试用假值使详情阶段可执行
    return c


def test_resume_continues_from_checkpoint(tmp_path):
    cp_path = str(tmp_path / "ckpt.json")
    # 3 页，每页 5 个岗位
    ALL = {
        p: [{"id": f"p{p}_{i}", "title": f"t{p}{i}"} for i in range(5)]
        for p in (1, 2, 3)
    }

    async def fetch(jid):
        return {"detail": jid}

    # ---- 第一次：爬到第 3 页途中 Ctrl+C（模拟中断）----
    c1 = _make_crawler(cp_path)
    nav1_seen = []

    async def nav1(page_no):
        nav1_seen.append(page_no)
        if page_no == 3:
            raise KeyboardInterrupt  # 模拟中途 Ctrl+C
        return ALL[page_no]

    try:
        asyncio.run(c1._drive_crawl(nav1, fetch))
    except KeyboardInterrupt:
        pass  # run() 的调用方会捕获并继续

    # 中断后检查点应在盘上，记录到已完成的 page 2
    assert FeishuCheckpoint.exists(cp_path)
    saved = FeishuCheckpoint.load(cp_path)
    assert saved.page_no == 2
    assert len(saved.job_items) == 10

    # ---- 第二次：新进程，从断点续传 ----
    c2 = _make_crawler(cp_path)
    c2._init_resume(True, cp_path)
    assert c2._resume_page == 2
    assert len(c2.jobs) == 10  # 已恢复已发现岗位

    nav2_seen = []

    async def nav2(page_no):
        nav2_seen.append(page_no)
        if page_no > 3:
            return []  # 到底（空页，连续 2 次后停止；不用 None 以免触发导航异常分支）
        return ALL[page_no]

    asyncio.run(c2._drive_crawl(nav2, fetch))

    # 续传补齐 page 3，总数 15，无重复
    assert len(c2.jobs) == 15
    assert len(set(c2.jobs.keys())) == 15
    # 续传从断点（page 2）开始，不从头
    assert nav2_seen[0] == 2
    # 详情全部补齐
    assert len(c2._fetched_detail_ids) == 15


def test_resume_skips_already_fetched_details(tmp_path):
    cp_path = str(tmp_path / "ckpt.json")
    items = [{"id": f"j{i}"} for i in range(4)]
    cp = FeishuCheckpoint(page_no=1, job_items=items, fetched_detail_ids=["j0", "j1"])
    FeishuCheckpoint.save(cp_path, cp)

    c = _make_crawler(cp_path)
    c._init_resume(True, cp_path)
    # 已抓详情的应被跳过
    assert c._fetched_detail_ids == {"j0", "j1"}

    fetched = []

    async def nav(page_no):
        return []  # 列表已就绪，不翻页（空页，连续 2 次后停止）

    async def fetch(jid):
        fetched.append(jid)
        return {"d": jid}

    asyncio.run(c._drive_crawl(nav, fetch))
    # 只抓未抓过的 j2, j3（j0/j1 跳过）
    assert set(fetched) == {"j2", "j3"}
