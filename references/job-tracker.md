# Job Tracker（P5）

每条**具体申请**的生命周期闭环 + 反馈回路。与 `career_log.py`（职业事件日志）互补：
career_log 记「发生了什么事件」，本模块记「每条申请走到哪、结果如何」，并据此给出
投放策略反馈（哪个 tier / 来源转化最好）。

- 存储：`notes/job-tracker.json`（**不进云同步**，纯本地）。可用 `--store <path>` 或
  环境变量 `JOB_TRACKER_STORE` 覆盖。
- 依赖：纯标准库，离线可用，无网络。

## 生命周期

```
planned → applied → screening → interview → offer / rejected / withdrawn(终态)
```

- `planned`：建档，记录 smart_score 的 tier/score/理由/风险快照（来自 Tier2 或 smart_score 输出）。
- `applied`：已投递（设 `applied_at`）。
- `screening` / `interview`：漏斗中段。
- 终态 `offer` / `rejected` / `withdrawn`：推导 `outcome`，不再可变更。

每次状态变更写入 `history`，终端状态锁定 `outcome`。

## 命令

```bash
# 建档（记录 smart_score 快照）
python scripts/job_tracker.py add --company ACME --role "MLE" --source boss \
    --tier A --score 82 --reasons "匹配K8s,论文相关" --risks "缺Go经验"

# 标记投递
python scripts/job_tracker.py apply --id <id>

# 更新状态（带备注）
python scripts/job_tracker.py update --id <id> --status interview --note "一面已过"

# 列出 / 查看
python scripts/job_tracker.py list [--status applied] [--source boss] [--company ACME]
python scripts/job_tracker.py show --id <id>

# 反馈回路（转化漏斗 + 按 tier/来源）
python scripts/job_tracker.py stats

# 导出 markdown 汇总到 notes/job-tracker.md
python scripts/job_tracker.py export
```

## 与 career-copilot 的衔接

- Tier2「精投模式」投递前 `add` 建档（快照 tier/score/理由/风险）；投递后 `apply`；
  拿到面试/offer/拒信后 `update`。
- session-end 收尾除 career_log + career-context 外，补 `job_tracker.py` 记录本次结果。
- `stats` 输出是投放策略的反馈回路：低 tier 长期零转化 → 重新审视 smart_score 权重或收紧投放门槛。
