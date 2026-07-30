# Golden Test Cases

人工标注的 JD-profile 评分基准。用于测量管线评分准确度。

## 格式

每个 case 是一个 JSON 文件（`case_XXX.json`），包含：
- `profile`: 精简版 boundary_profile（只含 direction_anchors, hard_negatives, skills）
- `jd_text`: 岗位描述全文
- `expected_score`: 人工标注分数（0-100）
- `expected_tier`: 人工标注档位（A/B/C）
- `tolerance`: 容差（默认 5 分）
- `key_reasons`: 标注理由（2-3 条）
- `difficulty`: easy | medium | hard | edge
- `annotator`: 标注者标识
- `annotated_at`: 标注日期

## 门控标准

- MAE ≤ 8（平均绝对误差）
- Spearman ρ ≥ 0.85（排序一致性）
- Tier Accuracy ≥ 80%（档位命中率）
- Outlier Rate ≤ 10%（偏差 > 15 分的比例）

## 标注指南

1. 分数含义：90+ = 强烈推荐，85-89 = 推荐（A档），72-84 = 可考虑（B档），<72 = 不推荐（C档）
2. 标注时考虑：技术栈匹配度、年限要求、方向一致性、英语要求、团队质量
3. 边界 case 优先：方向擦边、年限刚好、英语模糊、外包疑似

## 已交付状态（T10）

- `case_001.json`：计划规范自带的示例，**标注者 human**，可作为可信基准起点。
- `case_002~005.json`：**AI-draft 种子 case（`annotator: "ai-draft"`）**，用于让评估框架跑通并演示格式，
  其 `expected_score/tier` 为模型估算、**未经人工核实**，仅适合做冒烟测试，**不可用于宣称真实准确度**。
- 目标：积累 **20 个人工标注 case**。请人工复核 ai-draft 并补齐至 20（或重标）。

## 运行

```bash
# 框架自检（无需 LLM key，CI 友好）：加载 cases + 打印门控标准，exit 0
python evals/run_accuracy_eval.py --skip-on-error

# 真实准确度评估（需配置 LLM key）：调用管线打分并计算 MAE/ρ/TierAcc/Outlier
python evals/run_accuracy_eval.py --score --provider agnes --skip-on-error
```
