#!/usr/bin/env python3
"""加载 config/constraints.yaml —— skill 关键确定性约束的单一事实源。

verify_output.py / post_judge.py / 相关测试 都通过本模块读取约束，
确保「A 档比例、C9 语义」等只在一处定义，消除散落各处的硬编码常量。

依赖：PyYAML（项目 requirements.txt 已含）。缺失时抛出明确错误提示。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

# constraints.yaml 位于本文件上一级的 config/ 目录
CONSTRAINTS_PATH = Path(__file__).resolve().parent.parent / "config" / "constraints.yaml"


@lru_cache(maxsize=1)
def load_constraints() -> dict:
    """读取并返回约束配置（结果缓存，整个进程只解析一次）。"""
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "读取 config/constraints.yaml 需要 PyYAML。请先安装：pip install pyyaml"
        ) from exc

    if not CONSTRAINTS_PATH.exists():
        raise RuntimeError(f"约束配置文件缺失：{CONSTRAINTS_PATH}")

    with CONSTRAINTS_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise RuntimeError(f"约束配置文件格式错误（应为映射）：{CONSTRAINTS_PATH}")
    return data


if __name__ == "__main__":
    import json

    print(json.dumps(load_constraints(), ensure_ascii=False, indent=2))
