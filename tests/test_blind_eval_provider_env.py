"""M4 回归测试：blind_eval_runner._provider_env_names 按 provider 返回正确的 env 变量名。

此前 _make_client 用 ``{provider.upper()}_API_KEY/_BASE_URL`` 读取 env，对 friday 会读
FRIDAY_API_KEY / FRIDAY_BASE_URL（实际不存在），导致显式传入的 key 为 None、回退到
llm_client 的 import-time 快照，脆弱点未被真正规避。
"""
import sys
from pathlib import Path

import importlib.util

EVALS_DIR = Path(__file__).resolve().parent.parent / "evals"
if str(EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(EVALS_DIR))

SCRIPT = EVALS_DIR / "blind_eval_runner.py"
spec = importlib.util.spec_from_file_location("blind_eval_test", SCRIPT)
ber = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ber)


def test_provider_env_names_friday_special():
    assert ber._provider_env_names("friday") == ("FRIDAY_APP_ID", "LLM_BASE_URL")


def test_provider_env_names_others():
    assert ber._provider_env_names("agnes") == ("AGNES_API_KEY", "AGNES_BASE_URL")
    assert ber._provider_env_names("nvidia") == ("NVIDIA_API_KEY", "NVIDIA_BASE_URL")
    assert ber._provider_env_names("sub2api") == ("SUB2API_API_KEY", "SUB2API_BASE_URL")


def test_provider_env_names_unknown_fallback():
    assert ber._provider_env_names("foo") == ("FOO_API_KEY", "FOO_BASE_URL")
