"""m6 回归测试：llm_client 模块 docstring 应列出全部 4 个 provider（friday/sub2api/nvidia/agnes）。

此前 docstring 仅文档化 friday/sub2api，与实际 PROVIDERS 注册表（含 nvidia/agnes）不一致。
"""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "llm_client.py"
spec = importlib.util.spec_from_file_location("llm_client_doc", SCRIPT)
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)


def test_docstring_lists_all_providers():
    doc = lc.__doc__ or ""
    for p in ("friday", "sub2api", "nvidia", "agnes"):
        assert p in doc, f"docstring 缺少 provider: {p}"
