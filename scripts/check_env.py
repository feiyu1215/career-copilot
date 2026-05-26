#!/usr/bin/env python3
"""
Career Copilot 环境检测脚本。
分享给他人时，先跑这个确认基础环境就绪。

用法：python3 check_env.py
"""

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

    # 网络连通性检查
    print("\n  网络连通性检测：")
    _check_network_connectivity()

    # LLM 调用配置提示
    print("\n  ℹ️  LLM 平台配置（多 Provider 支持）：")
    print("     当前实现支持两个 Provider：internal（内部平台）和 external（外部 API 代理）")
    print("     切换方式：")
    print("       1. 环境变量 LLM_PROVIDER=internal|external（全局默认）")
    print("       2. 脚本参数 --provider internal|external（单次覆盖）")
    print("       3. Pipeline 启动时 AskQuestion 交互选择")
    print("     高级覆盖：LLM_BASE_URL/LLM_API_KEY（internal）或 EXTERNAL_BASE_URL/EXTERNAL_API_KEY（external）")

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


def _check_network_connectivity():
    """检测 LLM Provider 的网络连通性（HEAD 请求，5s 超时）。"""
    import os
    import urllib.request
    import urllib.error

    providers = {
        "internal": os.environ.get("LLM_BASE_URL", ""),
        "external": os.environ.get("EXTERNAL_BASE_URL", ""),
    }

    for name, base_url in providers.items():
        if not base_url:
            print(f"    ⚠️  {name} — 未配置（请在 .env 中设置对应 URL）")
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
