# 跨模型独立盲评方法论（Cross-Model Blind Evaluation）

本文档定义 Golden cases 的**跨模型独立盲评**流程，是 Phase 3 的核心产物。目标：在多个 LLM Provider 上独立跑同一批黄金用例，比较它们的评分准确度，**盲于"哪个模型 produced 哪个结果"**，避免人为偏袒或锚定。

## 1. 为什么需要盲评

- 单模型评分有方差（同 prompt 不同模型/温度结果不同）。
- 人工标注（`expected_score` / `expected_tier`）是唯一 ground truth，但人也会漂移。
- 盲评让"模型 A vs 模型 B vs 模型 C"的对比可被复现、可被审计，而非"我觉得 X 更好"。

## 2. 评测载体

- 黄金用例：`evals/golden/case_001..010.json`（10 个，覆盖矩阵见 `ANNOTATION_GUIDE.md`）。
- 评分运行器：`evals/run_accuracy_eval.py`
  - `--check`：离线自检覆盖矩阵与结构（无需 key）。
  - `--score --provider <name>`：对指定 Provider 跑真实评分门禁（需该 Provider 的 key）。

## 3. 门禁阈值（来自 ANNOTATION_GUIDE）

| 指标 | 阈值 | 含义 |
|---|---|---|
| MAE | ≤ 8 | 评分平均绝对误差（分） |
| ρ (Spearman) | ≥ 0.85 | 评分与人工标注的秩相关 |
| TierAcc | ≥ 80% | A/B/C 分级准确率 |
| Outlier | ≤ 10% | 超出 `tolerance` 的用例占比 |

## 4. 盲评流程（逐步）

1. **准备密钥**：为每个待评 Provider 配置环境变量（`FRIDAY_API_KEY` / `SUB2API_API_KEY` / `NVIDIA_API_KEY` / `AGNES_API_KEY`）。
2. **逐模型独立跑分**（每个 Provider 单独、互不看见彼此结果）：
   ```
   python evals/run_accuracy_eval.py --score --provider friday
   python evals/run_accuracy_eval.py --score --provider sub2api
   python evals/run_accuracy_eval.py --score --provider nvidia
   python evals/run_accuracy_eval.py --score --provider agnes
   ```
   每个命令输出该 Provider 的 MAE / ρ / TierAcc / Outlier，落盘到 `evals/transcripts/<provider>_<date>.jsonl`（已脱敏，仅含用例 id、模型分、人工分、偏差）。
3. **盲聚合**：把所有 `<provider>_*.jsonl` 汇总到一张表，但**先隐藏列名中的 Provider 标识**，仅以 `run_1 / run_2 / run_3 / run_4` 代称，由复核人（你）判读哪家更稳，再揭盲对应。
4. **揭盲与决策**：比对各模型在难例（`difficulty=hard|edge`）与硬负向（`hard_negatives` 命中）上的表现，选默认 Provider / 调 `LLM_FAILOVER_CHAIN` 顺序。

## 5. "盲"的关键点

- **结果先脱敏再聚合**：transcripts 不含 JD 原文/简历原文，只留 id + 分数，满足合规。
- **聚合时隐藏 Provider 名**：防止"已知是强模型就给高分"的锚定偏误。
- **难例优先看**：`difficulty=hard|edge` 与 `match_band=low` 的用例最能区分模型能力。

## 6. 当前状态

- 10 个 Golden cases 已按分级规则（90+/85–89=A/72–84=B/<72=C）标注，`_apply_review.py` 中 10 个分数均满足该规则。
- 本仓库以**契约测试 + 转录比对**为主；跨模型盲评的**实测**需密钥后运行上述命令，结论随跑分补齐（不在无 key 环境虚构）。
- 离线自检随时可跑：`python evals/run_accuracy_eval.py --check`。

## 7. 复核清单（给你）

- [ ] 10 个 case 的 `expected_score` / `expected_tier` 你是否认可（尤其 `golden_003`=70/C、`golden_004`=58/C 两个低分例）？
- [ ] 覆盖矩阵是否够（技术×3 / 非技术×2 / 跨行×1 / 应届实习×2 / 高匹配×1 / 低匹配×1）？
- [ ] 盲评是否要扩展到更多 Provider？默认链 `friday→sub2api→nvidia→agnes` 是否需要调整？
