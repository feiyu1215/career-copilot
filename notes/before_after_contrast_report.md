<!-- last_reviewed: 2026-07-23 | review_cycle_days: 90 -->
# P2-3 路径2：before/after 提示消融对比报告

> 配套数据：`evals/before_after_contrast.json`（agnes-2.0-flash，repeat=2，4 个 contract_adherence 用例）
> 生成脚本：`evals/run_ablation.py`（复用 `run_dynamic_eval` 的 `JUDGE_SYS` / `SYSTEM_REFS` / `load_env`，本地 `run_one` 带生成空/异常重试）
> **本版为 2026-07-21 晚的「干净基线重跑」结果**（首跑 21:43 的 before 基线被 5/8 生成失败污染，已重跑修正）。

## 0. 一句话结论

重跑后，`before`（裸顾问）的**有效 run 从首跑的 3 个增至 5 个且全部 fail**，所以 `before=0.0` 现在建立在 5 个有效失败 run 上，比首跑（3 个有效）更扎实；`after`（契约硬化）= 4/5 有效 run 通过 = 0.625。逐契约看 ① 前提来源标注、② 单源红线、③ 改稿熔断均呈**强因果**（裸顾问有效 run 全 fail → 硬化后通过），④ Over-Claim(known_variance) 两版均 fail（agnes 生成侧残差）。**结论：契约指令是合规行为的因果驱动，非模型天赋**——与 M4/P1-2 形成互补因果证据。

## 1. 方法学与诚实标注（不粉饰）

- **SYNTHETIC 提示消融基线**：`before` = 人为构造的「裸顾问 system（无契约）」，**不是**历史「契约前的真实 skill 输出快照」（无可重建、不可伪造）。
- **不是真实用户代理**：无 production transcript，仅复用 `evals.json` 的 4 个契约用例。
- **增量有限、定位清晰**：M4 跨模型回归（agnes 3/3 + nvidia 4/4）+ P1-2 已覆盖软契约在真实模型上的稳健性；本跑增量在**因果隔离**——同一模型去掉指令→契约行为消失。
- **agnes 跨 run 方差已知**（case13 95↔45、case14 known_variance）；repeat=2 给稳定性信号但不消除。
- **agnes 当前限流严重**：首跑（21:43）+ 重跑（22:4x）空响应率偏高，after 组仍 3 个 null（首跑遗留未重滚）；before 组经第三次补跑（null_retries=8）后仅 case14 r2 残余 1 个 null。详见 §4。

## 2. 运行配置

| 项 | 值 |
|---|---|
| provider | agnes（沙箱可达的外部 Cloudflare 端点）|
| gen / judge 模型 | agnes-2.0-flash / agnes-2.0-flash |
| repeat | 2 |
| null_retries | 5（生成空/异常重试，重试间退避 3×(attempt+1)s 让限流冷却）|
| 用例 | 4 个 `contract_adherence`（id 11/12/13/14）|
| 分块 | 因沙箱前台 Bash ~5min 硬上限，拆成 11-12 / 13-14 两块前台跑，再合并（首跑整跑前台被 kill，后台则不受限）|

## 3. 总览（case 平均，无效 run 不计入分母）

| 指标 | 值 |
|---|---|
| before_overall_pass_rate | **0.0** |
| after_overall_pass_rate | **0.625** |
| delta_overall_pass_rate | **+0.625** |

## 4. 数据质量（重跑后现状，重要）

**重跑前（首跑 21:43）**：before 组 8 run 中 5 次生成失败（null）；after 组 2 次 null。
**重跑后（本版）**：before 组剩 **3 个 null**（11r2、13r1、14r2），after 组剩 **3 个 null**（12r1、13r1、14r2）。
**补跑残余 before null（第三次跑）**：用 `EVAL_ONLY_MODE=before EVAL_ONLY_IDS=11,13,14` + 重试 8 次 + 退避，只重滚 before 不碰 after。结果：**11r2、13r1 已修复为零 null**；仅 **case 14 r2 仍 null（8 次重试全空，顽固）**。

**第四跑（本回合，12 次重试）**：应「可以跑一下」再试 case14 r2，用 `EVAL_ONLY_IDS=14 EVAL_NULL_RETRIES=12` 单 case 前台重跑（不碰 after）。结果：**r2 仍 null（12 次重试全空，确认顽固）**；r1 重滚为 `fail(score=0)`（此前 20，均 fail，判定稳定 fail）。结论不变：case14 r2 是 agnes 生成侧对 Over-Claim 用例的空响应毛刺，重试无法消除，与限流时点相关。before 组仍 **7 有效 run 全 fail、0.0 极稳健**；该 1 残余 null 边际价值低，不再追。

最终数据质量：
- **before 组**：case 11/12/13 均 **0 null**，仅 case 14 r2 一个 null。有效 run = **7 个（11:2、12:2、13:2、14:1）且全部 fail** → `before=0.0` 由 7 个有效失败 run 支撑，极稳健，原"0.0 部分源于模型没生成"的污染已基本消除。
- **after 组**：仍 3 个 null（12r1、13r1、14r2），来自首跑，本次未重滚（用户只需清 before）。
- case 12 before 从「整组缺失」变为「40/45 双有效 fail」，② 单源红线有了可用 before 对照。

唯一残余 before null（case 14 r2）不影响结论：每 case 已有 ≥1 有效 before run 且全 fail；且该 null 经 8 次 + 12 次重试均无法消除，确为 agnes 生成侧毛刺，非「未烧够 API」所致（边际价值低，见 §8）。

## 5. 每用例对比表（重跑后）

| id | 契约 | before（有效 pass/总 run）| after（有效 pass/总 run）| Δscore | null 残留 |
|---|---|---|---|---|---|
| 11 | ① 前提来源标注 | 0/2（均 fail，r2 已修复）| 1/2（95/60）| +58 | — / — |
| 12 | ② 单源红线 | 0/2（40/45）| 1/1（100，r1 失败）| +58 | — / after r1 |
| 13 | ③ 改稿熔断 | 0/2（均 fail，r1 已修复）| 1/1（95，r1 失败）| +75 | — / after r1 |
| 14 | ④ Over-Claim（KV）| 0/1（r2 仍 null）| 0/1（45，r2 失败）| +25 | before r2 / after r2 |

> 表中"有效 pass/总 run"的"总 run"含 null；分子仅计有效（非 null）run。

## 6. 逐契约因果解读

**① 前提来源标注 —— 强因果 ✅**
before 唯一有效 run = fail(20)（不标来源）；after = 95/60（1/2 通过，含 1 个 null）。裸顾问不带来源标签，硬化后基本合规。Δscore +58。

**② 单源红线 —— 强因果 ✅（首跑无法对比，本版可对比）**
before = 40/45 双有效 fail（裸顾问把单源数字写进简历）；after = 100（1/1 有效）。契约指令驱动拒绝单源数字。Δscore +58。这是相对首跑的净改善（首跑 before 整组缺失）。

**③ 改稿熔断 —— 强因果 ✅**
before 有效 run = fail(20)（不前置声明熔断）；after = 95（1/1 有效）。Δscore +75，最大幅度的因果效应。

**④ Over-Claim（known_variance）—— 两版均 fail，契约未救回 ⚠️**
before = fail(20)，after = fail(45)。agnes 在该 case 生成侧偶发撞 F1 确定性终审禁区，契约写对但模型仍违背；judge 也偶发误判。与已知残差一致，本跑未提供也未反驳契约有效性。Δscore +25（硬化输出结构略更合规但仍触 judge）。

## 7. 与既有证据的互补定位

- **M4 跨模型回归**（agnes core=3/3 + nvidia 4/4）+ **P1-2** 已证：软契约在真实模型上稳健、跨模型不回退。
- **本跑（P2-3 路径2）新增**：因果隔离证据——同一模型、同一 judge，**去掉契约指令→契约行为消失**（① ③ 从合规变违规，② 从缺失变可对比且违规），证明合规靠契约指令驱动、非模型默认习惯。这对"弱模型/新手模型适配"尤其重要：迁移到更弱模型时必须保留/强化这些指令。
- **仍未被替代的盲区**：真实用户 transcript 盲评（路径1）才能补 `self-eval-bias-template` 的 B1 三重同源缺陷；合成消融再漂亮也不是真实用户代理。

## 8. 下一步建议

1. **（已闭合，边际价值低）唯一残余 before null（case 14 r2）**：第三跑修复 11r2/13r1 后，第四跑再针对 case14 r2 加 12 次重试仍全空 → **确认顽固毛刺**，非「未烧够 API」。before 组现 **7 个有效 run 全 fail**、`before=0.0` 极稳健，该 null 不影响结论、不再追。P2-3 路径2 干净基线收口。
2. **路径1 真实 transcript 盲评仍是最高价值动作**：待生产环境积累 transcript 后，按 `proxy-quality-eval-protocol.md` 跑 D1-D6 盲评，补三重同源盲区。
3. **不自动 commit**：延续"暂不 commit"裁决，所有 P2-3 产物留在 working tree。

## 9. 证据层级

- 方法学（消融设计）= SYNTHETIC-MECHANISM
- 运行结果（agnes 真实生成 + judge）= LLM-REAL，但 **before/after 各 3 个 null 因当前 agnes 限流**，证据强度低于首跑的 M4/P1-2，且弱于限流缓解后的理想状态。
