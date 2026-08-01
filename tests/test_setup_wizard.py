"""setup_wizard.py 单测（Phase 5.1，依赖注入实现离线可测）。

不调用真实 LLM / 网络：profile_gen、check_env_fn、ask 全部注入 mock。
"""
import importlib.util
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "setup_wizard.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("setup_wizard", SCRIPT)
sw = importlib.util.module_from_spec(spec)
sys.modules["setup_wizard"] = sw
spec.loader.exec_module(sw)


SAMPLE_PORTALS = """portals:
  boss: {enabled: true, kind: "boss", backend: "scripts/fetch_boss.py"}
  catdesk: {enabled: true, kind: "catdesk", backend: "scripts/fetch_jobs.py"}
  linkedin: {enabled: true, kind: "linkedin", backend: "scripts/fetch_jobs_linkedin.py", cli: "linkedin-search"}
  shixiseng: {enabled: true, kind: "shixiseng", backend: "scripts/fetch_jobs_shixiseng.py"}
  nowcoder: {enabled: false, kind: "nowcoder", backend: "scripts/fetch_jobs_nowcoder.py"}
websearch_fallback: {enabled: true, kind: "websearch"}
"""

MULTI_PORTALS = """portals:
  boss:
    enabled: true
    kind: boss
  nowcoder:
    enabled: false
    kind: nowcoder
websearch_fallback: {enabled: true, kind: "websearch"}
"""


# --- set_portal_prefs 纯函数（内联 dict 写法）--------------------------------

def test_set_portal_prefs_inline_merge_keeps_others():
    out = sw.set_portal_prefs(SAMPLE_PORTALS, {"boss": False, "linkedin": True})
    assert "boss: {enabled: false" in out
    assert "linkedin: {enabled: true" in out
    # 未列出的门户保持原状（merge，不 clobber）
    assert "catdesk: {enabled: true" in out
    assert "shixiseng: {enabled: true" in out
    assert "nowcoder: {enabled: false" in out
    # websearch_fallback 在 portals: 段外，不动
    assert "websearch_fallback: {enabled: true" in out


def test_set_portal_prefs_multiline_form():
    out = sw.set_portal_prefs(MULTI_PORTALS, {"boss": False})
    assert "enabled: false" in out
    # nowcoder 不在 decisions，保持 false
    assert "nowcoder:" in out


# --- _apply_portal_prefs 落盘 -------------------------------------------------

def test_apply_portal_prefs_merge(tmp_path):
    p = tmp_path / "portals.yaml"
    p.write_text(SAMPLE_PORTALS, encoding="utf-8")
    sw._apply_portal_prefs(["boss", "linkedin"], False, p)
    txt = p.read_text(encoding="utf-8")
    assert "boss: {enabled: true" in txt
    assert "linkedin: {enabled: true" in txt
    assert "shixiseng: {enabled: true" in txt  # 未列出保持原状


def test_apply_portal_prefs_disable_others(tmp_path):
    p = tmp_path / "portals.yaml"
    p.write_text(SAMPLE_PORTALS, encoding="utf-8")
    sw._apply_portal_prefs(["boss"], True, p)
    txt = p.read_text(encoding="utf-8")
    assert "boss: {enabled: true" in txt
    # 其余全部置 false
    assert "catdesk: {enabled: false" in txt
    assert "linkedin: {enabled: false" in txt
    assert "shixiseng: {enabled: false" in txt
    assert "nowcoder: {enabled: false" in txt


# --- run_setup 端到端（注入 mock）-------------------------------------------

def _opts(tmp_path, **kw):
    base = dict(
        resume=None,
        resume_text=None,
        direction="社招",
        portals=None,
        disable_others=False,
        output_dir=str(tmp_path),
        profile_json=None,
        skip_profile=False,
        skip_env_check=True,
        non_interactive=True,
        yes=True,
        portals_yaml=str(tmp_path / "portals.yaml"),
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_run_setup_writes_profile_and_portals(tmp_path):
    (tmp_path / "portals.yaml").write_text(SAMPLE_PORTALS, encoding="utf-8")
    opts = _opts(tmp_path, resume_text="粘贴的简历内容", direction="社招",
                 portals="boss,linkedin")

    gen_calls = {}
    def fake_gen(resume_path, direction, scratch_dir):
        gen_calls["ran"] = True
        assert direction == "社招"
        return {"name": "测试", "direction": direction, "candidate_summary": "摘要"}, "摘要文本"

    result = sw.run_setup(opts, profile_gen=fake_gen)
    assert gen_calls.get("ran")
    assert (tmp_path / "boundary_profile.json").exists()
    assert (tmp_path / "candidate_summary.txt").read_text(encoding="utf-8") == "摘要文本"
    assert result["steps"]["portals"] == ["boss", "linkedin"]
    assert result["direction"] == "社招"
    # 简历文本被落盘为临时文件并喂给生成器
    assert result["resume_path"] is not None


def test_run_setup_default_direction_when_missing(tmp_path):
    (tmp_path / "portals.yaml").write_text(SAMPLE_PORTALS, encoding="utf-8")
    opts = _opts(tmp_path, resume_text="x", direction=None,
                 portals="boss")
    sw.run_setup(opts, profile_gen=lambda *a: ({"candidate_summary": "s"}, "s"))
    # 非交互 + 未给方向 → 默认 社招
    assert opts.direction is None  # 原 opts 不变
    # 但 run_setup 返回的 direction 应为默认
    # （通过重新调用取返回值验证）
    res = sw.run_setup(opts, profile_gen=lambda *a: ({"candidate_summary": "s"}, "s"))
    assert res["direction"] == "社招"


def test_run_setup_skip_profile_reuses_existing(tmp_path):
    prof = tmp_path / "boundary_profile.json"
    prof.write_text('{"name": "老档案", "candidate_summary": "旧摘要"}', encoding="utf-8")
    (tmp_path / "portals.yaml").write_text(SAMPLE_PORTALS, encoding="utf-8")
    opts = _opts(tmp_path, profile_json=str(prof), skip_profile=True, portals="boss")

    called = {"gen": False}
    def fake_gen(*a):
        called["gen"] = True
        return {}, ""

    sw.run_setup(opts, profile_gen=fake_gen)
    assert called["gen"] is False  # 未重新生成
    txt = (tmp_path / "candidate_summary.txt").read_text(encoding="utf-8")
    assert txt == "旧摘要"


def test_run_setup_runs_env_check_when_enabled(tmp_path):
    (tmp_path / "portals.yaml").write_text(SAMPLE_PORTALS, encoding="utf-8")
    opts = _opts(tmp_path, resume_text="x", portals="boss", skip_env_check=False)
    env_calls = {"n": 0}
    def fake_env():
        env_calls["n"] += 1
        return 0
    res = sw.run_setup(opts, profile_gen=lambda *a: ({"candidate_summary": "s"}, "s"),
                       check_env_fn=fake_env)
    assert env_calls["n"] == 1
    assert res["steps"]["env_check"] == "passed"
