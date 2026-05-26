#!/usr/bin/env python3
"""
fetch_jobs.py — 批量抓取招聘网站岗位 JD（v3 通用辅助脚本）

设计定位：
    catdesk-browser 的多页抓取辅助工具。如果 catdesk-browser 原生支持
    批量翻页抓取，可不使用本脚本。当原生能力不足时，本脚本作为确定性
    翻页循环的兜底方案。

用法：
    python3 fetch_jobs.py \\
        --base-url "https://jobs.bytedance.com/campus/position/list?current={page}&limit=10" \\
        --output ./jobs_raw.txt \\
        [--total-pages 60] \\
        [--start-page 1] \\
        [--delay 2.0] \\
        [--selector "自定义JS选择器表达式"] \\
        [--preset bytedance]

参数说明：
    --base-url      翻页 URL 模板，用 {page} 作为页码占位符
    --output        输出文件路径（默认 ./jobs_raw.txt）
    --total-pages   最大页数上限（默认 60，遇空页自动停止）
    --start-page    从第几页开始（默认 1，断点续爬时可设为已爬到的页码+1）
    --delay         每页之间等待秒数（默认 2.0）
    --selector      自定义 JS 提取表达式（返回 ||| 分隔的文本）
    --preset        使用内置选择器预设（bytedance / meituan / alibaba / generic）

输出格式：
    # JOB_MATCHER_FORMAT v1 generated_at=<ISO时间> total_jobs=<N>
    --- JOB 1 ---
    <完整 JD 文本>

    --- JOB 2 ---
    ...

终止条件（智能停止，无需精确知道总页数）：
    - 连续 2 页返回空结果 → 已到最后
    - 当前页所有标题与已收集标题完全重复 → 已到最后
    - 连续 5 次导航失败 → 网络异常
"""

from __future__ import annotations

import subprocess
import json
import time
import argparse
import sys
import os
import re
import datetime
import hashlib
import shutil

# 自动检测 catdesk 路径（优先级：环境变量 > ~/.catdesk/bin > ~/.catpaw/bin > PATH）
def _find_catdesk() -> str:
    """查找 catdesk 可执行文件路径"""
    # 1. 环境变量
    if "CATDESK_BIN" in os.environ:
        return os.environ["CATDESK_BIN"]
    
    # 2. 常见安装位置
    candidates = [
        os.path.expanduser("~/.catdesk/bin/catdesk"),
        os.path.expanduser("~/.catpaw/bin/catdesk"),
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    
    # 3. PATH 中查找
    catdesk_in_path = shutil.which("catdesk")
    if catdesk_in_path:
        return catdesk_in_path
    
    # 4. 都找不到，返回默认值（会在运行时报错）
    return "catdesk"

CATDESK = _find_catdesk()

# ============================================================
# 内置选择器预设
# ============================================================

PRESETS = {
    "bytedance": (
        "(() => {"
        "  const seen = new Set();"
        "  return Array.from(document.querySelectorAll('[class*=positionItem]'))"
        "    .filter(el => el.querySelector('.positionItem-jobDesc'))"
        "    .map(el => {"
        "      const text = el.innerText.trim();"
        "      const a = el.querySelector('a[href]');"
        "      const url = a ? a.href : '';"
        "      return url ? '[URL]' + url + '[/URL]\\n' + text : text;"
        "    })"
        "    .filter(t => {"
        "      const clean = t.replace(/^\\[URL\\].*?\\[\\/URL\\]\\n/, '');"
        "      if (clean.length <= 20) return false;"
        "      const title = clean.split('\\n')[0].trim();"
        "      if (seen.has(title)) return false;"
        "      seen.add(title);"
        "      return true;"
        "    })"
        "    .join('|||');"
        "})()"
    ),
    "meituan": (
        "Array.from(document.querySelectorAll("
        "'.job-item, [class*=job-card], [class*=position-item]'"
        ")).map(el => {"
        "  const text = el.innerText.trim();"
        "  const a = el.querySelector('a[href]');"
        "  const url = a ? a.href : '';"
        "  return url ? '[URL]' + url + '[/URL]\\n' + text : text;"
        "}).filter(t => t.replace(/^\\[URL\\].*?\\[\\/URL\\]\\n/, '').length > 20).join('|||')"
    ),
    "alibaba": (
        "Array.from(document.querySelectorAll("
        "'.position-item, [class*=job-card], [class*=item-inner]'"
        ")).map(el => {"
        "  const text = el.innerText.trim();"
        "  const a = el.querySelector('a[href]');"
        "  const url = a ? a.href : '';"
        "  return url ? '[URL]' + url + '[/URL]\\n' + text : text;"
        "}).filter(t => t.replace(/^\\[URL\\].*?\\[\\/URL\\]\\n/, '').length > 20).join('|||')"
    ),
    "generic": (
        "Array.from(document.querySelectorAll("
        "'[class*=position-list] [class*=position-item], "
        "[class*=job-list] [class*=job-item], "
        "[class*=list] a[href*=position], "
        "[class*=job-card], [class*=position-card]'"
        ")).map(el => {"
        "  const text = el.innerText.trim();"
        "  const a = el.tagName === 'A' ? el : el.querySelector('a[href]');"
        "  const url = a ? a.href : '';"
        "  return url ? '[URL]' + url + '[/URL]\\n' + text : text;"
        "}).filter(t => t.replace(/^\\[URL\\].*?\\[\\/URL\\]\\n/, '').length > 20).join('|||')"
    ),
}


# ============================================================
# 核心函数
# ============================================================

def run_browser_action(action_json: str, timeout: int = 30) -> dict:
    """执行 catdesk browser-action 命令并返回解析后的结果。
    
    返回值中若含 "_error" 字段，表示执行失败（超时/异常）。
    调用方应检查此字段并决定是否重试。
    """
    try:
        result = subprocess.run(
            [CATDESK, "browser-action", action_json],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr:
                print(f"  [WARN] stderr: {stderr[:100]}")
            # 尝试解析 stdout（即使 returncode != 0 也可能有有效 JSON）
            if result.stdout.strip():
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"_error": f"returncode={result.returncode}", "raw_output": result.stdout.strip()}
            return {"_error": f"returncode={result.returncode}"}
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except subprocess.TimeoutExpired:
        # 超时是严重错误，不应该被当作"空结果"处理
        return {"_error": f"timeout_after_{timeout}s"}
    except json.JSONDecodeError as e:
        # 如果 stdout 不是 JSON，返回原始文本并标记错误
        return {"_error": f"json_decode_error: {str(e)}", "raw_output": result.stdout.strip() if 'result' in dir() else ""}
    except Exception as e:
        return {"_error": f"exception: {str(e)}"}


def navigate_to_page(url: str) -> bool:
    """导航到指定 URL"""
    action = json.dumps({"action": "navigate", "url": url, "waitUntil": "networkidle"})
    result = run_browser_action(action, timeout=30)
    # catdesk browser-action navigate 成功时返回 {"success": true} 或类似结构
    # 容错：只要不是明确失败就认为成功
    if not result:
        return False
    if result.get("error"):
        return False
    return True


def extract_jobs_from_page(selector: str) -> tuple[list[str], bool]:
    """从当前页面提取岗位文本列表。
    
    返回 (jobs_list, success_flag)：
    - success_flag=True: 成功提取（可能为空，但不是因为错误）
    - success_flag=False: 执行失败（超时/异常），调用方应重试
    """
    action = json.dumps({"action": "evaluate", "script": selector})
    result = run_browser_action(action, timeout=20)

    # 检查是否有错误标记
    if isinstance(result, dict) and "_error" in result:
        error_msg = result.get("_error", "unknown error")
        print(f"  [ERROR] {error_msg}")
        return [], False  # 失败，应该重试

    # 兼容多种返回格式
    raw = ""
    if isinstance(result, dict):
        # 格式1: {"data": {"result": "..."}}
        data = result.get("data")
        if isinstance(data, dict):
            raw = data.get("result", "")
        # 格式2: {"result": "..."}
        elif "result" in result:
            raw = result.get("result", "")
        # 格式3: {"output": "..."}
        elif "output" in result:
            raw = result.get("output", "")
        # 格式4: 原始文本
        elif "raw_output" in result:
            raw = result.get("raw_output", "")

    if not raw or raw in ("null", '""', "undefined"):
        return [], True  # 成功但为空

    jobs = [j.strip() for j in raw.split("|||") if j.strip() and len(j.strip()) > 20]
    return jobs, True  # 成功


def _strip_url_prefix(job_text: str) -> str:
    """去掉 [URL]...[/URL] 前缀，返回纯内容文本"""
    if job_text.startswith("[URL]"):
        idx = job_text.find("[/URL]")
        if idx != -1:
            return job_text[idx + 6:].lstrip("\n")
    return job_text


def _dedup_key(job_text: str) -> str:
    """生成去重 key（MD5 of 前200字符，去掉 URL 前缀）"""
    clean = _strip_url_prefix(job_text)
    return hashlib.md5(clean[:200].encode("utf-8")).hexdigest()


def _get_title(job_text: str) -> str:
    """提取岗位标题（第一行，去掉 URL 前缀）"""
    clean = _strip_url_prefix(job_text)
    return clean.split("\n")[0].strip()


def fetch_all_jobs(
    base_url: str,
    total_pages: int,
    output_file: str,
    start_page: int = 1,
    delay: float = 2.0,
    selector: str = PRESETS["generic"],
    prepended_jobs: list[str] | None = None,
) -> int:
    """
    批量抓取所有页面的岗位，保存到文件。
    返回总抓取岗位数。

    智能终止：无需精确知道总页数，连续空页或全重复时自动停止。
    """
    if "{page}" not in base_url:
        print("[ERROR] --base-url 必须包含 {page} 占位符")
        print("  例: https://jobs.bytedance.com/campus/position/list?current={page}&limit=10")
        return 0

    all_jobs = list(prepended_jobs) if prepended_jobs else []
    failed_pages = []
    consecutive_nav_failures = 0
    consecutive_empty_pages = 0  # 连续空结果计数

    # 去重集合
    seen_hashes = set()
    seen_titles = set()
    for job in all_jobs:
        seen_hashes.add(_dedup_key(job))
        seen_titles.add(_get_title(job))

    print(f"=" * 60)
    print(f"fetch_jobs.py — Career Copilot 多页抓取")
    print(f"=" * 60)
    print(f"URL 模板: {base_url}")
    print(f"页数上限: {total_pages}（遇空页自动停止）")
    print(f"起始页: {start_page}")
    print(f"每页延迟: {delay}s")
    print(f"输出文件: {output_file}")
    if all_jobs:
        print(f"已有岗位: {len(all_jobs)}（断点续爬）")
    print(f"-" * 60)

    crawl_start_time = time.time()
    try:
        for page in range(start_page, total_pages + 1):
            url = base_url.replace("{page}", str(page))
            # 计算 ETA
            elapsed = time.time() - crawl_start_time
            pages_done = page - start_page
            if pages_done > 0:
                avg_per_page = elapsed / pages_done
                remaining_pages = total_pages - page
                eta = avg_per_page * remaining_pages
                eta_str = f" | ETA: {eta:.0f}s"
            else:
                eta_str = ""
            print(f"[{page}/{total_pages}]{eta_str} ", end="", flush=True)

            # 导航
            success = navigate_to_page(url)
            if not success:
                print(f"导航失败")
                failed_pages.append(page)
                consecutive_nav_failures += 1
                if consecutive_nav_failures >= 5:
                    print(f"\n[STOP] 连续 {consecutive_nav_failures} 次导航失败，停止抓取")
                    break
                continue

            consecutive_nav_failures = 0
            time.sleep(delay)

            # 提取（带重试逻辑）
            jobs, success = extract_jobs_from_page(selector)
            
            # 如果执行失败（超时/异常），重试一次
            if not success:
                print(f"重试...", end=" ", flush=True)
                time.sleep(delay)
                jobs, success = extract_jobs_from_page(selector)
            
            # 如果仍然失败，标记为失败页面并继续
            if not success:
                print(f"执行失败，跳过此页")
                failed_pages.append(page)
                continue

            # 如果成功但为空，检查是否到达末尾
            if not jobs:
                consecutive_empty_pages += 1
                print(f"空（连续空页: {consecutive_empty_pages}/2）")
                if consecutive_empty_pages >= 2:
                    print(f"\n[STOP] 连续 {consecutive_empty_pages} 页为空，判定已抓取完毕")
                    break
                failed_pages.append(page)
                continue

            # 去重
            added = 0
            page_all_dup = True
            for job in jobs:
                title = _get_title(job)
                dk = _dedup_key(job)
                if dk not in seen_hashes and title not in seen_titles:
                    seen_hashes.add(dk)
                    seen_titles.add(title)
                    all_jobs.append(job)
                    added += 1
                    page_all_dup = False

            # 如果本页所有岗位都是重复的，说明翻页已到尽头
            if page_all_dup and len(jobs) > 0:
                consecutive_empty_pages += 1
                print(f"全部重复（连续: {consecutive_empty_pages}/2），累计 {len(all_jobs)}")
                if consecutive_empty_pages >= 2:
                    print(f"\n[STOP] 连续 {consecutive_empty_pages} 页全重复，判定已抓取完毕")
                    break
            else:
                consecutive_empty_pages = 0
                print(f"+{added} 新增（本页 {len(jobs)} 条），累计 {len(all_jobs)}")

            # 每 5 页保存一次进度
            if page % 5 == 0:
                _save_jobs(all_jobs, output_file)
                print(f"  [✓ 已保存进度]")

    except KeyboardInterrupt:
        print(f"\n[中断] 用户取消，保存已抓取的 {len(all_jobs)} 个岗位...")
    finally:
        _save_jobs(all_jobs, output_file)

    print(f"-" * 60)
    print(f"完成！总计 {len(all_jobs)} 个岗位 → {output_file}")
    if failed_pages:
        print(f"失败页面（{len(failed_pages)} 页）: {failed_pages[:20]}")
    print(f"=" * 60)

    return len(all_jobs)


def _save_jobs(jobs: list[str], output_file: str):
    """将岗位列表保存为 JOB_MATCHER_FORMAT v1"""
    out_dir = os.path.dirname(os.path.abspath(output_file))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        timestamp = datetime.datetime.now().isoformat()
        f.write(f"# JOB_MATCHER_FORMAT v1 generated_at={timestamp} total_jobs={len(jobs)}\n")
        for i, job in enumerate(jobs, 1):
            f.write(f"--- JOB {i} ---\n{job}\n\n")


def _load_existing_jobs(filepath: str) -> list[str]:
    """从已有 jobs_raw.txt 加载岗位（用于断点续爬）"""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return []
    # 跳过版本头
    if content.startswith("# JOB_MATCHER_FORMAT"):
        content = content.split("\n", 1)[1] if "\n" in content else ""
    # 按 --- JOB N --- 分割
    parts = re.split(r"^--- JOB \d+ ---$", content, flags=re.MULTILINE)
    jobs = [p.strip() for p in parts if p.strip()]
    return jobs


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="批量抓取招聘网站岗位 JD（Career Copilot 辅助脚本）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", required=True,
                        help="翻页 URL 模板，用 {page} 作为页码占位符")
    parser.add_argument("--output", default="./jobs_raw.txt",
                        help="输出文件路径（默认 ./jobs_raw.txt）")
    parser.add_argument("--total-pages", type=int, default=60,
                        help="最大页数上限（默认 60，遇空页自动停止）")
    parser.add_argument("--start-page", type=int, default=1,
                        help="从第几页开始（默认 1）")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="每页等待秒数（默认 2.0）")
    parser.add_argument("--selector",
                        help="自定义 JS 提取表达式（返回 ||| 分隔文本）")
    parser.add_argument("--preset", choices=list(PRESETS.keys()),
                        help="使用内置选择器预设: bytedance, meituan, alibaba, generic")

    args = parser.parse_args()

    # 检查 catdesk
    if not os.path.exists(CATDESK):
        print(f"[ERROR] 找不到 catdesk: {CATDESK}")
        print("请确保 CatDesk 已安装")
        sys.exit(1)

    # URL 校验
    if "{page}" not in args.base_url:
        print("[ERROR] --base-url 必须包含 {page} 占位符")
        sys.exit(1)

    # 确定选择器
    selector = args.selector
    if not selector:
        if args.preset:
            selector = PRESETS[args.preset]
        else:
            # 自动检测
            if "bytedance" in args.base_url or "字节" in args.base_url:
                selector = PRESETS["bytedance"]
                print("[自动选择] bytedance 预设选择器")
            elif "meituan" in args.base_url:
                selector = PRESETS["meituan"]
                print("[自动选择] meituan 预设选择器")
            elif "alibaba" in args.base_url or "aligroup" in args.base_url:
                selector = PRESETS["alibaba"]
                print("[自动选择] alibaba 预设选择器")
            else:
                selector = PRESETS["generic"]
                print("[自动选择] generic 通用选择器")

    # 断点续爬
    prepended_jobs = None
    if args.start_page > 1 and os.path.exists(args.output):
        prepended_jobs = _load_existing_jobs(args.output)
        if prepended_jobs:
            print(f"[断点续爬] 从已有文件加载 {len(prepended_jobs)} 个岗位")

    total = fetch_all_jobs(
        base_url=args.base_url,
        total_pages=args.total_pages,
        output_file=args.output,
        start_page=args.start_page,
        delay=args.delay,
        selector=selector,
        prepended_jobs=prepended_jobs,
    )

    if total == 0:
        print("\n[提示] 未抓取到任何岗位，可能原因：")
        print("  1. 选择器不匹配 → 用 catdesk browser-action snapshot 查看页面结构")
        print("  2. 页面需要登录 → 先在浏览器中登录")
        print("  3. URL 模板不正确 → 确认 {page} 位置正确")
        sys.exit(1)


if __name__ == "__main__":
    main()
