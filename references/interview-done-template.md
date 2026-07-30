# Interview Done — 面试结果事件模板

> 用于向职业日志写入一条「面试结束」事件，并 **自动触发竞争力重算**（若已配置 `--competitiveness-store`）。
> 写入入口：`scripts/career_log.py append --type interview_done --data '{...}'`
>
> **隐私红线（同 SKILL.md）**：不要写面试官真名、身份证号、完整 JD 原文；写岗位维度标签即可（如 `"分布式事务"`、`"系统设计"`）。

---

## 字段定义

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `company` | ✅ | string | 公司名（去隐私，用公开简称即可），用于 stats 漏斗按时点聚合 |
| `result` | ✅ | string | 结果：`pass` / `fail`；未出结果时可用 `pending`（stats 与竞争力重算均接受） |
| `role` | ⬜ | string | 应聘岗位（可选，便于人工回溯） |
| `round` | ⬜ | string | 轮次：如 `初试` / `复试` / `三面` / `HR` / `笔试` / `群面`（可选） |
| `strong_points` | ⬜ | list[str] | **强项维度标签**，喂给竞争力引擎做正增益（如 `"系统设计"`、`"编码能力"`） |
| `weak_points` | ⬜ | list[str] | **弱项维度标签**，喂给竞争力引擎做负增益（如 `"分布式事务"`、`"英语沟通"`） |
| `learnings` | ⬜ | list[str] | 复盘收获（可选，进职业记忆，不计入分数） |
| `questions_asked` | ⬜ | list[str] | 被问到 / 自己问的关键问题（可选） |
| `duration_minutes` | ⬜ | int | 面试时长（可选，仅记录用） |
| `notes` | ⬜ | string | 其他备注（可选） |

> 维度标签用自然语言短词即可，竞争力引擎通过 `map_to_dimensions()` 把标签映射到
> `技术深度 / 工程实践 / 系统设计 / 业务理解 / 沟通协作 / 学习成长` 六个维度（同 `references/career-memory.md`）。

---

## 复制即用（JSON）

### 通过（pass）

```json
{
  "company": "美团",
  "result": "pass",
  "role": "后端开发工程师",
  "round": "三面",
  "strong_points": ["系统设计", "编码能力"],
  "weak_points": ["分布式事务"],
  "learnings": ["多聊业务背景，少堆八股", "白板先讲思路再写代码"],
  "questions_asked": ["如何设计异地多活?", "你们的服务治理方案?"],
  "duration_minutes": 60
}
```

### 未通过（fail）

```json
{
  "company": "字节",
  "result": "fail",
  "role": "客户端开发工程师",
  "round": "复试",
  "strong_points": ["工程实践"],
  "weak_points": ["系统设计", "算法"],
  "learnings": ["算法得系统刷一遍", "系统设计先把 CAP/一致性讲清楚"]
}
```

### 结果未出（pending）

```json
{
  "company": "某厂",
  "result": "pending",
  "role": "SRE",
  "round": "HR"
}
```

---

## 命令行示例

```bash
# 基础：仅记结果（写职业日志 + 参与 stats 漏斗）
# 职业日志默认落在 ~/.catpaw/career-copilot/career-log.jsonl
# （可用环境变量 CAREER_COPILOT_DIR 改位置；career_log.py append 不接收 --career-log 参数）
python scripts/career_log.py append \
  --type interview_done \
  --data '{"company":"美团","result":"pass","strong_points":["系统设计"],"weak_points":["分布式事务"]}'

# 进阶：带竞争力闭环（自动重算并落盘竞争力快照，供周报引用）
python scripts/career_log.py append \
  --type interview_done \
  --data '{"company":"美团","result":"pass","strong_points":["系统设计"],"weak_points":["分布式事务"]}' \
  --competitiveness-store ~/.catpaw/career-copilot/competitiveness.json

# 周报渲染时 generate_report.py / run_pipeline.py 会自动读取同一份 career-log.jsonl，
# 用于竞争力 delta 的面试归因；若职业日志在非默认位置且未用 CAREER_COPILOT_DIR 指定，可显式覆盖：
python scripts/generate_report.py \
  --competitiveness-store ~/.catpaw/career-copilot/competitiveness.json \
  --career-log /path/to/your/career-log.jsonl
```

> 配合 `references/setup-guide.md` Step 7 设置 `CAREER_COMPETITIVENESS_STORE` 后，`run_pipeline`
> 会自动在周报里渲染竞争力板块（`--competitiveness-provider agnes` 或 `LLM_PROVIDER=agnes` 还可叠加教练建议）。

---

## 校验规则

- `company` 与 `result` 为 **必填**，缺失时 `career_log.py` 直接报错退出。
- `result` 大小写不敏感（`PASS`/`Fail` 均可），竞争力重算按小写归一。
- 与 stats 漏斗、`render_competitiveness_section` 的口径一致：`pass_rate = pass / 总场数`（含 `pending` 计入分母）；
  若只想统计已出结果场次，在 `references/career-memory.md` 的漏斗口径中剔除 `pending` 即可。

## 下游消费

- `scripts/stats.py`：按 `company` + `result` 出面试漏斗与通过率。
- `scripts/competitiveness_tracker.py`：用 `strong_points` / `weak_points` 重算六维分数与 `overall`，并比较生成 `overall_delta`（正/负/持平）。
- `scripts/generate_report.py`：在周报的「竞争力」板块引用最新快照与 `overall_delta`，可选叠加 Agnes 教练叙述。
