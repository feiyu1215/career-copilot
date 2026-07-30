#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""career-copilot evals 共享 .env 加载工具（M1：抽出三处重复的 .env 加载逻辑）。

设计要点：
- load_dotenv_like：覆盖式注入（与 python-dotenv --override 一致），统一三处语义。
- scholar .env 默认位置硬编码为开发机绝对路径（向后兼容）；生产 / CI 用
  环境变量 SCHOLAR_DOTENV 覆盖，避免依赖特定机器路径（可移植性）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 向后兼容的默认 scholar .env（用户本机路径）；
# 生产 / CI 用环境变量 SCHOLAR_DOTENV 覆盖，避免依赖特定机器路径。
DEFAULT_SCHOLAR_ENV = r"D:\57709\Desktop\Apple\美团\scholar-agent-public.working-20260707\.env"

# scholar .env 的 key 映射：OPENAI_* → friday provider 变量
# （scholar 仓用 OPENAI_* 名义存内部 One-API 凭据，映射到本仓 friday provider 的变量名）。
SCHOLAR_MAPPING = {"OPENAI_BASE_URL": "LLM_BASE_URL", "OPENAI_API_KEY": "FRIDAY_APP_ID"}


def load_dotenv_like(path: str, mapping=None) -> None:
    """读 .env 注入 os.environ（覆盖式）。

    path 可为相对 ROOT 的路径或绝对路径。找不到文件时打印告警并跳过（不抛异常）。
    """
    p = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.exists(p):
        print(f"[load_env] 未找到 {p}", file=sys.stderr)
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if mapping and k in mapping:
            k = mapping[k]
        os.environ[k] = v


def scholar_dotenv_path() -> str:
    """返回 scholar .env 路径：受 SCHOLAR_DOTENV 覆盖，默认开发机绝对路径。"""
    return os.environ.get("SCHOLAR_DOTENV") or DEFAULT_SCHOLAR_ENV


def load_provider_env() -> None:
    """注入两个 .env 的 key：本仓 .env（NVIDIA 等）+ scholar .env（AGNES / friday）。

    必须在 import llm_client 之前调用：llm_client 在 import 时即快照 NVIDIA_*/AGNES_*
    等环境变量，若 import 时 env 为空，模块级变量会被捕获成 ""，之后再设也无效。
    """
    load_dotenv_like(".env")
    load_dotenv_like(scholar_dotenv_path(), mapping=SCHOLAR_MAPPING)
