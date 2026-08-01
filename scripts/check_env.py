#!/usr/bin/env python3
"""
Career Copilot 环境检测脚本。
分享给他人时，先跑这个确认基础环境就绪。

用法：python3 check_env.py
"""

import shutil
import sys


def check(label: str, ok: bool, fix: str = ""):
    if ok:
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}"
        if fix:
            msg += f" → {fix}"
        print(msg)
    return ok


def main():
    print("Career Copilot 环境检测\n")
    all_ok = True

    # Python 版本
    v = sys.version_info
    all_ok &= check(
        f"Python {v.major}.{v.minor}.{v.micro}",
        v >= (3, 9),
        "需要 Python ≥ 3.9"
    )

    # PDF 解析（gen_profile.py 硬依赖）
    pdf_libs = ["pypdf", "PyPDF2", "pdfminer"]
    pdf_available = [lib for lib in pdf_libs if _try_import(lib)]
    if pdf_available:
        all_ok &= check(f"PDF 解析库: {', '.join(pdf_available)}", True)
    else:
        all_ok &= check(
            "PDF 解析库（pypdf/PyPDF2/pdfminer）均未安装",
            False,
            "pip install pypdf"
        )

    # openai 包（llm_client.py 硬依赖）
    openai_ok = _try_import("openai")
    all_ok &= check(
        "openai 包",
        openai_ok,
        "pip install openai"
    )

    # LaTeX 引擎（build_cv 编译 PDF 硬依赖；优先级与 build_cv 一致）
    latex_engine = detect_latex_engine()
    all_ok &= check(
        f"LaTeX 引擎 ({'/'.join(ENGINE_CANDIDATES)})",
        latex_engine is not None,
        "安装 TeX 发行版（TeX Live / MiKTeX）"
    )

    # python-docx（build_cv 的 DOCX 降级路径）
    docx_ok = _try_import("docx")
    all_ok &= check(
        "python-docx（DOCX 降级路径）",
        docx_ok,
        "pip install python-docx"
    )

    # 网络连通性检查
    print("\n  网络连通性检测：")
    _check_network_connectivity()

    # LLM 调用配置提示
    print("\n  ℹ️  LLM 平台配置（多 Provider 支持）：")
    print("     系统支持四个 Provider：friday（内部平台）、sub2api（外部 API 代理）、nvidia（开源模型托管）、agnes（外部可达）；")
    print("     降级顺序由 LLM_FAILOVER_CHAIN 控制（默认 friday,sub2api,nvidia,agnes）。下方会依次探测已配置 Provider 的连通性。")
    print("     切换方式：")
    print("       1. 环境变量 LLM_PROVIDER=friday|sub2api|nvidia|agnes（全局默认）")
    print("       2. 脚本参数 --provider <name>（单次覆盖）")
    print("       3. Pipeline 启动时 AskQuestion 交互选择")
    print("     高级覆盖：LLM_BASE_URL/FRIDAY_APP_ID（Friday）、SUB2API_BASE_URL/SUB2API_API_KEY（Sub2API）、")
    print("                NVIDIA_BASE_URL/NVIDIA_API_KEY（NVIDIA）、AGNES_BASE_URL/AGNES_API_KEY（Agnes）")

    print()
    if all_ok:
        print("🎉 基础环境就绪。")
    else:
        print("⚠️  请修复上述 ❌ 项后重试。")
    sys.exit(0 if all_ok else 1)


def _try_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# LaTeX 引擎优先级：与 build_cv.find_latex_engine 保持一致（lualatex > xelatex > pdflatex）。
# 自包含实现，避免在 bootstrap 期 import build_cv 连带拉入 verify_ats / visual_inspect 重依赖。
ENGINE_CANDIDATES = ("lualatex", "xelatex", "pdflatex")


def detect_latex_engine() -> str | None:
    """返回首个可用的 LaTeX 引擎；都没有返回 None（调用方须显式报错，不静默降级）。"""
    for engine in ENGINE_CANDIDATES:
        if shutil.which(engine):
            return engine
    return None


def _check_network_connectivity():
    """检测 LLM Provider 的网络连通性（HEAD 请求，5s 超时）。"""
    import os
    import urllib.error
    import urllib.request

    providers = {
        "friday": os.environ.get("LLM_BASE_URL", "https://friday.xiaojukeji.com"),
        "sub2api": os.environ.get("SUB2API_BASE_URL", "https://api.sub2api.com"),
        "nvidia": os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "agnes": os.environ.get("AGNES_BASE_URL", ""),
    }

    for name, base_url in providers.items():
        if not base_url:
            # agnes 等未配置 BASE_URL 的 Provider：跳过连通性探测，避免误报不可达
            print(f"    ⏭️  {name} — 未配置 BASE_URL，跳过连通性检测")
            continue
        # 规范化 URL：确保是 https 开头的完整地址
        url = base_url.rstrip("/")
        if not url.startswith("http"):
            url = f"https://{url}"

        try:
            req = urllib.request.Request(url, method="HEAD")
            urllib.request.urlopen(req, timeout=5)
            print(f"    ✅ {name} ({url}) — 可达")
        except urllib.error.HTTPError as e:
            # 4xx/5xx 说明网络是通的，服务端拒绝 HEAD 而已
            if e.code < 500:
                print(f"    ✅ {name} ({url}) — 可达 (HTTP {e.code})")
            else:
                print(f"    ⚠️  {name} ({url}) — 服务端错误 (HTTP {e.code})")
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", str(e))
            print(f"    ❌ {name} ({url}) — 不可达: {reason}")
        except Exception as e:
            print(f"    ❌ {name} ({url}) — 异常: {e}")


if __name__ == "__main__":
    main()
