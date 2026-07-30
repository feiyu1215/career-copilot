#!/usr/bin/env python3
"""N2 多 portal 批处理 Orchestrator（多门户批处理抓取）。

按 config/portals.yaml 遍历 enabled 门户，复用现有 fetch_*.py 抓取，
合并 + 去重（+ 规范化）为一份 v1 文本（jobs_raw.txt 格式）。默认串行、opt-in（仅显式运行时触发），
不内嵌评分（评分是 smart_score 的独立步骤）。

设计原则：薄封装，不迁移现有 fetcher 运行时；后端失败（CLI 未装 / 未登录 /
缺参数）优雅跳过，不中断整体。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from job_common import (  # noqa: E402
    load_portals,
    enabled_portals,
    SeenJobs,
    load_jobs_format,
    save_jobs_format,
    quality_gate,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _backend_command(kind, portal, query, pages, max_jobs, out_path):
    """按门户 kind 构造后端子进程命令；缺必需参数返回 None（调用方跳过）。"""
    backend = portal.get("backend")
    if not backend:
        return None
    base = [sys.executable, os.path.join(SCRIPT_DIR, backend)]
    if kind == "boss":
        return base + ["search", "--query", query, "--output", out_path,
                       "--pages", str(pages), "--max-jobs", str(max_jobs)]
    if kind == "linkedin":
        return base + ["--query", query, "--output", out_path,
                       "--pages", str(pages), "--mode", "auto"]
    if kind == "shixiseng":
        return base + ["--query", query, "--output", out_path, "--pages", str(pages)]
    if kind == "nowcoder":
        return base + ["--query", query, "--output", out_path, "--pages", str(pages), "--max-jobs", str(max_jobs)]
    if kind == "catdesk":
        base_url = portal.get("base_url")
        preset = portal.get("preset")
        if not (base_url and preset):
            return None
        return base + ["--base-url", base_url, "--preset", preset,
                       "--output", out_path, "--total-pages", str(pages)]
    if kind == "feishu":
        url = portal.get("url")
        if not url:
            return None
        return base + ["--url", url, "--output", out_path]
    return None


_URL_RE = re.compile(r"\[URL\](.*?)\[/URL\]", re.S)


def _normalize_job_dict(d: dict) -> dict:
    """把后端 JSON 岗位字典规整为统一结构，并构造 v1 文本块。"""
    title = (d.get("title") or "").strip()
    url = (d.get("url") or "").strip()
    company = (d.get("company") or "").strip()
    location = (d.get("location") or "").strip()
    jd = (d.get("description") or d.get("jd") or d.get("raw")
          or d.get("summary") or "").strip()
    block = title
    if url:
        block += f"\n[URL]{url}[/URL]"
    extra = []
    if company:
        extra.append(f"Company: {company}")
    if location:
        extra.append(f"Location: {location}")
    if jd:
        extra.append(jd)
    if extra:
        block += "\n" + "\n".join(extra)
    return {"title": title, "url": url, "company": company,
            "location": location, "jd": jd, "_block": block}


def _block_to_job(block: str) -> dict:
    """把 v1 文本块解析为统一结构。

    文本块由 _normalize_job_dict 构造，约定：
        - 首行非空行：岗位标题
        - 含 [URL]...[/URL] 或裸 http(s) 链接的行：URL
        - `Company: <公司>` 行：公司（大小写不敏感）
        - `Location: <地点>` 行：地点
        - 其余：JD 正文
    反向解析出 company/location，使文本后端的复合身份去重（company+title+location）
    也能生效，而不是退化成仅 URL 去重（否则相同 title 不同公司会被错误合并）。
    """
    text = block.strip()
    title = ""
    url = ""
    company = ""
    location = ""
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("company:"):
            company = s[len("company:"):].strip()
            continue
        if low.startswith("location:"):
            location = s[len("location:"):].strip()
            continue
        m = _URL_RE.search(s)
        if m and not url:
            url = m.group(1).strip()
            continue
        if not title:
            title = s
    # 兜底：极简块（无结构化行）至少把首行当 title，避免拿到空标题
    if not title:
        for ln in text.split("\n"):
            if ln.strip():
                title = ln.strip()
                break
    return {"title": title, "url": url, "company": company,
            "location": location, "jd": text, "_block": text}


def _read_backend_output(path: str) -> list[dict]:
    """格式无关地读取后端输出：优先按 JSON（boss），失败回退 v1 文本。

    返回统一岗位字典列表（含内部字段 _block）。读取失败返回空列表，
    调用方按「无结果」处理，不会让单个门户的格式问题中断整体。
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, ValueError):
        # 非 JSON：按 v1 文本块解析（linkedin/shixiseng/catdesk/feishu 均输出此格式）
        blocks = load_jobs_format(path)
        if not blocks:
            # 兜底：文件整体作为单个岗位块（无 --- JOB N --- 分隔时也别丢）
            raw = p.read_text(encoding="utf-8").strip()
            if raw:
                blocks = [raw]
        return [_block_to_job(b) for b in blocks]
    if isinstance(data, dict):
        data = data.get("jobs", [])
    if not isinstance(data, list):
        # 后端返回了无法识别的结构（如 {"error": ...} 或被意外包装），
        # 不要静默当作「无结果」跳过——显式告警，避免掩盖后端故障。
        print(f"[batch_fetch] 后端输出无法识别（期望 list 或 {{jobs:[...]}}，"
              f"实际为 {type(data).__name__}），跳过该门户", file=sys.stderr)
        return []
    out = []
    for item in data:
        if isinstance(item, dict):
            out.append(_normalize_job_dict(item))
        elif isinstance(item, str):
            out.append(_block_to_job(item))
    return out


def _run_one(portal_name, kind, portal, query, pages, max_jobs, tmp_dir):
    """抓取单个门户；返回 (name, jobs_or_None, error_or_None)。"""
    out_path = os.path.join(tmp_dir, f"{portal_name}.json")
    cmd = _backend_command(kind, portal, query, pages, max_jobs, out_path)
    if cmd is None:
        return portal_name, None, "缺少必需参数（catdesk 需 base_url+preset；feishu 需 url），跳过"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as exc:  # noqa: BLE001
        return portal_name, None, f"调用异常：{exc}"
    if proc.returncode != 0:
        return portal_name, None, f"后端退出码 {proc.returncode}（多半 CLI 未装/未登录），跳过"
    try:
        jobs = _read_backend_output(out_path)
    except Exception as exc:  # noqa: BLE001
        return portal_name, None, f"读取输出失败：{exc}"
    return portal_name, jobs, None


def batch_fetch(query, portals_path, output, pages=3, max_jobs=0, concurrency=1,
                seen_path=None, quality_gate_enabled=True, quality_report=None):
    """遍历 enabled 门户并合并去重，再经 Phase 4.3 质量守门，返回合并后的岗位列表。

    seen_path: 跨运行持久去重的存储路径（必须稳定！默认 data/seen_jobs.json）。
    放临时目录会让「跨运行持久」变成空话。
    quality_gate_enabled: 是否启用 Phase 4.3 逐条准入校验（默认开）。
    quality_report: 若给定路径，写出守门报告 JSON（accepted/rejected/stats）。
    """
    if seen_path is None:
        seen_path = os.path.join(SCRIPT_DIR, "..", "data", "seen_jobs.json")
    portals = load_portals(portals_path)
    enabled = enabled_portals(portals)
    if not enabled:
        print("[batch_fetch] 没有 enabled 门户", file=sys.stderr)
        return []
    pdict = portals.get("portals", {}) or {}
    tasks = [(n, pdict[n].get("kind", n), pdict[n]) for n in enabled]
    jobs: list[dict] = []
    # 去重表落在稳定路径，真正跨运行持久；不能放进临时目录。
    seen = SeenJobs.load(seen_path)
    with tempfile.TemporaryDirectory() as tmp:
        if concurrency and concurrency > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as ex:
                futures = {ex.submit(_run_one, n, k, p, query, pages, max_jobs, tmp): n
                           for n, k, p in tasks}
                results = [f.result() for f in as_completed(futures)]
        else:
            results = [_run_one(n, k, p, query, pages, max_jobs, tmp) for n, k, p in tasks]
        for name, data, err in results:
            if err:
                print(f"[batch_fetch] 门户 {name}: {err}", file=sys.stderr)
                continue
            if not data:
                print(f"[batch_fetch] 门户 {name}: 无结果", file=sys.stderr)
                continue
            added = 0
            for j in data:
                # 复合身份键：来源(name) + 公司 + 岗位 + 地点，避免不同岗位被错误合并
                if seen.seen(j.get("url", ""), j.get("title", ""),
                             j.get("company", ""), name, j.get("location", "")):
                    continue
                seen.add(j.get("url", ""), j.get("title", ""),
                         j.get("company", ""), name, j.get("location", ""))
                jobs.append(j)
                added += 1
            print(f"[batch_fetch] 门户 {name}: 合并 {added} 条（原始 {len(data)}）", file=sys.stderr)
    seen.save()

    # Phase 4.3 质量守门：逐条准入校验，拦截字段缺失/占位/损坏 URL 的废卡
    if quality_gate_enabled:
        g = quality_gate(jobs)
        jobs = g["accepted"]
        st = g["stats"]
        print(f"[batch_fetch] 质量守门：通过 {st['accepted']} / 拦截 {st['rejected']}"
              f"（接受率 {st['accept_rate']:.0%}）", file=sys.stderr)
        for code, cnt in st["by_code"].items():
            print(f"[batch_fetch]   拦截项 {code}: {cnt} 条", file=sys.stderr)
        if st["warnings"]:
            wsum = sum(st["warnings"].values())
            print(f"[batch_fetch]   软警告（未拦截）: {wsum} 条 {st['warnings']}",
                  file=sys.stderr)
        if quality_report:
            _write_quality_report(quality_report, g, query)

    # 写出 v1 文本（jobs_raw.txt 格式），下游 smart_score / diff_watch 可直接消费
    blocks = [j["_block"] for j in jobs if j.get("_block")]
    try:
        save_jobs_format(blocks, output)
    except Exception as exc:  # noqa: BLE001
        print(f"[batch_fetch] 写出失败：{exc}", file=sys.stderr)
    clean = [{k: v for k, v in j.items() if k != "_block"} for j in jobs]
    print(f"[batch_fetch] 合并完成：共 {len(clean)} 条 → {output}", file=sys.stderr)
    return clean


def _write_quality_report(path: str, gate_result: dict, query: str = "") -> None:
    """把质量守门报告写成 JSON（供 CI / 复盘读取）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps({
            "query": query,
            "stats": gate_result["stats"],
            "rejected": [{"reason_codes": [r["code"] for r in item["reasons"]],
                          "record": {k: v for k, v in item["record"].items()
                                     if k != "_block"}}
                         for item in gate_result["rejected"]],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[batch_fetch] 质量守门报告 → {path}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[batch_fetch] 写出守门报告失败：{exc}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description="多门户批处理抓取（N2）：按 portals.yaml 合并去重")
    ap.add_argument("--query", required=True, help="岗位/方向关键词")
    ap.add_argument("--portals", default=os.path.join(SCRIPT_DIR, "..", "config", "portals.yaml"))
    ap.add_argument("--output", default="batch_jobs.txt")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--max-jobs", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=1, help="并发抓取门户数（默认 1，串行）")
    ap.add_argument("--seen", default=os.path.join(SCRIPT_DIR, "..", "data", "seen_jobs.json"),
                    help="跨运行持久去重存储路径（默认 data/seen_jobs.json，勿放临时目录）")
    ap.add_argument("--no-quality-gate", action="store_true",
                    help="关闭 Phase 4.3 质量守门（放行所有去重后的记录，仅调试用）")
    ap.add_argument("--quality-report", default=None,
                    help="写出质量守门报告 JSON 的路径（含 accepted/rejected/stats）")
    args = ap.parse_args(argv)
    batch_fetch(args.query, args.portals, args.output, args.pages, args.max_jobs,
                args.concurrency, args.seen,
                quality_gate_enabled=not args.no_quality_gate,
                quality_report=args.quality_report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
