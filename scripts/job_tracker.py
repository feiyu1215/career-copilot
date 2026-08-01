#!/usr/bin/env python3
"""Job tracker — 申请/结果生命周期闭环 + 反馈回路。

career-copilot P5 补完项。与 career_log.py（事件日志）互补：career_log 记「发生了什么」，
本模块记「每条具体申请走到哪、结果如何」，并据此给出反馈（哪个 tier / 来源转化最好）。

设计要点（来自升级计划 P5）：
- 存储落在 `notes/`（不新建云同步）；默认 `notes/job-tracker.json`，可用 --store / 环境变量覆盖。
- 纯标准库，离线可用，无网络依赖。
- 生命周期：planned -> applied -> screening -> interview -> offer/rejected/withdrawn(终态)。
- 每次状态变更写入 history，终端状态推导 outcome。
- stats 子命令即「反馈回路」：按 tier / 来源汇总转化漏斗。

典型用法：
    python scripts/job_tracker.py init
    python scripts/job_tracker.py add --company ACME --role "MLE" --source boss \\
        --tier A --score 82 --reasons "匹配K8s,论文相关" --risks "缺Go经验"
    python scripts/job_tracker.py apply --id app_xxx
    python scripts/job_tracker.py update --id app_xxx --status interview --note "一面已过"
    python scripts/job_tracker.py stats
    python scripts/job_tracker.py export
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# 默认存储：<skill_root>/notes/job-tracker.json（不随 cwd 漂移）
DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "notes",
    "job-tracker.json",
)

VALID_STATUSES = {
    "planned",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
}
TERMINAL = {"offer", "rejected", "withdrawn"}
TIER_ORDER = ["A", "B", "C", "D"]


class JobTrackerError(Exception):
    """CLI 可控错误：打印到 stderr 并以非零码退出。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(store: str) -> dict:
    if not os.path.exists(store):
        return {"applications": []}
    try:
        with open(store, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise JobTrackerError(f"无法读取存储 {store}: {exc}") from exc
    if not isinstance(data, dict) or "applications" not in data:
        data = {"applications": []}
    return data


def _save(store: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(store)), exist_ok=True)
    tmp = store + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, store)


def _find(data: dict, ident: str | None, company: str | None, role: str | None):
    apps = data["applications"]
    if ident:
        for a in apps:
            if a["id"] == ident:
                return a
        raise JobTrackerError(f"找不到 id={ident} 的申请")
    if company or role:
        matches = [
            a
            for a in apps
            if (not company or company.lower() in a["company"].lower())
            and (not role or role.lower() in a["role"].lower())
        ]
        if not matches:
            raise JobTrackerError("没有匹配 company/role 的申请")
        return matches[-1]  # 最近一条
    raise JobTrackerError("需要 --id 或 --company/--role 来定位申请")


def _new_id() -> str:
    return "app_" + uuid.uuid4().hex[:12]


def _notify_transition(rec: dict, webhook: str | None) -> None:
    """B2：状态变为 applied/interview/offer 时推送企业微信（webhook 空则跳过）。"""
    if not webhook:
        return
    if rec.get("status") not in {"applied", "interview", "offer"}:
        return
    try:
        from notify_wecom import notify
        notify("job_tracker", f"{rec['company']} / {rec['role']} → {rec['status']}", webhook)
    except Exception:
        pass


def cmd_init(args, store: str) -> int:
    data = _load(store)
    _save(store, data)
    print(f"job-tracker store ready: {store}")
    return 0


def cmd_add(args, store: str) -> int:
    data = _load(store)
    reasons = [r.strip() for r in (args.reasons or "").split(",") if r.strip()]
    risks = [r.strip() for r in (args.risks or "").split(",") if r.strip()]
    rec = {
        "id": _new_id(),
        "company": args.company,
        "role": args.role,
        "url": args.url or "",
        "source": args.source or "unknown",
        "tier": args.tier or "",
        "score": args.score if args.score is not None else None,
        "top_reasons": reasons,
        "top_risks": risks,
        "status": "planned",
        "applied_at": None,
        "created_at": _now(),
        "history": [{"at": _now(), "status": "planned", "note": "记录建档"}],
        "outcome": None,
    }
    data["applications"].append(rec)
    _save(store, data)
    print(f"已建档 {rec['id']}: {rec['company']} / {rec['role']} (tier={rec['tier']}, score={rec['score']})")
    return 0


def cmd_apply(args, store: str) -> int:
    data = _load(store)
    rec = _find(data, args.id, args.company, args.role)
    if rec["status"] != "planned":
        raise JobTrackerError(f"id={rec['id']} 当前状态={rec['status']}，不是 planned，无法标记投递")
    rec["status"] = "applied"
    rec["applied_at"] = _now()
    rec["history"].append({"at": _now(), "status": "applied", "note": args.note or "已投递"})
    _save(store, data)
    print(f"已标记投递 {rec['id']}: {rec['company']} / {rec['role']}")
    _notify_transition(rec, args.wecom or os.environ.get("WECOM_WEBHOOK"))
    return 0


def cmd_update(args, store: str) -> int:
    if args.status not in VALID_STATUSES:
        raise JobTrackerError(f"非法状态 {args.status!r}；合法值: {sorted(VALID_STATUSES)}")
    data = _load(store)
    rec = _find(data, args.id, args.company, args.role)
    if rec["status"] == args.status:
        raise JobTrackerError(f"id={rec['id']} 已是 {args.status}，无变更")
    if rec["status"] in TERMINAL:
        raise JobTrackerError(f"id={rec['id']} 已终态({rec['status']})，不能再变更")
    if rec["status"] == "planned" and args.status in {"offer", "interview", "screening"}:
        print(f"[warn] id={rec['id']} 还标记为 planned 却跳到 {args.status}；建议先 apply", file=sys.stderr)
    rec["status"] = args.status
    if args.status == "applied" and not rec["applied_at"]:
        rec["applied_at"] = _now()
    if args.status in TERMINAL:
        rec["outcome"] = args.status
    rec["history"].append({"at": _now(), "status": args.status, "note": args.note or ""})
    _save(store, data)
    print(f"已更新 {rec['id']}: -> {args.status}" + (f" (outcome={rec['outcome']})" if rec["outcome"] else ""))
    _notify_transition(rec, args.wecom or os.environ.get("WECOM_WEBHOOK"))
    return 0


def _fmt_row(rec) -> str:
    return (
        f"{rec['id']}\t{rec['company']}\t{rec['role']}\t"
        f"{rec.get('source','')}\t{rec.get('tier','')}\t{rec.get('status','')}"
    )


def cmd_list(args, store: str) -> int:
    data = _load(store)
    apps = data["applications"]
    if args.status:
        apps = [a for a in apps if a["status"] == args.status]
    if args.source:
        apps = [a for a in apps if a.get("source", "").lower() == args.source.lower()]
    if args.company:
        apps = [a for a in apps if args.company.lower() in a["company"].lower()]
    apps = apps[-args.limit:] if args.limit else apps
    if not apps:
        print("(无匹配申请)")
        return 0
    header = "id\tcompany\trole\tsource\ttier\tstatus"
    print(header)
    for a in apps:
        print(_fmt_row(a))
    return 0


def cmd_show(args, store: str) -> int:
    data = _load(store)
    rec = _find(data, args.id, args.company, args.role)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


def cmd_stats(args, store: str) -> int:
    data = _load(store)
    apps = data["applications"]
    total = len(apps)
    if total == 0:
        print("(无数据)")
        return 0

    # 漏斗
    funnel: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    for a in apps:
        funnel[a["status"]] = funnel.get(a["status"], 0) + 1

    # 终态 outcome 计数
    outcomes: dict[str, int] = {}
    for a in apps:
        oc = a.get("outcome")
        if oc:
            outcomes[oc] = outcomes.get(oc, 0) + 1

    # 按 tier 转化（offer / (interview+offer)）
    by_tier: dict[str, dict[str, int]] = {t: {"n": 0, "reached": 0, "interview": 0, "offer": 0} for t in TIER_ORDER}
    for a in apps:
        t = a.get("tier") or "?"
        if t not in by_tier:
            by_tier[t] = {"n": 0, "reached": 0, "interview": 0, "offer": 0}
        by_tier[t]["n"] += 1
        # 「曾投递」以 applied_at 时间戳为准（apply/update 时写入），是累计口径；
        # 与上方漏斗的「applied=当前处于 applied 状态」区分开，避免误读。
        if a.get("applied_at"):
            by_tier[t]["reached"] += 1
        if a["status"] in {"interview", "offer"}:
            by_tier[t]["interview"] += 1
        if a["status"] == "offer":
            by_tier[t]["offer"] += 1

    # 按来源
    by_source: dict[str, dict[str, int]] = {}
    for a in apps:
        s = a.get("source") or "unknown"
        d = by_source.setdefault(s, {"n": 0, "offer": 0, "rejected": 0})
        d["n"] += 1
        if a["status"] == "offer":
            d["offer"] += 1
        if a["status"] == "rejected":
            d["rejected"] += 1

    print(f"# Job tracker 统计 (共 {total} 条申请)\n")
    print("## 状态漏斗")
    for s in VALID_STATUSES:
        print(f"- {s}: {funnel[s]}")
    print("\n## 终态结果")
    for k in ("offer", "rejected", "withdrawn"):
        print(f"- {k}: {outcomes.get(k, 0)}")
    print("\n## 按 tier 转化 (offer / 进入面试 / 曾投递 / 总数)")
    for t in by_tier:
        d = by_tier[t]
        rate = (d["offer"] / d["n"] * 100) if d["n"] else 0
        print(f"- {t}: offer={d['offer']} interview={d['interview']} 曾投递={d['reached']} n={d['n']} | offer率={rate:.0f}%")
    print("\n## 按来源")
    for s in sorted(by_source):
        d = by_source[s]
        print(f"- {s}: n={d['n']} offer={d['offer']} rejected={d['rejected']}")

    # 反馈回路提示
    best = max(by_tier, key=lambda t: by_tier[t]["offer"])
    print(f"\n> 反馈回路：tier={best} 当前 offer 最多 ({by_tier[best]['offer']})；"
          "低 tier 长期零转化时，重新审视打分权重或收紧投放门槛。")
    return 0


def cmd_export(args, store: str) -> int:
    data = _load(store)
    apps = data["applications"]
    lines = ["# Job Tracker 汇总", ""]
    lines.append(f"> 生成时间(UTC): {_now()} — 共 {len(apps)} 条申请\n")
    lines.append("| id | company | role | source | tier | score | status | applied | outcome |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for a in apps:
        lines.append(
            f"| {a['id']} | {a['company']} | {a['role']} | {a.get('source','')} | "
            f"{a.get('tier','')} | {a.get('score','')} | {a['status']} | "
            f"{a.get('applied_at') or '-'} | {a.get('outcome') or '-'} |"
        )
    md = "\n".join(lines) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"已导出: {args.out}")
    else:
        out = os.path.join(os.path.dirname(os.path.abspath(store)), "job-tracker.md")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"已导出: {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="career-copilot job tracker (P5)")
    p.add_argument("--store", default=os.environ.get("JOB_TRACKER_STORE", DEFAULT_STORE),
                   help="存储路径 (默认 <skill>/notes/job-tracker.json)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化存储")

    a = sub.add_parser("add", help="建档一条申请（planned）")
    a.add_argument("--company", required=True)
    a.add_argument("--role", required=True)
    a.add_argument("--url", default="")
    a.add_argument("--source", default="unknown", help="boss/linkedin/referral/...")
    a.add_argument("--tier", default="")
    a.add_argument("--score", type=float, default=None)
    a.add_argument("--reasons", default="", help="逗号分隔")
    a.add_argument("--risks", default="", help="逗号分隔")

    ap = sub.add_parser("apply", help="标记已投递")
    ap.add_argument("--id")
    ap.add_argument("--company")
    ap.add_argument("--role")
    ap.add_argument("--note", default="")
    ap.add_argument("--wecom", default=None, help="企业微信群机器人 key（B2）；空则跳过")

    u = sub.add_parser("update", help="更新状态/结果")
    u.add_argument("--id")
    u.add_argument("--company")
    u.add_argument("--role")
    u.add_argument("--status", required=True)
    u.add_argument("--note", default="")
    u.add_argument("--wecom", default=None, help="企业微信群机器人 key（B2）；空则跳过")

    list_parser = sub.add_parser("list", help="列出申请")
    list_parser.add_argument("--status")
    list_parser.add_argument("--source")
    list_parser.add_argument("--company")
    list_parser.add_argument("--limit", type=int, default=0)

    sh = sub.add_parser("show", help="查看单条详情")
    sh.add_argument("--id")
    sh.add_argument("--company")
    sh.add_argument("--role")

    sub.add_parser("stats", help="反馈回路统计")
    ex = sub.add_parser("export", help="导出 markdown 汇总")
    ex.add_argument("--out", default=None)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    store = os.path.abspath(args.store)
    handlers = {
        "init": cmd_init,
        "add": cmd_add,
        "apply": cmd_apply,
        "update": cmd_update,
        "list": cmd_list,
        "show": cmd_show,
        "stats": cmd_stats,
        "export": cmd_export,
    }
    try:
        return handlers[args.cmd](args, store)
    except JobTrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
