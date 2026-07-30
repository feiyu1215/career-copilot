#!/usr/bin/env python3
"""简历生成质量 Eval（Phase 3.2）。

评估「简历产出物」（系统生成的草稿，或脱敏参考简历）在 5 个维度的质量：
  - 真实性 (authenticity)  确定性：C_R1~C_R4 四条硬契约 0 违规（不可妥协，HARD GATE）。
  - ATS 兼容 (ats)         确定性：verify_ats 的 A2(联系方式)/A3(乱码) 硬失败为 0；
                            A1(页数) 在「文本模式」（无真实渲染 PDF）下纯文本字符数会
                            低估真实页数，故默认仅作提示、不参与硬门禁；仅当
                            `--page-check`（真实渲染页数可得，如 live/generate 模式）才
                            作为硬失败。W-A 关键词覆盖为警告，不扣分。
  - 信息密度 (density)     确定性：按 verify_ats 同款 chars_per_page 估算「实际页数」，
                            求每页有效字符填充率（不低于 50% 即满分）。
  - 改写安全 (rewrite)     确定性：简历对「原始 profile」的落地比例（grounding），
                            即简历实质内容多大程度可追溯至画像——呼应 circuit breaker
                            「单轮改写不超过 60%」的语义（diff ≤ 60% ⇔ grounding ≥ 40%）。
  - 相关性 (relevance)     LLM-judge 优先；离线回退为 JD 关键词/锚点覆盖启发式。

设计原则（与 3.1 / 3.3 一致）：
  - 4 个确定性维度完全离线可跑，不依赖 LLM 网关 → CI 友好、可复现。
  - 相关性默认离线启发式，仅当显式 `--relevance-judge llm --provider X` 才调用 LLM。
  - 与 3.1（评分准确性）分工：3.1 管「岗位匹配分准不准」，本 eval 管「简历写得好不好」。

用法：
  python evals/run_resume_eval.py --check                 # 结构自检（离线，CI）
  python evals/run_resume_eval.py --reference             # 评估内置脱敏参考简历（离线，全 5 维）
  python evals/run_resume_eval.py --drafts-dir DIR        # 评估预生成草稿（DIR 下 <id>.txt）
  python evals/run_resume_eval.py --generate --provider X # 实时生成草稿并评估（需 LLM 网关）

门控（验收标准）：
  - 真实性 维度 == 100（任一硬契约违规即整体 FAIL）。
  - 5 case 平均总分 >= 75/100。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CASE_DIR = Path(__file__).parent / "resume_cases"

# 确保 scripts.* 可导入（无论 cwd 在哪）
# 同时把 scripts/ 加入，使 drafter_reviewer 内部的 `import jd_guard` 顶层导入也能解析
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

# 维度权重（等权）
DIMS = ["authenticity", "ats", "density", "rewrite", "relevance"]
DIM_LABELS = {
    "authenticity": "真实性",
    "ats": "ATS 兼容",
    "density": "信息密度",
    "rewrite": "改写安全",
    "relevance": "相关性",
}

GATE_TOTAL = 75.0          # 平均总分门禁
DENSITY_FILL_FLOOR = 0.5   # 密度：每页至少填充 50% 即满分
REWRITE_GROUND_FLOOR = 0.4 # 改写安全：grounding >= 40%（即 diff <= 60%）


# ============================================================
# 约束加载（单一事实源 config/constraints.yaml）
# ============================================================
def load_constraints() -> dict:
    try:
        import yaml
    except Exception:  # noqa: BLE001
        yaml = None
    p = REPO_ROOT / "config" / "constraints.yaml"
    if yaml is not None and p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    # 兜底：复用 verify_ats 已加载的（若其模块已 import）
    try:
        from scripts.verify_ats import _CONSTRAINTS
        return _CONSTRAINTS or {}
    except Exception:  # noqa: BLE001
        return {}


# ============================================================
# 各维度评分（均返回 0-100 的 float）
# ============================================================
def score_authenticity(resume: str, profile, jd: str) -> tuple[float, list[str]]:
    """C_R1~C_R4 四条硬契约。0 违规 → 100；有违规 → 0（不可妥协）。"""
    from scripts.drafter_reviewer import check_hard_contracts
    violations = check_hard_contracts(resume, profile, jd)
    if not violations:
        return 100.0, []
    msgs = [f"{cid}: {msg}" for cid, msg in violations]
    return 0.0, msgs


def score_ats(resume: str, jd_keywords, constraints: dict,
              page_check: bool = False) -> tuple[float, list[str], list[str], int]:
    """ATS 硬失败（A2 联系方式 / A3 乱码）扣分；W-A 关键词覆盖仅作警告，不扣分。
    A1 页数：在「文本模式」（无真实渲染 PDF）下，纯文本字符数会低估真实页数
    （verify_ats 按 ats.chars_per_page 估算偏保守），故默认仅作提示、不参与硬门禁；
    仅当 page_check=True（真实渲染页数可得，如 live/generate 模式）才作为硬失败。
    返回 (score, failures, warnings, estimated_pages)。"""
    from scripts.verify_ats import run_checks_text
    failures, warnings = run_checks_text(
        resume, jd_keywords=jd_keywords, constraints=constraints, page_check=page_check
    )
    score = max(0.0, 100.0 - 40.0 * len(failures))
    ats = constraints.get("ats", {})
    cpp = ats.get("chars_per_page", 2000)
    estimated_pages = max(1, (len(resume) + cpp - 1) // cpp)
    return score, failures, warnings, estimated_pages


def score_density(resume: str, constraints: dict) -> float:
    """信息密度：按「实际估算页数」折算每页有效字符填充率。
    纯文本下用 verify_ats 的同款 chars_per_page 估算页数，求每页填充率；
    填充率 >= DENSITY_FILL_FLOOR 即满分，低于则线性扣分。"""
    ats = constraints.get("ats", {})
    chars_per_page = ats.get("chars_per_page", 2000)
    n = len(resume)
    est_pages = max(1, (n + chars_per_page - 1) // chars_per_page)
    floor = est_pages * chars_per_page * DENSITY_FILL_FLOOR
    if n >= floor:
        return 100.0
    return round(100.0 * n / floor, 1)


def score_rewrite_safety(resume: str, profile: dict) -> tuple[float, float]:
    """落地比例（grounding）：画像的 skills + direction_anchors 在简历中的覆盖率。
    grounding >= REWRITE_GROUND_FLOOR（即 diff <= 60%）视为安全。"""
    vocab = list(profile.get("skills", [])) + list(profile.get("direction_anchors", []))
    vocab = [v for v in vocab if v]
    if not vocab:
        return 100.0, 1.0
    lowered = resume.lower()
    covered = sum(1 for v in vocab if v.lower() in lowered)
    ratio = covered / len(vocab)
    return round(ratio * 100.0, 1), ratio


def score_relevance(resume: str, jd: str, jd_keywords, provider: str | None) -> tuple[float, str]:
    """相关性：LLM-judge 优先；否则离线启发式（JD 关键词 + 锚点覆盖）。"""
    if provider:
        try:
            return _llm_judge_relevance(resume, jd, provider), "llm"
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] LLM 相关性评审失败，回退启发式：{e}", file=sys.stderr)
    # 离线启发式
    kws = list(jd_keywords or [])
    if not kws:
        # 从 JD 抽取名词性关键词（粗粒度：2-4 字连续中文 / 英文词）
        kws = re.findall(r"[一-鿿]{2,4}|[A-Za-z][A-Za-z+#.\-]{1,}", jd)
        kws = [k for k in kws if len(k) >= 2][:20]
    lowered = resume.lower()
    if not kws:
        return 50.0, "heuristic(no-keywords)"
    covered = sum(1 for k in kws if k.lower() in lowered)
    return round(100.0 * covered / len(kws), 1), "heuristic"


def _llm_judge_relevance(resume: str, jd: str, provider: str) -> float:
    from scripts.llm_client import LLMClient
    client = LLMClient(provider=provider)
    prompt = (
        "你是严格的简历-岗位相关性评审。给定一份简历与目标 JD，"
        "请评估简历内容是否「针对该 JD 定制」（突出相关能力、裁剪无关内容），"
        "而非通用模板。仅输出一个 0-100 的整数分数，不要解释。"
    )
    user = f"# 目标 JD\n{jd}\n\n# 简历\n{resume}"
    raw = asyncio.run(client.chat(prompt, user, temperature=0.0, max_tokens=10))
    m = re.search(r"\d+", raw or "")
    return float(m.group(0)) if m else 50.0


# ============================================================
# Case 加载 / 结构自检
# ============================================================
def load_cases() -> list[dict]:
    cases = []
    for f in sorted(CASE_DIR.glob("case_*.json")):
        cases.append(json.loads(f.read_text(encoding="utf-8")))
    return cases


def check_cases() -> list[str]:
    issues = []
    required = ("id", "profile", "jd_text", "jd_keywords", "reference_resume", "meta")
    for f in sorted(CASE_DIR.glob("case_*.json")):
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            issues.append(f"{f.name}: JSON 解析失败 ({e})")
            continue
        for k in required:
            if k not in c:
                issues.append(f"{f.name}: 缺字段 {k}")
        meta = c.get("meta")
        if not isinstance(meta, dict):
            issues.append(f"{f.name}: 缺 meta")
        else:
            for mk in ("track", "role_family", "transition", "career_stage", "match_band"):
                if mk not in meta:
                    issues.append(f"{f.name}: meta 缺 {mk}")
        if not str(c.get("reference_resume", "")).strip():
            issues.append(f"{f.name}: reference_resume 为空")
    return issues


# ============================================================
# 单 case 评估
# ============================================================
def evaluate_text(resume: str, case: dict, constraints: dict,
                  provider: str | None = None, page_check: bool = False) -> dict:
    profile = case["profile"]
    jd = case["jd_text"]
    jd_keywords = case.get("jd_keywords", [])

    auth_score, auth_v = score_authenticity(resume, profile, jd)
    ats_score, ats_fail, ats_warn, est_pages = score_ats(
        resume, jd_keywords, constraints, page_check=page_check
    )
    dens_score = score_density(resume, constraints)
    rewrite_score, grounding = score_rewrite_safety(resume, profile)
    rel_score, rel_src = score_relevance(resume, jd, jd_keywords, provider)

    per_dim = {
        "authenticity": auth_score,
        "ats": ats_score,
        "density": dens_score,
        "rewrite": rewrite_score,
        "relevance": rel_score,
    }
    total = round(sum(per_dim[d] for d in DIMS) / len(DIMS), 1)

    auth_pass = auth_score >= 100.0
    return {
        "id": case["id"],
        "per_dim": per_dim,
        "total": total,
        "auth_pass": auth_pass,
        "auth_violations": auth_v,
        "ats_failures": ats_fail,
        "ats_warnings": ats_warn,
        "estimated_pages": est_pages,
        "page_check": page_check,
        "grounding": grounding,
        "relevance_source": rel_src,
    }


# ============================================================
# 模式：reference / drafts-dir / generate
# ============================================================
def run_reference(constraints: dict, provider: str | None,
                  page_check: bool = False) -> list[dict]:
    results = []
    for case in load_cases():
        resume = case["reference_resume"]
        r = evaluate_text(resume, case, constraints, provider, page_check=page_check)
        results.append(r)
    return results


def run_drafts(drafts_dir: Path, constraints: dict, provider: str | None,
               page_check: bool = False) -> list[dict]:
    results = []
    cases = {c["id"]: c for c in load_cases()}
    for f in sorted(drafts_dir.glob("*.txt")):
        cid = f.stem
        case = cases.get(cid)
        if case is None:
            print(f"  [SKIP] {f.name}: 无对应 case", file=sys.stderr)
            continue
        r = evaluate_text(f.read_text(encoding="utf-8"), case, constraints,
                          provider, page_check=page_check)
        results.append(r)
    return results


def run_generate(constraints: dict, provider: str, page_check: bool = False) -> list[dict]:
    import asyncio
    from scripts.drafter_reviewer import DrafterReviewer
    results = []
    for case in load_cases():
        try:
            draft = asyncio.run(
                DrafterReviewer(provider).draft(case["profile"], case["jd_text"])
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [SKIP] {case['id']}: 生成失败 ({e})", file=sys.stderr)
            continue
        r = evaluate_text(draft, case, constraints, provider, page_check=page_check)
        results.append(r)
    return results


# ============================================================
# 输出 / 门控
# ============================================================
def print_report(results: list[dict]) -> bool:
    print("\n" + "=" * 72)
    print("简历生成质量 Eval 报告")
    print("=" * 72)
    all_pass = True
    for r in results:
        print(f"\n[{r['id']}]  总分={r['total']}  真实性={'PASS' if r['auth_pass'] else 'FAIL'}")
        for d in DIMS:
            print(f"    - {DIM_LABELS[d]:<6} {r['per_dim'][d]:>6.1f}")
        if r["auth_violations"]:
            for v in r["auth_violations"]:
                print(f"        [真实性违规] {v}")
        if r["ats_failures"]:
            for f in r["ats_failures"]:
                print(f"        [ATS 失败] {f}")
        if r["ats_warnings"]:
            print(f"        [ATS 警告] {'; '.join(r['ats_warnings'])}")
        note = "（文本模式：A1 页数仅提示，真实页数以渲染 PDF 为准）" if not r.get("page_check") else ""
        print(f"        估算页数={r['estimated_pages']}{note}")
        print(f"        改写落地比例 grounding={r['grounding']:.2f}；相关性来源={r['relevance_source']}")

        case_ok = r["auth_pass"] and r["total"] >= GATE_TOTAL
        all_pass = all_pass and case_ok
        print(f"    -> {'通过' if case_ok else '未达门禁'}")

    avg = round(sum(r["total"] for r in results) / len(results), 1) if results else 0.0
    auth_all = all(r["auth_pass"] for r in results)
    print("\n" + "-" * 72)
    print(f"平均总分 = {avg}  (门禁 >= {GATE_TOTAL})")
    print(f"真实性全部 100% = {auth_all}")
    gate = auth_all and avg >= GATE_TOTAL and len(results) > 0
    print(f"总体门禁 = {'PASS' if gate else 'FAIL'}")
    print("=" * 72)
    return gate


def main():
    parser = argparse.ArgumentParser(description="简历生成质量 Eval（Phase 3.2）")
    parser.add_argument("--check", action="store_true",
                        help="仅结构自检（离线，CI 友好）")
    parser.add_argument("--reference", action="store_true",
                        help="评估内置脱敏参考简历（离线，全 5 维）")
    parser.add_argument("--drafts-dir", type=str, default=None,
                        help="评估预生成草稿目录（<id>.txt）")
    parser.add_argument("--generate", action="store_true",
                        help="实时调用 DrafterReviewer 生成草稿并评估（需 LLM 网关）")
    parser.add_argument("--provider", type=str, default=None,
                        help="LLM provider（用于 --generate 与 --relevance-judge llm）")
    parser.add_argument("--relevance-judge", choices=["heuristic", "llm"], default="heuristic",
                        help="相关性评审方式：heuristic(默认,离线) / llm(需 --provider)")
    parser.add_argument("--page-check", action="store_true",
                        help="启用 ATS A1 页数硬门禁（仅当提供真实渲染页数/PDF 时有意义）")
    args = parser.parse_args()

    if args.check:
        issues = check_cases()
        if issues:
            print("❌ 结构自检失败：")
            for i in issues:
                print("  - " + i)
            sys.exit(1)
        print(f"✅ 结构自检通过（{len(load_cases())} 个 case）")
        sys.exit(0)

    rel_provider = args.provider if args.relevance_judge == "llm" else None
    constraints = load_constraints()
    page_check = args.page_check

    if args.reference:
        results = run_reference(constraints, rel_provider, page_check=page_check)
    elif args.drafts_dir:
        results = run_drafts(Path(args.drafts_dir), constraints, rel_provider, page_check=page_check)
    elif args.generate:
        if not args.provider:
            print("❌ --generate 需要 --provider", file=sys.stderr)
            sys.exit(2)
        results = run_generate(constraints, args.provider, page_check=page_check)
    else:
        # 默认：reference 模式（离线可复现）
        results = run_reference(constraints, rel_provider, page_check=page_check)

    gate = print_report(results)
    sys.exit(0 if gate else 1)


if __name__ == "__main__":
    main()
