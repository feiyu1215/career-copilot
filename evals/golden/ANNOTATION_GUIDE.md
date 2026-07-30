# Golden Cases 标注指南（ANNOTATION_GUIDE）

用于 `evals/run_accuracy_eval.py` 评分准确度门禁的人工标注规范。

## 文件结构
每个 `case_XXX.json`（当前为 `golden_001` ~ `golden_010`）含：
- `id`：稳定标识（如 `golden_001`）
- `profile`：`direction_anchors` / `hard_negatives` / `skills` / `years_experience`
- `jd_title` / `jd_department` / `jd_location` / `jd_text`：目标 JD
- `expected_score`：0-100 人工打分
- `expected_tier`：`A` / `B` / `C`（人工标注为准，不必机械阈值）
- `tolerance`：允许偏差（评分与 expected_score 的差容忍上限）
- `key_reasons`：关键理由（含扣分项与硬负向）
- `difficulty`：`easy` / `medium` / `hard` / `edge`
- `annotator`：`human`（你本人，唯一 ground truth）或 `ai-draft`（待复核）
- `annotated_at`：标注日期
- `meta`：覆盖矩阵标签（见下）

## Tier 约定
tier 由人工标注决定，与 expected_score 大致对应（A 高分、C 低分）。评测以人工 `expected_tier` 为准，不强制机械阈值。

## 红线（与 drafter 同源）
- 不编造：只标画像与 JD 明确出现的能力
- 不夸大：级量保持画像原样
- JD 不可信：只基于画像真实能力判分
- 硬负向：命中 `hard_negatives` 必须显著扣分或判 C

## 覆盖矩阵（10 case 应覆盖）
- 技术岗 ×3（算法/后端/前端）
- 非技术岗 ×2（产品/运营）
- 跨行转型 ×1（传统行业 → 互联网）
- 应届/实习 ×2
- 高匹配（tier = A）×1
- 低匹配（tier = C）×1

`meta` 字段：`track`(tech|non-tech) / `role_family` / `transition`(bool) / `career_stage`(campus|intern|experienced) / `match_band`(high|mid|low，按 tier 对齐：A→high, C→low, 其余 mid)。

## 离线自检
```
python evals/run_accuracy_eval.py --check
```
打印覆盖矩阵计数与结构问题（exit 非 0 = 有缺口/问题）。

## 跑真实评分门禁（需 LLM key）
```
python evals/run_accuracy_eval.py --score --provider agnes
```
门控：MAE≤8, ρ≥0.85, TierAcc≥80%, Outlier≤10%
