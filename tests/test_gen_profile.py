"""M3 回归测试：gen_profile.PROFILE_SYSTEM_PROMPT 现已包含 core_team_signals 字段。

此前 core_team_signals 是死字段——post_judge.detect_core_team 读取它，但 gen_profile 的
schema 从不产出它。现已在 schema 中补上，使该特性真正生效（无需目标公司输入，
由简历中真实参与过的核心团队/核心产品线推导）。
"""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gen_profile.py"
spec = importlib.util.spec_from_file_location("gen_profile_test", SCRIPT)
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)


def test_profile_prompt_includes_core_team_signals():
    assert "core_team_signals" in gp.PROFILE_SYSTEM_PROMPT
