"""setup_wizard.py — 交互式建档引导（Phase 5.1）。

把 SKILL.md 的 setup 意图路由落地为可运行脚本：6 步引导新用户从零产出可用 profile，
闭环「抓得到 / 评得准 / 生成得了」之前缺的最后一环——「人怎么上手」。

依赖通过参数注入，离线可测：
- 真实 LLM 生成默认经 gen_profile.py（需联网 + LLM 配置）；测试时注入 mock profile_gen。
- 环境自检默认子进程跑 check_env.py（其 sys.exit 不影响本向导）；测试时注入 mock。

步骤：
1. 询问求职方向（应届 / 社招 / 实习 / 转型）
2. 收集简历（文件 / 粘贴文本 / 口述经历）
3. 调用 gen_profile.py 生成 boundary_profile.json + candidate_summary.txt
4. 展示结果，让用户确认 / 修正方向锚点
5. 询问目标 portal 偏好，写入 portals.yaml（外科手术式，保留注释）
6. 跑 check_env.py 确认环境就绪

用法：
    python scripts/setup_wizard.py --resume path.pdf --direction 社招 --portals boss,linkedin --yes
    python scripts/setup_wizard.py --resume-text "..." --non-interactive
    python scripts/setup_wizard.py --profile-json data/boundary_profile.json --skip-profile
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

# 确保同目录模块可 import（scripts/ 作为脚本目录自动在 sys.path[0]，这里补一道保险）。
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

VALID_DIRECTIONS = ("应届", "社招", "实习", "转型")
DEFAULT_DIRECTION = "社招"
_ENABLED_RE = re.compile(r"enabled:\s*(true|false)")


# ---------------------------------------------------------------------------
# 可注入依赖的默认实现
# ---------------------------------------------------------------------------

def _default_profile_gen(resume_path: Path, direction: str, scratch_dir: Path):
    """默认 profile 生成器：调用 gen_profile.py 的 async 入口（需 LLM + 网络）。"""
    from gen_profile import generate_profile, generate_summary

    profile = asyncio.run(
        generate_profile(Path(resume_path), direction=direction, output_dir=Path(scratch_dir))
    )
    summary = asyncio.run(generate_summary(profile, output_dir=Path(scratch_dir)))
    return profile, summary


def _default_check_env() -> int:
    """默认环境自检：子进程跑 check_env.py（避免其 sys.exit 影响本向导）。"""
    import subprocess

    proc = subprocess.run([sys.executable, str(_SCRIPT_DIR / "check_env.py")])
    return proc.returncode


def _default_ask(prompt: str, default: str) -> str:
    try:
        val = input(f"{prompt} [{default}] ").strip()
    except EOFError:
        return default
    return val or default


# ---------------------------------------------------------------------------
# portal 偏好写入（外科手术式，保留注释与格式）
# ---------------------------------------------------------------------------

def set_portal_prefs(yaml_text: str, decisions: dict) -> str:
    """修改 portals.yaml 的 enabled 开关，保留注释 / 格式。

    decisions: {portal_name: bool}。仅修改 portals: 段内、且命中 decisions 键的门户；
    同时兼容内联 dict（``boss: {enabled: true, ...}``）与多行（``enabled:`` 独立缩进行）两种写法。
    """
    lines = yaml_text.splitlines(keepends=True)
    out = []
    in_portals = False
    current: Optional[str] = None
    for line in lines:
        stripped = line.lstrip()
        if re.match(r"^portals:\s*$", line):
            in_portals = True
            out.append(line)
            continue
        if in_portals and not line.startswith(" ") and stripped:
            # 离开 portals: 段（遇到另一个顶层键，如 websearch_fallback:）
            in_portals = False
        if in_portals:
            m = re.match(r"^  (\w[\w-]*):", line)
            if m:
                current = m.group(1) if m.group(1) in decisions else None
            if current:
                new_line, n = re.subn(
                    _ENABLED_RE,
                    lambda mo, c=current: f"enabled: {'true' if decisions[c] else 'false'}",
                    line,
                    count=1,
                )
                if n:
                    out.append(new_line)
                    current = None
                    continue
        out.append(line)
    return "".join(out)


def _apply_portal_prefs(prefs, disable_others: bool, portals_path: Path, *, set_fn=None) -> None:
    """把目标 portal 偏好写回 portals.yaml。仅启用列出的；disable_others 时其余置 false。"""
    set_fn = set_fn or set_portal_prefs
    text = Path(portals_path).read_text(encoding="utf-8")
    if disable_others:
        # 需要全部门户名以决定「其余置 false」
        import job_common  # scripts/，纯 stdlib（yaml 缺失时回退内嵌默认，仍含门户名）

        data = job_common.load_portals(portals_path)
        all_names = list((data.get("portals") or {}).keys())
        decisions = {n: (n in prefs) for n in all_names}
    else:
        # 仅启用列出的，未列出的保持原状（不 clobber）
        decisions = {n: True for n in prefs}
    new_text = set_fn(text, decisions)
    Path(portals_path).write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 各步骤采集
# ---------------------------------------------------------------------------

def _collect_direction(opts, ask: Callable) -> str:
    if getattr(opts, "direction", None):
        return opts.direction
    if getattr(opts, "non_interactive", False):
        return DEFAULT_DIRECTION
    return ask("求职方向（应届/社招/实习/转型）：", DEFAULT_DIRECTION)


def _prepare_resume(opts, scratch: Path, ask: Callable) -> Optional[Path]:
    if getattr(opts, "skip_profile", False) and getattr(opts, "profile_json", None):
        return None
    if getattr(opts, "resume", None):
        p = Path(opts.resume)
        if not p.exists():
            raise FileNotFoundError(f"简历文件不存在: {p}")
        return p
    if getattr(opts, "resume_text", None):
        tp = scratch / "resume_pasted.txt"
        tp.write_text(opts.resume_text, encoding="utf-8")
        return tp
    if getattr(opts, "non_interactive", False):
        raise ValueError("未提供简历（--resume / --resume-text），且非交互模式无法采集")
    ans = ask("简历路径，或直接粘贴文本（多行/超长即视为粘贴）：", "")
    if not ans:
        raise ValueError("未提供简历")
    if "\n" in ans or len(ans) > 200:
        tp = scratch / "resume_pasted.txt"
        tp.write_text(ans, encoding="utf-8")
        return tp
    p = Path(ans)
    if not p.exists():
        raise FileNotFoundError(f"简历文件不存在: {p}")
    return p


def _confirm_anchors(summary: str, opts, ask: Callable) -> bool:
    if getattr(opts, "non_interactive", False) or getattr(opts, "yes", False):
        return True
    print("---- 生成的候选人摘要 ----")
    print((summary or "")[:2000])
    print("-------------------------")
    ans = ask("方向锚点是否确认？(y 确认 / n 稍后手动编辑 boundary_profile.json)：", "y")
    return ans.strip().lower() in ("y", "yes", "")


def _collect_portals(opts, ask: Callable):
    if getattr(opts, "portals", None):
        return [x.strip() for x in opts.portals.split(",") if x.strip()]
    if getattr(opts, "non_interactive", False):
        return None  # 使用 portals.yaml 现有默认，不改动
    ans = ask("目标 portal（逗号分隔，如 boss,linkedin,shixiseng；留空=不改）：", "")
    if not ans.strip():
        return None
    return [x.strip() for x in ans.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# 编排主流程
# ---------------------------------------------------------------------------

def run_setup(opts, *, profile_gen=None, check_env_fn=None, ask=None) -> dict:
    profile_gen = profile_gen or _default_profile_gen
    check_env_fn = check_env_fn or _default_check_env
    ask = ask or _default_ask

    out_dir = Path(getattr(opts, "output_dir", None) or (_SCRIPT_DIR.parent / "data"))
    out_dir.mkdir(parents=True, exist_ok=True)
    portals_path = Path(
        getattr(opts, "portals_yaml", None) or (_SCRIPT_DIR.parent / "config" / "portals.yaml")
    )

    scratch = Path(tempfile.mkdtemp(prefix="setup_scratch_", dir=out_dir))
    result: dict = {"direction": None, "resume_path": None, "steps": {}, "outputs": {}, "ok": True}
    try:
        # 1. 方向
        direction = _collect_direction(opts, ask)
        result["direction"] = direction

        # 2. 简历
        resume_path = _prepare_resume(opts, scratch, ask)
        result["resume_path"] = str(resume_path) if resume_path else None

        # 3. 生成 profile
        if getattr(opts, "skip_profile", False) and getattr(opts, "profile_json", None):
            pj = Path(opts.profile_json)
            profile = json.loads(pj.read_text(encoding="utf-8"))
            summary = profile.get("candidate_summary") or ""
            sum_path = pj.parent / "candidate_summary.txt"
            if not summary and sum_path.exists():
                summary = sum_path.read_text(encoding="utf-8")
        else:
            profile, summary = profile_gen(resume_path, direction, scratch)

        profile_path = out_dir / "boundary_profile.json"
        summary_path = out_dir / "candidate_summary.txt"
        profile_path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary_path.write_text(summary or "", encoding="utf-8")
        result["outputs"]["boundary_profile"] = str(profile_path)
        result["outputs"]["candidate_summary"] = str(summary_path)

        # 4. 确认方向锚点
        confirmed = _confirm_anchors(summary, opts, ask)
        result["steps"]["confirm_anchors"] = "confirmed" if confirmed else "deferred"

        # 5. portal 偏好
        portal_prefs = _collect_portals(opts, ask)
        if portal_prefs is not None:
            if not portals_path.exists():
                raise FileNotFoundError(f"portals.yaml 不存在: {portals_path}（无法写入偏好）")
            _apply_portal_prefs(
                portal_prefs, bool(getattr(opts, "disable_others", False)), portals_path
            )
            result["steps"]["portals"] = portal_prefs
        else:
            result["steps"]["portals"] = "skipped"

        # 6. 环境自检
        if getattr(opts, "skip_env_check", False):
            result["steps"]["env_check"] = "skipped"
        else:
            rc = check_env_fn()
            result["steps"]["env_check"] = "passed" if rc == 0 else "issues"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="career-copilot 交互式建档向导 (Phase 5.1)")
    p.add_argument("--resume", help="简历文件路径 (.pdf/.txt)")
    p.add_argument("--resume-text", help="直接粘贴的简历文本")
    p.add_argument("--direction", help="求职方向：应届/社招/实习/转型")
    p.add_argument("--portals", help="目标 portal（逗号分隔），如 boss,linkedin")
    p.add_argument("--disable-others", action="store_true", help="未列出的 portal 置为 enabled=false")
    p.add_argument("--output-dir", help="产出目录（默认 <repo>/data）")
    p.add_argument("--profile-json", help="已有 boundary_profile.json，配合 --skip-profile 跳过 LLM 生成")
    p.add_argument("--skip-profile", action="store_true", help="配合 --profile-json 跳过生成")
    p.add_argument("--skip-env-check", action="store_true")
    p.add_argument("--non-interactive", action="store_true", help="不提示，使用默认/提供值")
    p.add_argument("--yes", action="store_true", help="非交互下默认确认所有步骤")
    p.add_argument("--portals-yaml", help="portals.yaml 路径（测试用；默认 <repo>/config/portals.yaml）")
    args = p.parse_args(argv)
    try:
        result = run_setup(args)
    except Exception as e:  # noqa: BLE001
        print(f"[setup] 失败：{e}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
