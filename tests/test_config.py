"""T5 Pipeline 配置化测试。"""
import sys

sys.path.insert(0, "scripts")

from smart_score import load_config, DEFAULT_CONFIG_PATH  # noqa: E402


def test_load_config_falls_back_to_defaults_when_missing():
    cfg = load_config("/nonexistent/path/pipeline.yaml")
    assert cfg["stage1"]["batch_size"] == 25
    assert cfg["stage2"]["group_size"] == 6
    assert cfg["stage1"]["truncation_chars"] == 1500
    assert cfg["tiers"]["A"] == 85
    assert cfg["tiers"]["B"] == 72
    assert cfg["stage1"]["circuit_breaker_threshold"] == 0.30


def test_load_config_reads_default_yaml():
    # 默认 config/pipeline.yaml 必须存在且可被加载
    assert DEFAULT_CONFIG_PATH.exists(), f"missing {DEFAULT_CONFIG_PATH}"
    cfg = load_config()
    assert cfg["stage2"]["group_size"] == 6
    assert cfg["stage1"]["circuit_min_samples"] == 5
    assert cfg["pipeline"]["timeout_seconds"] == 1800


def test_load_config_merge_overrides_defaults():
    # 用临时文件验证深度合并（file_cfg 覆盖 defaults）
    import tempfile
    import os
    import textwrap

    content = textwrap.dedent("""
        stage2:
          group_size: 4
        tiers:
          A: 90
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(content)
        path = f.name
    try:
        cfg = load_config(path)
        assert cfg["stage2"]["group_size"] == 4          # 覆盖
        assert cfg["stage2"]["model"] == "gpt-4.1-mini"  # 保留默认
        assert cfg["tiers"]["A"] == 90                    # 覆盖
        assert cfg["tiers"]["B"] == 72                    # 保留默认
    finally:
        os.unlink(path)
