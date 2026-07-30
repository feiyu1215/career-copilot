"""fetch_jobs_linkedin.py — LinkedIn 多门户后端。

策略（与用户确认的 A 方案一致）：外部 CLI 优先 + WebSearch 兜底。
- 默认 --mode auto：检测到外部 linkedin-search CLI 即用；否则生成 WebSearch 任务，
  由 agent 执行 WebSearch+WebFetch 后 --ingest 回灌。
- 真实抓取依赖「已登录会话 / 外部 CLI」，脚本本身不伪造 LinkedIn 爬虫（踩 ToS 且脆弱）。
- 输出 JOB_MATCHER_FORMAT v1，下游 smart_score 直接消费。

用法：
  python scripts/fetch_jobs_linkedin.py --query "推荐算法" --city "上海" --mode auto
  python scripts/fetch_jobs_linkedin.py --ingest linkedin_websearch_results.json --output jobs_raw.txt
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from job_common import (  # noqa: E402
    build_linkedin_websearch_queries,
    save_jobs_format,
)


def _cli_available(cli_cmd: str) -> bool:
    return shutil.which(cli_cmd) is not None


def _parse_cli_output(stdout: str) -> list[dict]:
    """解析外部 linkedin-search CLI 输出（宽松：JSON 数组或 NDJSON）。"""
    stdout = stdout.strip()
    if not stdout:
        return []
    try:
        data = json.loads(stdout)
        return data if isinstance(data, list) else [data]
    except Exception:
        out = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


def _run_cli(cli_cmd: str, query: str, city: str, pages: int) -> list[dict]:
    """shell out 到外部 linkedin-search CLI（bun cli.ts 风格）。"""
    cmd = [cli_cmd, "--query", query]
    if city:
        cmd += ["--city", city]
    cmd += ["--pages", str(pages), "--json"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError(f"linkedin CLI 失败: {res.stderr[:200]}")
    return _parse_cli_output(res.stdout)


def _job_to_block(job: dict) -> str:
    """dict -> v1 单岗位文本块。"""
    lines = []
    url = job.get("url", "")
    if url:
        lines.append(f"[URL]{url}[/URL]")
    lines.append(job.get("title", "未知岗位"))
    lines.append(job.get("company", ""))
    if job.get("salary"):
        lines.append(job.get("salary", ""))
    if job.get("location"):
        lines.append(job.get("location", ""))
    if job.get("description"):
        lines.append(job.get("description", ""))
    return "\n".join(x for x in lines if x != "")


def _emit_websearch_task(query: str, city: str, track: str, output_dir: Path) -> Path:
    """无 CLI 时生成 WebSearch 任务文件，供 agent 执行后 --ingest。"""
    queries = build_linkedin_websearch_queries(query, city, track)
    task = {
        "portal": "linkedin",
        "instructions": (
            "对每条 query 执行 WebSearch，打开结果中的 linkedin.com/jobs 链接用 WebFetch 取 JD，"
            "整理为 [{url,title,company,salary,location,description}] 写入本目录 "
            "linkedin_websearch_results.json，再运行 --ingest 回灌。"
        ),
        "queries": queries,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "linkedin_websearch_task.json"
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    md = output_dir / "linkedin_websearch_task.md"
    md.write_text(
        f"# LinkedIn WebSearch 兜底任务\n\n{ task['instructions'] }\n\n"
        + "\n".join(f"- {q}" for q in queries) + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LinkedIn 多门户后端（CLI 优先 + WebSearch 兜底）")
    ap.add_argument("--query", required=True, help="岗位/方向关键词")
    ap.add_argument("--city", default="", help="城市")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--mode", choices=["auto", "cli", "websearch"], default="auto")
    ap.add_argument("--cli-cmd", default="linkedin-search")
    ap.add_argument("--track", choices=["intern", "job"], default="job")
    ap.add_argument("--output", default="jobs_raw.txt")
    ap.add_argument("--ingest", default="", help="回灌 agent WebSearch 结果 JSON")
    ap.add_argument("--task-dir", default=".", help="WebSearch 任务文件输出目录")
    args = ap.parse_args(argv)

    if args.ingest:
        p = Path(args.ingest)
        if not p.exists():
            print(f"[ERR] ingest 文件不存在: {p}", file=sys.stderr)
            return 2
        records = json.loads(p.read_text(encoding="utf-8"))
        blocks = [_job_to_block(r) for r in records]
        n = save_jobs_format(blocks, args.output, datetime.now().isoformat(timespec="seconds"))
        print(f"[OK] LinkedIn ingest {n} 条 -> {args.output}")
        return 0

    if args.mode in ("cli", "auto") and _cli_available(args.cli_cmd):
        try:
            records = _run_cli(args.cli_cmd, args.query, args.city, args.pages)
            blocks = [_job_to_block(r) for r in records]
            n = save_jobs_format(blocks, args.output, datetime.now().isoformat(timespec="seconds"))
            print(f"[OK] LinkedIn CLI {n} 条 -> {args.output}")
            return 0
        except Exception as e:
            if args.mode == "cli":
                print(f"[ERR] LinkedIn CLI 失败: {e}", file=sys.stderr)
                return 1
            print(f"[WARN] LinkedIn CLI 不可用({e})，转 WebSearch 兜底")

    # WebSearch 兜底：生成任务，不伪造抓取
    task_path = _emit_websearch_task(args.query, args.city, args.track, Path(args.task_dir))
    print(
        f"[INFO] 未检测到外部 LinkedIn CLI，已生成 WebSearch 兜底任务:\n"
        f"       {task_path}\n"
        f"       由 agent 执行 WebSearch+WebFetch 后运行:\n"
        f"       python scripts/fetch_jobs_linkedin.py --ingest <results.json> --output {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
