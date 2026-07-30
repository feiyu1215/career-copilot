# Spec: 增量 1 — verify_ats.py（ATS 文本层 + 硬性不变量门禁）

> 属于 `career-copilot-upgrade-plan.md` 的 P2。聚焦、可独立完成、可全自测。
> 配套：absorb-analysis.md（可行性）、upgrade-plan.md（整体路线 v2.1）。

## Objective

为 Tier2「精投模式」生成 LaTeX CV 后提供**客观出厂校验**：简历 PDF 的 ATS 文本层与硬性不变量（页数、联系方式字面文本、无乱码、关键词覆盖）由代码断言，而非肉眼核对。这是计划 §4.3「客观不变量 → `verify_*` 为唯一权威」的落地。

用户故事：生成 CV 后跑 `verify_ats.py --pdf cv.pdf`，任一硬性不变量不满足即阻断交付（退出码 1），并给出可定位的契约号 [A#]。

## Tech Stack

- Python 3.9+（与 pyproject 一致）
- `pypdf>=3.0`（项目已有依赖，纯 Python，离线可用）→ 文本层提取 + 页数，主后端
- `pdftotext` + `pdfinfo`（poppler，可选）→ 兜底后端
- `PyYAML`（已有）→ 读 `config/constraints.yaml`
- `pytest`（已有）→ 测试

## Commands

- 运行：`python3 scripts/verify_ats.py --pdf ./cv.pdf [--keywords "Python,风控"]`
- 测试：`python3 -m pytest tests/test_verify_ats.py -q`

## Project Structure

- `scripts/verify_ats.py` → 新增门禁脚本（对齐 `verify_output.py` 风格：docstring + argparse + `load_constraints` + failures/warnings + 退出码）
- `config/constraints.yaml` → 新增 `ats:` 段（单一事实源）
- `tests/test_verify_ats.py` → 用 pypdf 合成 PDF 自测（离线）

## Code Style

对齐 `verify_output.py`：函数 `run_checks(...)` 返回 `(failures, warnings)`；failures 非空 = 退出码 1；警告用 `[W-...]` 显式暴露（契合「隐蔽 fallback 更危险」）。契约号 [A1]/[A2]/[A3]，关键词覆盖用 [W-A]。

```python
failures, warnings = run_checks(pdf_path, jd_keywords)
# failures 非空 -> 退出码 1；warnings 仅暴露不阻断
```

## Testing Strategy

- 框架：pytest（tests/，importlib 加载脚本，对齐 test_verify_output.py）
- 离线自测：测试内用最小合法 PDF 生成器（`pypdf` 可读字节）合成样本，不依赖外部文件
- 用例：合法 2 页全过；3 页→[A1]；缺联系方式→[A2]；含 `(cid` 乱码→[A3]；关键词缺失→[W-A] 不失败；全命中→覆盖摘要
- 覆盖：每个契约号至少 1 例

## Boundaries

- Always: 跑测试再交付；约束只在 `constraints.yaml` 一处定义；失败显式带 [A#]
- Ask first: 改 `ats` 段默认值（如 page_count 变 1）；改 require_contact 语义
- Never: 提交密钥；让 ATS 检查静默通过（warning 必暴露）；用 prompt 自检替代代码门禁

## Success Criteria

1. `verify_ats.py --pdf <合法2页CV>` 退出码 0
2. 3 页 PDF → 退出码 1 且含 [A1]
3. 缺邮箱/电话 PDF → 退出码 1 且含 [A2]
4. 含 `(cid` 乱码 PDF → 退出码 1 且含 [A3]
5. 给 JD 关键词但 CV 缺词 → 退出码 0 且 [W-A] 暴露缺失（不硬失败）
6. `pypdf` 不可用时自动回退 `pdftotext`+`pdfinfo`，缺失则明确报错

## Open Questions

- 同义词匹配（covered/synonym/missing 三表中的 synonym）暂为轻量占位（JD 原词命中即 covered），后续可接轻量同义词表，不在本增量范围。
- BOSS 抓取（P6）复用 `fetch_jobs.py` 的 catdesk 机制加 BOSS 预设，见下一增量。
