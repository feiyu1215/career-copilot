# Career Copilot 实施方案

> 每一项改进的具体实施步骤。每项开始前需重新思考：这个改进是否真的该这样做？有没有更简单/更合适的形式？

---

## P0 层：改动极小，立即可做

---

### 1. Stage 1 fallback 阈值 50 → 30

**文件**：`scripts/smart_score.py` 行 295  
**现状代码**：
```python
score = result.get("score", 50) if result else 50
```

**实施前重新思考**：
- 为什么是 30 而不是其他值？→ Stage 1 只是粗筛，fallback 意味着"LLM 没给出有效答案"。50 分意味着默认进入 Stage 2 候选池（通常阈值 40-50），等于 fallback 的 JD 几乎必定被保留。30 分让 fallback 的 JD 默认被过滤，只有确实被 Stage 1 评高分的才进入 Stage 2。
- 替代方案：fallback 时标记 `needs_retry: true`，下一轮单独重试？→ 增加复杂度，且 fallback 通常说明 JD 质量差或解析失败，低分合理。
- 风险：如果 LLM 偶尔超时导致 fallback，好岗位会被误杀 → 可以配合 retry 逻辑减少 fallback 频率。

**最终方案**：
1. 将 fallback 改为 30
2. 同时在 fallback 时打印 warning：`[WARN] JD #{id} 评分失败，使用默认分 30`
3. 在最终输出中标记 `"is_fallback": true`，让 verify_output 可以统计 fallback 率

**改动量**：~5 行

---

### 2. LLMClient 增加 timeout

**文件**：`scripts/llm_client.py` 行 122-130  
**现状代码**：`AsyncOpenAI` 的 `chat.completions.create` 没传 timeout，默认 600s。

**实施前重新思考**：
- 600s 对一次 LLM 调用太长了。正常响应 2-15s，超过 60s 基本是卡死了。
- 但 Stage 2 的 Listwise 评估（6 个 JD 一组）token 较多，可能需要 30-45s → timeout 不能设太短。
- 替代方案：不设全局 timeout，而是在每次调用时传入？→ 增加调用复杂度。全局合理值 + 可覆盖更好。

**最终方案**：
1. `LLMClient.__init__` 增加 `timeout: int = 120` 参数
2. 传递给 `AsyncOpenAI(timeout=self.timeout)`
3. 在 retry 逻辑中，timeout 错误立即重试（不等待指数退避），因为通常是网络抖动

**改动量**：~5 行

---

### 3. CORE_TEAM_SIGNALS 从硬编码改为 profile 驱动

**文件**：`scripts/post_judge.py` 行 119-126  
**现状代码**：
```python
CORE_TEAM_SIGNALS = [
    "豆包", "火山方舟", "Coze",
    "核心团队", "S级", "重点项目", "战略级", "一号位",
    "核心业务", "基础架构", "中台核心", "基础研发",
]
```

**实施前重新思考**：
- 问题本质：`["豆包", "火山方舟", "Coze"]` 是字节跳动特有的业务线，对非字节用户完全无效。
- 但通用信号（"核心团队"、"S级"等）对所有用户都有效 → 不能全部移走。
- 替代方案 A：profile 中增加 `core_team_signals` 字段，gen_profile 时由 LLM 根据目标公司生成。
- 替代方案 B：保留通用信号不动，只把公司特定的移到 profile。
- 方案 B 更简单，且不需要改 gen_profile 的 prompt → 选 B。

**最终方案**：
1. 将 CORE_TEAM_SIGNALS 拆为两部分：
   ```python
   # 通用核心团队信号（不依赖特定公司）
   GENERIC_CORE_SIGNALS = [
       "核心团队", "S级", "重点项目", "战略级", "一号位",
       "核心业务", "基础架构", "中台核心", "基础研发",
   ]
   ```
2. `post_judge(jobs, profile)` 函数中从 profile 读取 `profile.get("core_team_signals", [])`
3. 合并：`all_signals = GENERIC_CORE_SIGNALS + profile.get("core_team_signals", [])`
4. gen_profile 的 prompt 中增加提示：`如果用户有明确目标公司，提取该公司的核心业务线关键词到 core_team_signals 字段`

**改动量**：post_judge.py ~10 行，gen_profile.py prompt 增加 1 句话

---

### 4. Meta 权衡声明

**文件**：`SKILL.md` 顶部（frontmatter 之后）  
**现状**：直接进入全局约束，无"何时可以走捷径"的说明。

**实施前重新思考**：
- 目的：解决"简单问题也走全流程太重"的问题。
- 但声明不能太长（本身就是为了省 token）→ 3-4 行即可。
- 放置位置：必须在最前面（attention 最高），紧跟 frontmatter。
- 替代方案：不写声明，靠意图路由表来区分？→ 现有路由表只区分"做什么"，不区分"做多深"，加声明更直接。

**最终方案**：
在 SKILL.md 行 5（frontmatter 之后）插入：
```markdown
> **权衡声明**：本 Skill 偏向谨慎与完整性。以下场景可走快速路径（纯推理，不执行脚本）：
> 单个 JD 快速评估、Yes/No 判断、方向性建议。当用户说"快速看看"或"简单评估"时，
> 跳过完整框架直接给出判断。方向已明确且用户催促时，跳过确认环节直接执行。
```

**改动量**：3 行

---

### 5. JSON 解析逻辑统一抽取

**文件**：`scripts/smart_score.py` 行 119-152（_parse_json）+ 行 469-491（Stage 2 内重复逻辑）  
**另涉及**：`scripts/post_judge.py`、`scripts/verify_output.py` 中可能有类似逻辑

**实施前重新思考**：
- 现状：`_parse_json` 在 smart_score.py 中定义为模块级函数，但 Stage 2 内部又手写了一遍类似逻辑。
- 抽到哪里？选项：
  - A) 抽到 `llm_client.py` 中作为 `parse_llm_json(text)` → 与 LLM 调用耦合太紧
  - B) 新建 `scripts/utils.py` → 新增文件，增加认知负担
  - C) 保留在 `smart_score.py` 但让 Stage 2 逻辑复用同一个函数 → 最小改动
- 考虑到当前是单人项目，C 方案最简单。但如果其他文件也需要用，B 更好。
- 先查看：post_judge.py 和 verify_output.py 是否有 JSON 解析？→ verify_output 读的是已保存的 JSON 文件（json.load），不需要清洗。post_judge.py 也不做 LLM 输出解析。
- 结论：只有 smart_score.py 内部重复，选 C。

**最终方案**：
1. 删除 Stage 2 内部的重复 JSON 清洗逻辑（行 469-491）
2. 让 Stage 2 调用已有的 `_parse_json()` 函数
3. 给 `_parse_json` 增加第三层恢复：修复 trailing comma、single quotes
4. 增加第四层：regex 提取 `"score": \d+` 作为最后兜底，返回 `{"score": X, "is_fallback": true}`

**改动量**：~30 行改动（删重复 + 增强 _parse_json）

---

## P1 层：中等工作量，解决实际痛点

---

### 6. Pipeline Checkpoint 机制

**文件**：`scripts/smart_score.py` 行 742-931（run_pipeline 函数）  
**现状**：run_pipeline 190 行单体函数，中途失败从头重跑。

**实施前重新思考**：
- Checkpoint 存什么？每个 Stage 的输出结果。
- 形式选择：
  - A) 自动保存到 `_checkpoint_stageN.json` + `--resume` 参数恢复
  - B) 将 pipeline 拆成子命令（`--mode stage1/stage2/rerank`），中间文件即 checkpoint
  - 方案 B 更彻底（roadmap 二中已提出），但改动量大。方案 A 是增量改动。
- 实际使用场景：跑 200 个 JD 的 Stage 1 用了 5 分钟，然后 Stage 2 第 3 组挂了。A 方案可以从 Stage 2 恢复。
- 风险：checkpoint 文件没清理会污染下次运行 → 加 `--clean` 参数或成功后自动清理。
- 决定：先做 A（增量），B 作为后续重构。

**最终方案**：
1. 定义 checkpoint 目录：`output/.checkpoint/`
2. 每个 Stage 完成后保存：
   - `output/.checkpoint/stage1_results.json`
   - `output/.checkpoint/stage1_top_k.json`  
   - `output/.checkpoint/stage2_results.json`
3. `run_pipeline` 开头检查 checkpoint：
   ```python
   if args.resume and os.path.exists("output/.checkpoint/stage1_results.json"):
       print("[恢复] 检测到 Stage 1 checkpoint，跳过 Stage 1...")
       stage1_results = load_checkpoint("stage1_results")
   ```
4. Pipeline 成功完成后删除 `.checkpoint/` 目录
5. 增加 `--resume` 和 `--clean-checkpoint` CLI 参数

**改动量**：~40 行

---

### 7. gen_profile.py 增加 direction_anchors 确认输出

**文件**：`scripts/gen_profile.py` 行 297-311  
**现状**：输出了 role_type、core_experiences 数量，但没输出最关键的 `direction_anchors`。

**实施前重新思考**：
- direction_anchors 是整个 pipeline 的灵魂——决定了匹配方向。如果这一步错了，后面全错。
- 当前 SKILL.md 的工作流要求 agent "确认 profile 再继续"，但 stdout 没给出 direction_anchors 的值，agent 只能去读文件。
- 替代方案：让 agent 每次都 read profile 文件？→ 浪费 token，且不直观。
- 应该直接打印到 stdout，让 agent 一目了然。

**最终方案**：
1. 在现有输出后增加：
   ```python
   print(f"\n  direction_anchors:")
   for anchor in profile.get("direction_anchors", []):
       print(f"    - {anchor}")
   print(f"  hard_negatives: {profile.get('hard_negatives', [])}")
   print(f"  english_level: {profile.get('english_level', '?')}")
   print(f"\n⚠️  请确认以上方向锚点是否准确。如有偏差请手动修正 profile 文件。")
   ```

**改动量**：~8 行

---

### 8. fetch_jobs.py 翻页进度增强

**文件**：`scripts/fetch_jobs.py` 行 303, 366  
**现状**：只打印 `[page/total] +N 新增`，没有 ETA。

**实施前重新思考**：
- 目的：200 个 JD 可能要爬 10 页，每页 3-8 秒（取决于网站响应）。用户不知道还要等多久。
- ETA 计算方式：`avg_time_per_page × remaining_pages`
- 但是有些页可能因为去重导致 0 新增，要不要计入 ETA？→ 还是算，因为网络时间是固定的。
- 替代方案：用 tqdm？→ 引入额外依赖，对单脚本项目太重。简单计算 ETA 就够了。

**最终方案**：
1. 在翻页循环前记录 `start_time = time.time()`
2. 每页完成后计算并打印 ETA：
   ```python
   elapsed = time.time() - start_time
   avg_per_page = elapsed / page
   remaining = (total_pages - page) * avg_per_page
   print(f"[{page}/{total_pages}] +{added} | ETA: {remaining:.0f}s")
   ```
3. 全部完成后打印总耗时和 JD 总数

**改动量**：~10 行

---

### 9. LLMClient retry 逻辑区分错误类型

**文件**：`scripts/llm_client.py` 行 119-142  
**现状**：捕获所有 Exception，统一指数退避。

**实施前重新思考**：
- 问题：auth error（API key 错误）重试 5 次毫无意义，浪费 2+4+8+16+32 = 62 秒。
- rate limit 应该等更久（按 response header 的 retry-after）。
- timeout 应该立即重试（网络抖动）。
- invalid model 不应重试。
- 但 openai SDK 是否暴露了这些错误类型？→ 是的：`openai.RateLimitError`, `openai.AuthenticationError`, `openai.APITimeoutError`。

**最终方案**：
1. 引入 openai 的具体异常类
2. 分类处理：
   ```python
   except openai.AuthenticationError:
       raise  # 不重试，直接报错
   except openai.RateLimitError as e:
       wait = max(int(e.response.headers.get("retry-after", 30)), 2 ** attempt)
       print(f"[Rate Limited] 等待 {wait}s...")
   except openai.APITimeoutError:
       wait = 2  # 立即快速重试
   except Exception as e:
       wait = 2 ** (attempt + 1)  # 其他错误指数退避
   ```

**改动量**：~20 行

---

### 10. pre_filter.py 过滤规则可配置化

**文件**：`scripts/pre_filter.py` 行 101-105（ENGLISH_HARD_GATE_SIGNALS）+ 行 120-129  
**现状**：英语信号词、年限检测正则全部硬编码。

**实施前重新思考**：
- 需要配置化的有哪些？
  - 英语门槛词 → 通用，不太需要配置
  - 年限过滤阈值（比如"5 年以上经验才排除"vs"3 年以上就排除"）→ 需要
  - "排除实习/外包" → 有些应届生用户恰恰要看实习
- 配置放哪里？
  - A) pipeline_config.yaml → 对于"是否排除实习"这种个人偏好，放 profile 更合适
  - B) profile 中增加 `filter_config` 字段
  - C) CLI 参数 `--include-intern`
- profile 是 LLM 生成的（gen_profile），加配置字段不太合适 → 选 C（CLI 参数）。

**最终方案**：
1. `pre_filter.py` 的 `pre_filter(jobs, profile, config=None)` 增加 config 字典参数
2. config 支持：
   ```python
   {
       "include_intern": False,      # 是否保留实习岗
       "include_outsource": False,   # 是否保留外包岗
       "max_year_requirement": 10,   # 超过此年限要求才过滤
   }
   ```
3. smart_score.py 增加对应 CLI 参数，传递给 pre_filter

**改动量**：~15 行

---

### 11. diff_watch.py 增加"上次运行"提示

**文件**：`scripts/diff_watch.py`  
**现状**：`watch_history.json` 存了每次运行日期，但启动时不读取不展示。

**实施前重新思考**：
- 极简改动，没什么好纠结的。用户跑 diff_watch 时如果知道"上次是 3 天前跑的"，能更好理解新增 JD 的含义。
- 格式：`[diff_watch] 上次运行: 2025-05-25 (3 天前)，本次新增 12 条`

**最终方案**：
1. `run()` 函数开头读取 `watch_history.json`，取最后一条 run 的 date
2. 计算距今天数，打印提示
3. 如果是首次运行，打印 `[diff_watch] 首次运行，建立 baseline...`

**改动量**：~8 行

---

### 12. career_log.py 事件增加 model 信息

**文件**：`scripts/career_log.py` 行 234  
**现状**：事件只有 `type + timestamp + data`，不记录模型信息。

**实施前重新思考**：
- 谁调用 career_log？→ smart_score.py 在 pipeline 结束后记录 `match_round` 事件。
- 模型信息从哪来？→ smart_score.py 的 args 中有 `--stage1-model` 和 `--stage2-model`。
- 应该由 career_log 自动添加，还是由调用方传入？
  - career_log 是通用日志模块，不应该知道 model 的概念
  - 应该由调用方（smart_score.py）在 data 字典中传入 `model_config`
- 这就不是 career_log 的改动，而是 smart_score.py 记录事件时的改动。

**最终方案**：
1. `smart_score.py` 在记录 match_round 事件时，data 中增加：
   ```python
   "model_config": {
       "stage1": args.stage1_model,
       "stage2": args.stage2_model,
       "provider": args.provider,
   }
   ```
2. career_log.py 本身不改（保持通用性）

**改动量**：~5 行（在 smart_score.py 中）

---

### 13. check_env.py 增加网络连通性检查

**文件**：`scripts/check_env.py`（82 行）  
**现状**：只检查 Python 版本和包安装。

**实施前重新思考**：
- 最常见的运行失败原因就是网络问题（VPN 没开、provider API 不通）。
- 检查方式：简单 HTTP GET 到 provider 的 base_url？→ 不暴露 API key 的情况下 ping 一下就行。
- 替代方案：不改 check_env，而是在 llm_client 首次调用时做连通性检查？→ 那时已经进入 pipeline 了，太晚。check_env 的定位就是"跑之前确认环境 OK"。

**最终方案**：
1. 从 llm_client.py 的 PROVIDERS 导入 base_url 列表
2. 对每个 provider 做一次 HEAD 请求（timeout=5s）
3. 打印结果：`✓ internal: 可连通 (latency 230ms)` 或 `✗ external: 连接超时`
4. 如果所有 provider 不可连通，输出 WARNING 而非阻断（用户可能只用其中一个）

**改动量**：~15 行

---

## P2 层：锦上添花

---

### 14. generate_report.py 分层重构

**文件**：`scripts/generate_report.py`（729 行，generate_html 占 630 行）

**实施前重新思考**：
- 这是一个纯确定性模块（不调 LLM），重构风险低。
- 但 729 行的大文件，重构完需要严格验证输出 HTML 不变。
- 是否值得现在做？→ 如果不加新功能（暗色模式、搜索框），纯重构 ROI 低。
- 建议：**延后到需要加新功能时再重构**。标记为"下次改 report 时顺手做"。

**最终方案（延后执行）**：
1. 当需要加暗色模式或搜索框时，先拆分：
   - `prepare_report_data(scored_results, profile)` → 纯数据处理
   - `REPORT_TEMPLATE` → CSS + JS + HTML 骨架（考虑用 Jinja2 或简单 string.Template）
   - `render_html(data, template)` → 组装
2. 新功能在新结构上开发

---

### 15. Stage 2 并发度可配置

**文件**：`scripts/smart_score.py` 行 542  
**现状**：`concurrent_groups = 2` 硬编码。

**实施前重新思考**：
- 为什么硬编码为 2？→ 大概率是为了避免 rate limit。
- 如果 provider 支持更高 QPM，提升到 3-4 能显著加速 Stage 2。
- 但如果设太高触发 rate limit，反而更慢（retry 等待）。
- 最优策略：默认 2，暴露 CLI 参数让用户按需调整。

**最终方案**：
1. 增加 `--stage2-concurrency` CLI 参数，默认 2
2. 运行时 `concurrent_groups = min(args.stage2_concurrency, len(groups))`

**改动量**：~5 行

---

### 16. SKILL.md 规则精简

**文件**：`SKILL.md`（306 行）

**实施前重新思考**：
- 目标：306 行 → ≤ 150 行。
- 核心问题：哪些规则可以删/合并？需要对现有规则做"违反频率"评估。
- 如果没有数据（哪些规则经常被违反），就只能凭经验判断。
- 安全策略：先做减法实验——精简后跑 5 个真实场景，观察是否出现退化。
- 最大风险：删了某条规则后 agent 开始犯那个错误 → 加回来。

**最终方案**：
1. **合并**：
   - "运行时自检 9 条" + "错误思维对照 9 条" → 合并为 5 条"关键防线"（取最高频违反的）
   - "匹配哲学 5 条" → 精简为 3 条（合并相似的）
2. **移出**：
   - "文件结构树" → 删除（agent 需要时 ls）
   - "User-Learned Best Practices" → 移到 `references/evolution-log.md`
   - "Reference 自声明规范" → 移到 matching-guide.md 末尾
3. **保留核心**（约 80 行）：
   - 权衡声明（3 行）
   - 全局约束（5 条 → 精简为 3 条）
   - 思考框架（4 步，保留）
   - 意图路由表（保留）
   - 匹配哲学（3 条）
   - 关键防线（5 条）
4. **验证**：精简后用 5 个测试场景验证 agent 行为不退化

**改动量**：大改 SKILL.md + 新建 1 个 reference 文件

---

## 实施顺序建议

```
第一轮（30 分钟，纯 bugfix/微调）：
  #1 fallback 阈值 → #2 timeout → #4 Meta 声明 → #12 model 记录

第二轮（1 小时，可靠性提升）：
  #5 JSON 解析统一 → #9 retry 分类 → #6 checkpoint → #13 网络检查

第三轮（1 小时，UX 改善）：
  #3 CORE_TEAM 动态化 → #7 profile 确认 → #8 进度增强 → #11 上次运行

第四轮（2-3 小时，架构优化）：
  #16 SKILL.md 精简 → #10 过滤规则配置 → #15 并发度配置

第五轮（时机合适时）：
  #14 report 分层重构
```

---

## 实施原则

1. **每项改动前先 git stash**，确保可以干净回滚
2. **每完成一项立即测试**：至少跑一次相关脚本验证不 break
3. **重新思考节点**：每项开始实施前，花 30 秒问自己"这个改动真的是最小有效方案吗？有没有更简单的方式达到同样目的？"
4. **不做过度抽象**：这是单人项目，不需要为"未来可能的需求"预留接口

---

*方案完*
