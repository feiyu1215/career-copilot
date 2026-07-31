<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# T11 / T12 设计文档（自拟实现，待用户确认后落地）

> 背景：升级计划 v3.0 中 T11（版本回归对比）、T12（多 Judge 交叉验证）**无详细步骤**，
> 用户裁决「我按目标自拟实现」。本文件为落地前的设计草案，确认后转为代码 + 测试。
> 依赖：T10 golden cases（提供固定输入 + 可信标注）作为两项的共用数据底座。

---

## T11 — 版本间回归对比（version-to-version regression compare）

### 目标
管线任何改动（prompt 外置 T8 / 模型切换 / 代码重构 T4）都可能**静默改变打分结果**。
T11 在固定输入上对比「当前版本」与「已存基线快照」，量化漂移，把"分数变了但没人发现"
变成可门禁的硬信号。

### 输入
- 固定夹具：`evals/regression/fixtures/`（复用 T10 golden 的 resume+JD 对，或独立抽样 ≥20 条）。
- 基线快照：`evals/regression/baseline.json`（首跑 `snapshot.py` 生成，git 跟踪或标注版本号）。
- 当前输出：`smart_score.py` 跑夹具产出的 `scored_results.json`。

### 指标（per-job 对齐）
| 指标 | 定义 | 建议门禁 |
|------|------|----------|
| MAE(total_score) | 总分绝对误差均值 | ≤ 5 |
| Tier 一致率 / κ | 档位（A/B/C/D）一致 + Cohen's κ | κ ≥ 0.8 |
| Tier 翻转数 | 档位变化的 job 数 | ≤ 2（且不得 A↔D 跳变） |
| Outlier 数 | \|Δtotal\| > 10 的 job 数 | ≤ 10% |

### 产物
- `evals/regression/report.md`：漂移分布图（文本/表）+ 触发门禁的 job 清单。
- `evals/regression/diff.json`：结构化逐 job 差值。
- CLI：`python evals/run_regression_compare.py --baseline baseline.json --current scored.json`
  （亦可 `--snapshot` 仅生成基线）。

### 关键坑（预判）
- 对齐靠 job id，需保证夹具 job 在不同版本间 id 稳定（已在 T5 group_size/config 体系内）。
- LLM 本身有温度抖动 → 基线/当前各跑 **≥2 次取中位数**再比，避免把随机噪声当回归。

---

## T12 — 多 Judge 交叉验证（multi-judge cross-validation）

### 目标
验证打分**不是单一模型怪癖的产物**。用 K 个独立 Judge 对同一批 scored 结果独立判档，
测 inter-rater 一致性；低一致项标记人工复核。

### 输入
- T10 golden 的标注集（真值 tier）或 T11 夹具产出。
- K 个 Judge：`--judges friday,sub2api,agnes`（不同 provider/model）；同模型可加 temperature/seed 变体。

### 流程
1. 对每个样本，K 个 Judge 独立输出 `tier` + `confidence(1–5)`。
2. 计算一致性：
   - 两两 Cohen's κ（每对 Judge）；
   - 多 Judge 用 **Fleiss' κ**；
   - 分数向量 Pearson ρ / Spearman ρ。
3. 低一致（κ<0.4 或 ρ<0.6）样本 → 标记 `needs_human_review`。

### 门禁（建议）
- Fleiss' κ ≥ 0.6（中等一致）视为管线可信；
- 或与 golden 真值比，TierAcc ≥ 80%（复用 T10 门禁）。

### 产物
- `evals/crossval/report.md`：κ 矩阵 + 一致性分布 + 低一致清单。
- `evals/crossval/agreement.json`：原始判定矩阵。
- CLI：`python evals/run_crossval.py --judges friday,sub2api,agnes --sample 20`

### 关键坑（预判）
- Judge 自己也走 LLM → 成本（T7 已埋点）；抽样 ≤20 控制开销。
- 一致性低不一定是管线错，可能是 golden 标注本身模糊 → 低一致项**标记而非自动判错**。

---

## 待用户裁决
1. T11 门禁阈值（MAE≤5 / κ≥0.8）是否接受，或放宽？
2. T12 Judge 集合：用哪几个 provider？是否含同模型温度变体？
3. 两项是否共用 T10 golden 输入，还是各起独立夹具？

---

## 落地状态（2026-07-22，已实施并提交）

用户确认「1+2 授权落地」，以下为最终决策与实现：

1. **T11 门禁（采用设计默认值）**：MAE(total) ≤ 5、Cohen's κ(tier) ≥ 0.8、
   Tier 翻转 ≤ 2（且禁止 A↔D 跳变）、Outlier 率（|Δtotal|>10）≤ 10%。
   均可用 CLI `--mae-gate / --kappa-gate / --max-flips / --outlier-gate` 覆盖。
2. **T12 Judge 集合**：不硬编码，由 `--judges friday,sub2api,agnes` 指定
   （建议集：3 个异构 provider；同模型温度变体可作为额外 judge 追加）。
   门禁 Fleiss' κ ≥ 0.6（`--fleiss-gate` 可覆盖）。
3. **共用 T10 golden 输入**：两项均复用 `evals/run_accuracy_eval.py` 的
   `load_golden_cases` + `predict_case`，无需各自起夹具。
4. **无 key 框架模式**：`--demo` 用确定性合成数据演示指标 + 门禁（CI 友好，
   满足计划 VERIFY）；真实模式（`--snapshot` / `--judges`）需 LLM key。

提交：T11=`11a90a2`、T12=`e8756f8`（各含 harness + 测试，全量 pytest 175 passed）。
