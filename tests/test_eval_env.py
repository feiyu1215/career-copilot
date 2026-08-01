"""M1 回归测试：evals/eval_env.py 共享 .env 加载工具。

覆盖：
- load_dotenv_like 支持 mapping（OPENAI_* → friday 变量）
- scholar_dotenv_path 受 SCHOLAR_DOTENV 覆盖、默认开发机绝对路径
- load_provider_env 按覆盖路径加载 scholar .env（可移植性）
"""
import importlib.util
import os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "evals" / "eval_env.py"
spec = importlib.util.spec_from_file_location("eval_env_test", SCRIPT)
ee = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ee)


def test_load_dotenv_like_with_mapping(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text(
        "OPENAI_API_KEY=sk-x\nOPENAI_BASE_URL=http://h\nNVIDIA_API_KEY=nv\n",
        encoding="utf-8",
    )
    for k in ("FRIDAY_APP_ID", "LLM_BASE_URL", "NVIDIA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    ee.load_dotenv_like(
        str(p), mapping={"OPENAI_BASE_URL": "LLM_BASE_URL", "OPENAI_API_KEY": "FRIDAY_APP_ID"}
    )
    assert os.environ["FRIDAY_APP_ID"] == "sk-x"
    assert os.environ["LLM_BASE_URL"] == "http://h"
    assert os.environ["NVIDIA_API_KEY"] == "nv"


def test_load_dotenv_like_missing_file_is_noop(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    ee.load_dotenv_like(str(tmp_path / "nope.env"))
    # 不应抛异常；NVIDIA_API_KEY 保持未设置
    assert "NVIDIA_API_KEY" not in os.environ


def test_scholar_dotenv_path_override(monkeypatch):
    monkeypatch.setenv("SCHOLAR_DOTENV", "/some/ci/path/.env")
    assert ee.scholar_dotenv_path() == "/some/ci/path/.env"


def test_scholar_dotenv_path_default(monkeypatch):
    monkeypatch.delenv("SCHOLAR_DOTENV", raising=False)
    assert ee.scholar_dotenv_path() == ee.DEFAULT_SCHOLAR_ENV


def test_load_provider_env_uses_override(tmp_path, monkeypatch):
    scholar_env = tmp_path / "scholar.env"
    scholar_env.write_text(
        "OPENAI_API_KEY=fr-app\nOPENAI_BASE_URL=fr-url\n", encoding="utf-8"
    )
    monkeypatch.setenv("SCHOLAR_DOTENV", str(scholar_env))
    for k in ("FRIDAY_APP_ID", "LLM_BASE_URL", "NVIDIA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    ee.load_provider_env()
    # scholar 部分按覆盖路径加载，且经 mapping 映射为 friday 变量
    assert os.environ["FRIDAY_APP_ID"] == "fr-app"
    assert os.environ["LLM_BASE_URL"] == "fr-url"
