"""T8 提示词外部化测试：config/prompts.yaml 为单一可信源，且与内联默认逐字一致。

核心不变量：
  1. 4 个系统提示词都能从 config/prompts.yaml 正确加载；
  2. YAML 文本必须与 _DEFAULT_PROMPTS 内联默认**逐字相同** —— 这是“外部化零回归”
     的硬性保证：正常路径走 YAML，兜底路径走内联，两者输出必须完全一致；
  3. build_* 函数的 .format() 必须正确注入动态字段、且无残留占位符。
"""
import sys

sys.path.insert(0, "scripts")

from smart_score import (  # noqa: E402
    _DEFAULT_PROMPTS,
    _GLOBAL_RERANK_TEMPLATE,
    _PROMPTS,
    CALIBRATION_SYSTEM,
    _build_rerank_system,
    build_stage1_system,
    build_stage2_system,
    load_prompts,
)

PROMPT_KEYS = ("stage1_system", "stage2_system", "calibration_system", "global_rerank_system")


def test_prompts_yaml_loaded_with_four_keys():
    prompts = load_prompts()
    for key in PROMPT_KEYS:
        assert key in prompts, f"{key} 缺失于 config/prompts.yaml"
        assert isinstance(prompts[key], str) and prompts[key].strip(), f"{key} 为空"


def test_yaml_matches_inline_default_no_drift():
    # T8 关键不变量：YAML 文本必须与内联默认逐字一致，避免静默漂移导致行为变化
    for key in PROMPT_KEYS:
        assert _PROMPTS[key] == _DEFAULT_PROMPTS[key], (
            f"{key}：config/prompts.yaml 与 _DEFAULT_PROMPTS 不一致，"
            f"外部化将改变 LLM 输入"
        )


def test_build_stage1_substitutes_anchor():
    out = build_stage1_system("搜索推荐方向")
    assert "搜索推荐方向" in out
    assert "{direction_anchor}" not in out  # 无残留占位符


def test_build_stage2_substitutes_all_placeholders():
    out = build_stage2_system(
        domain_knowledge="## 行业知识XYZ",
        calibration_knowledge="## 辨别知识XYZ",
        profile={"role_type": "AI产品经理"},
        group_size=6,
    )
    assert "AI产品经理" in out
    assert "## 行业知识XYZ" in out
    assert "## 辨别知识XYZ" in out
    assert "6" in out
    for ph in ("{role_type}", "{domain_knowledge}", "{calibration_knowledge}", "{group_size}",
               "{stage2_top_low}", "{stage2_top_high}", "{stage2_bottom_cap}"):
        assert ph not in out  # 无残留占位符


def test_constants_loaded():
    assert CALIBRATION_SYSTEM.strip()
    assert _GLOBAL_RERANK_TEMPLATE.strip()
    # _build_rerank_system 应注入配置值，无残留占位符
    rendered = _build_rerank_system()
    assert "{rerank_top_score}" not in rendered
    assert "{rerank_bottom_score}" not in rendered
    assert "{rerank_min_gap}" not in rendered


def test_fallback_when_yaml_missing(monkeypatch):
    # 即使 prompts.yaml 缺失，build 函数仍应产出与内联默认一致的有效提示词
    import pathlib

    missing = pathlib.Path(__file__).resolve().parent.parent / "config" / "prompts_DNE.yaml"
    prompts = load_prompts(str(missing))
    assert prompts == {}, "缺失文件应回退为空 dict"

    # 直接用内联默认构造，验证 .format 不抛异常且字段被替换
    out = _DEFAULT_PROMPTS["stage1_system"].format(direction_anchor="兜底锚点")
    assert "兜底锚点" in out
    out2 = _DEFAULT_PROMPTS["stage2_system"].format(
        role_type="R", domain_knowledge="D", calibration_knowledge="C", group_size=6,
        stage2_top_low=90, stage2_top_high=97, stage2_bottom_cap=75,
    )
    assert "R" in out2 and "D" in out2 and "C" in out2
    # rerank 模板兜底
    out3 = _DEFAULT_PROMPTS["global_rerank_system"].format(
        rerank_top_score=97, rerank_bottom_score=72, rerank_min_gap=20, rerank_top_score_minus_2=95,
    )
    assert "97" in out3 and "{rerank_top_score}" not in out3
