# Golden Cases 复核表（001~010）

> 用途：你逐项复核后，改下面的 `REVIEW_*` 行即可；不改就保留当前值。
> 填完把本文件发回，我解析 `REVIEW_*` 写回 `case_*.json` 的
> `expected_score` / `expected_tier` / `annotator` 三个字段。
> （`REVIEW_NOTE` 仅备注，不写回 json；如要留痕可自存。）

## 填写规则
- `REVIEW_SCORE`：整数 0–100，按你的真实判断填（不要因为"AI 估了 X"就照抄）。
- `REVIEW_TIER`：A / B / C 三选一。
  - 参考分档：`A` ≳ 80（强匹配，可直投）、`B` ≈ 60–80（匹配良好，可投）、`C` ≲ 60（弱匹配/不建议优先）。
  - ⚠️ 注意现有 `README.md` 与 `case_001` 的 84/B 存在冲突（84 按 A≳80 应归 A）。请以你的口径为准，我们事后统一分档约定。
- `REVIEW_ANNOTATOR`：复核无误填 `human`；仍存疑填 `ai-draft`。
- 只改 `REVIEW_*` 四行；`META` / `CURRENT` 是只读参考，勿改。

---

## case_001
FILE: case_001.json
META: tech | backend | transition=false | stage=experienced | band=mid
CURRENT: score=84 | tier=B | annotator=human
REVIEW_SCORE: 84
REVIEW_TIER: B
REVIEW_ANNOTATOR: human
REVIEW_NOTE:

## case_002
FILE: case_002.json
META: tech | backend | transition=false | stage=experienced | band=high
CURRENT: score=92 | tier=A | annotator=ai-draft
REVIEW_SCORE: 92
REVIEW_TIER: A
REVIEW_ANNOTATOR: ai-draft
REVIEW_NOTE:

## case_003
FILE: case_003.json
META: tech | data | transition=false | stage=experienced | band=mid
CURRENT: score=71 | tier=B | annotator=ai-draft
REVIEW_SCORE: 71
REVIEW_TIER: B
REVIEW_ANNOTATOR: ai-draft
REVIEW_NOTE:

## case_004
FILE: case_004.json
META: tech | backend | transition=false | stage=experienced | band=low
CURRENT: score=58 | tier=C | annotator=ai-draft
REVIEW_SCORE: 58
REVIEW_TIER: C
REVIEW_ANNOTATOR: ai-draft
REVIEW_NOTE:

## case_005
FILE: case_005.json
META: tech | frontend | transition=false | stage=experienced | band=mid
CURRENT: score=80 | tier=B | annotator=ai-draft
REVIEW_SCORE: 80
REVIEW_TIER: B
REVIEW_ANNOTATOR: ai-draft
REVIEW_NOTE:

## case_006
FILE: case_006.json
META: tech | algorithm | transition=false | stage=experienced | band=mid
CURRENT: score=78 | tier=B | annotator=ai-draft
REVIEW_SCORE: 78
REVIEW_TIER: B
REVIEW_ANNOTATOR: ai-draft
REVIEW_NOTE:

## case_007
FILE: case_007.json
META: non-tech | product | transition=false | stage=experienced | band=mid
CURRENT: score=77 | tier=B | annotator=ai-draft
REVIEW_SCORE: 77
REVIEW_TIER: B
REVIEW_ANNOTATOR: ai-draft
REVIEW_NOTE:

## case_008
FILE: case_008.json
META: non-tech | operations | transition=false | stage=intern | band=mid
CURRENT: score=79 | tier=B | annotator=ai-draft
REVIEW_SCORE: 79
REVIEW_TIER: B
REVIEW_ANNOTATOR: ai-draft
REVIEW_NOTE:

## case_009
FILE: case_009.json
META: tech | supply-chain | transition=true | stage=experienced | band=mid
CURRENT: score=66 | tier=B | annotator=ai-draft
REVIEW_SCORE: 66
REVIEW_TIER: B
REVIEW_ANNOTATOR: ai-draft
REVIEW_NOTE:

## case_010
FILE: case_010.json
META: tech | algorithm | transition=false | stage=campus | band=high
CURRENT: score=80 | tier=A | annotator=ai-draft
REVIEW_SCORE: 80
REVIEW_TIER: A
REVIEW_ANNOTATOR: ai-draft
REVIEW_NOTE:

---

## 覆盖矩阵自检（填完我也会重新跑 `run_accuracy_eval.py --check` 校验）
- tech = 8 (001,002,003,004,005,006,009,010)
- non-tech = 2 (007,008)
- transition = 1 (009)
- campus/intern = 2 (008,010)
- high = 2 (002,010)
- low = 1 (004)
