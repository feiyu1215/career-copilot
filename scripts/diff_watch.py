#!/usr/bin/env python3
"""
diff_watch.py — 增量监测：检测新增岗位并只对新增部分评分

核心逻辑：
  1. 对比 baseline（上次抓取的 jobs_raw.txt）和 current（本次抓取的 jobs_raw.txt）
  2. 通过标题相似度匹配，找出"新增"岗位
  3. 对新增岗位单独跑 smart_score pipeline
  4. 将结果追加到历史记录中

使用方式：
    python3 diff_watch.py \
        --baseline /path/to/prev_jobs_raw.txt \
        --current /path/to/new_jobs_raw.txt \
        --profile /path/to/boundary_profile.json \
        --summary /path/to/candidate_summary.txt \
        --output /path/to/watch_results.json \
        [--history /path/to/watch_history.json] \
        [--stage1-model gpt-4o-mini] \
        [--stage2-model gpt-4.1-mini]

应用场景：
  - 配合 CatDesk automation，每周自动抓取 + diff + 评分 + 通知
  - Profile 生成一次后长期复用，只跟踪 JD 变化

输出：
  - watch_results.json: 本次新增岗位的评分结果
  - watch_history.json: 累计所有监测记录（追加模式）
"""

from __future__ import annotations

import json
import sys
import argparse
import asyncio
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

# 添加 scripts 目录到路径
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from smart_score import parse_jobs_raw, run_pipeline


def normalize_title(title: str) -> str:
    """标准化标题用于比较"""
    # 去掉城市、部门等后缀噪声
    import re
    # 去掉括号内容（如"(北京)"）
    title = re.sub(r'[（(][^)）]*[)）]', '', title)
    # 去掉多余空白
    title = re.sub(r'\s+', ' ', title).strip()
    return title.lower()


def title_similarity(t1: str, t2: str) -> float:
    """计算两个标题的相似度（0-1）"""
    n1 = normalize_title(t1)
    n2 = normalize_title(t2)
    return SequenceMatcher(None, n1, n2).ratio()


def find_new_jobs(baseline_jobs: list[dict], current_jobs: list[dict],
                  threshold: float = 0.85) -> list[dict]:
    """找出 current 中相对于 baseline 新增的岗位

    Args:
        baseline_jobs: 上次抓取的岗位列表
        current_jobs: 本次抓取的岗位列表
        threshold: 标题相似度阈值，高于此值认为是同一岗位

    Returns:
        新增的岗位列表
    """
    baseline_titles = [j["title"] for j in baseline_jobs]
    new_jobs = []

    for job in current_jobs:
        # 检查是否与任何 baseline 岗位匹配
        is_existing = False
        for bt in baseline_titles:
            if title_similarity(job["title"], bt) >= threshold:
                is_existing = True
                break

        if not is_existing:
            new_jobs.append(job)

    return new_jobs


def find_removed_jobs(baseline_jobs: list[dict], current_jobs: list[dict],
                      threshold: float = 0.85) -> list[dict]:
    """找出 baseline 中有但 current 中没有的岗位（已下架）"""
    current_titles = [j["title"] for j in current_jobs]
    removed = []

    for job in baseline_jobs:
        is_still_there = False
        for ct in current_titles:
            if title_similarity(job["title"], ct) >= threshold:
                is_still_there = True
                break

        if not is_still_there:
            removed.append(job)

    return removed


def write_temp_jobs_raw(jobs: list[dict], output_path: Path) -> None:
    """将岗位列表写回 jobs_raw.txt 格式（供 smart_score 消费）"""
    lines = ["# JOB_MATCHER_FORMAT v1"]
    for i, job in enumerate(jobs, 1):
        lines.append(f"--- JOB {i} ---")
        lines.append(job["full_text"])
    output_path.write_text("\n".join(lines), encoding="utf-8")


async def run(args):
    print("=" * 60)
    print("Diff Watch — 增量监测")
    print("=" * 60)

    # 显示上次运行时间（如果有历史记录）
    if args.history:
        history_path = Path(args.history)
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text(encoding="utf-8"))
                runs = history.get("runs", [])
                if runs:
                    last_date = runs[-1].get("date", "?")
                    from datetime import datetime as _dt
                    try:
                        days_ago = (datetime.now() - _dt.fromisoformat(last_date)).days
                        print(f"\n📅 上次监测: {last_date} ({days_ago} 天前)")
                    except (ValueError, TypeError):
                        print(f"\n📅 上次监测: {last_date}")
                else:
                    print(f"\n📅 首次运行，建立 baseline...")
            except (json.JSONDecodeError, KeyError):
                pass

    # 解析 baseline 和 current
    print(f"\n解析 baseline: {args.baseline}")
    baseline_jobs = parse_jobs_raw(args.baseline)
    print(f"  岗位数: {len(baseline_jobs)}")

    print(f"\n解析 current: {args.current}")
    current_jobs = parse_jobs_raw(args.current)
    print(f"  岗位数: {len(current_jobs)}")

    # 找差异
    new_jobs = find_new_jobs(baseline_jobs, current_jobs)
    removed_jobs = find_removed_jobs(baseline_jobs, current_jobs)

    print(f"\n差异分析:")
    print(f"  新增岗位: {len(new_jobs)}")
    print(f"  下架岗位: {len(removed_jobs)}")
    print(f"  不变岗位: {len(current_jobs) - len(new_jobs)}")

    if new_jobs:
        print(f"\n新增岗位标题:")
        for j in new_jobs[:15]:
            print(f"  + {j['title']}")
        if len(new_jobs) > 15:
            print(f"  ... 还有 {len(new_jobs) - 15} 个")

    if removed_jobs:
        print(f"\n下架岗位标题:")
        for j in removed_jobs[:10]:
            print(f"  - {j['title']}")

    # 如果没有新增，直接输出
    if not new_jobs:
        output = {
            "generated_at": datetime.now().isoformat(),
            "watch_type": "no_change",
            "baseline_count": len(baseline_jobs),
            "current_count": len(current_jobs),
            "new_count": 0,
            "removed_count": len(removed_jobs),
            "removed_titles": [j["title"] for j in removed_jobs],
            "message": "没有新增岗位，无需评分。"
        }
        Path(args.output).write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✓ 无新增岗位，结果已保存: {args.output}")
        return output

    # 对新增岗位跑评分 pipeline
    print(f"\n{'='*60}")
    print(f"对 {len(new_jobs)} 个新增岗位进行评分...")
    print(f"{'='*60}")

    # 写临时 jobs_raw
    temp_jobs_path = Path(args.output).parent / "_temp_new_jobs_raw.txt"
    write_temp_jobs_raw(new_jobs, temp_jobs_path)

    # 构造 smart_score 的 args
    class ScoreArgs:
        jobs = str(temp_jobs_path)
        profile = args.profile
        summary = args.summary
        output = str(Path(args.output).parent / "_temp_scored.json")
        top_k = min(len(new_jobs), 50)  # 新增岗位通常不多，全量精排
        stage1_model = args.stage1_model
        stage2_model = args.stage2_model
        concurrency = 5
        provider = getattr(args, 'provider', None)

    score_results = await run_pipeline(ScoreArgs())

    # 清理临时文件
    temp_jobs_path.unlink(missing_ok=True)
    Path(ScoreArgs.output).unlink(missing_ok=True)

    # 组装 watch 输出
    output = {
        "generated_at": datetime.now().isoformat(),
        "watch_type": "new_jobs_found",
        "baseline_count": len(baseline_jobs),
        "current_count": len(current_jobs),
        "new_count": len(new_jobs),
        "removed_count": len(removed_jobs),
        "removed_titles": [j["title"] for j in removed_jobs[:20]],
        "new_jobs_scored": score_results.get("recommendations", {}),
        "new_jobs_summary": score_results.get("summary", {}),
    }

    # 保存结果
    Path(args.output).write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ 监测结果已保存: {args.output}")

    # 追加到 history
    if args.history:
        history_path = Path(args.history)
        if history_path.exists():
            history = json.loads(history_path.read_text(encoding="utf-8"))
        else:
            history = {"runs": []}

        history["runs"].append({
            "date": datetime.now().isoformat()[:10],
            "new_count": len(new_jobs),
            "removed_count": len(removed_jobs),
            "tier_a_new": score_results.get("summary", {}).get("tier_A", 0),
            "tier_b_new": score_results.get("summary", {}).get("tier_B", 0),
        })

        history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ 历史记录已更新: {history_path}")

    # 打印通知摘要
    tier_a_new = score_results.get("summary", {}).get("tier_A", 0)
    tier_b_new = score_results.get("summary", {}).get("tier_B", 0)

    print(f"\n{'='*60}")
    print("📢 监测摘要")
    print(f"{'='*60}")
    print(f"  新增 {len(new_jobs)} 个岗位，其中：")
    print(f"    🟢 A档（强烈推荐）: {tier_a_new}")
    print(f"    🟡 B档（可以考虑）: {tier_b_new}")
    print(f"    ⚪ C档（迁移较远）: {len(new_jobs) - tier_a_new - tier_b_new}")

    if tier_a_new > 0:
        a_jobs = score_results.get("recommendations", {}).get("tier_A", [])
        print(f"\n  新增 A 档岗位：")
        for j in a_jobs:
            print(f"    ★ [{j.get('score', 0):.0f}] {j.get('title', '?')}")

    return output


def main():
    parser = argparse.ArgumentParser(description="增量监测：检测新增岗位并评分")
    parser.add_argument("--baseline", required=True, help="上次的 jobs_raw.txt")
    parser.add_argument("--current", required=True, help="本次的 jobs_raw.txt")
    parser.add_argument("--profile", required=True, help="boundary_profile.json 路径")
    parser.add_argument("--summary", required=True, help="candidate_summary.txt 路径")
    parser.add_argument("--output", required=True, help="输出 watch_results.json 路径")
    parser.add_argument("--history", default=None, help="累计历史记录 JSON 路径（可选）")
    parser.add_argument("--stage1-model", default="gpt-4o-mini", help="Stage 1 模型")
    parser.add_argument("--stage2-model", default="gpt-4.1-mini", help="Stage 2 模型")
    parser.add_argument("--provider", default=None, help="LLM provider: internal 或 external（默认读环境变量 LLM_PROVIDER）")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
