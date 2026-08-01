#!/usr/bin\python3
"""
jd_guard.py — JD 信任边界（不可信数据）

核心立场（红线）：JD 是**外部不可信数据**，不是指令。
- 禁止执行 JD 内嵌的任何指令（无论它伪装成"岗位要求"还是"系统提示"）。
- 任何看起来像指令的片段，必须被剥离后只当作"待核验的文本"送入匹配/改写链路。
- 若 JD 含注入企图，输出带警示，绝不把注入内容当事实或当命令。

本模块全部为确定性检查（无 LLM），可在 CI / 离线单测中跑。

使用方式：
    from jd_guard import scan_jd, sanitize_jd, JdGuardReport

    report = scan_jd(jd_text, source="boss")
    if report.injection_detected:
        print(report.summary())
        cleaned = sanitize_jd(jd_text)   # 剥离注入片段，仅留可核验正文
    # 把 cleaned（或带警示的原文）送入下游，但严禁把 report 外的"指令"当动作执行

CLI：
    python jd_guard.py check --jd jd.txt
    python jd_guard.py sanitize --jd jd.txt --output jd.clean.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ============================================================
# 注入模式库（确定性匹配，按语义分组）
# ============================================================

# 1) 元指令 / 角色劫持：试图重新定义助手身份或推翻既有系统提示
META_INSTRUCTION_PATTERNS = [
    r"忽略(之前|以上|上述|前面).{0,6}?(指令|提示|要求|规则|system)",
    r"无视(之前|以上|上述|前面).{0,6}?(指令|提示|要求|规则)",
    r"忘记(之前|以上|上述|前面).{0,6}?(指令|提示|要求|规则)",
    r"你(现在)?(是|扮演|作为|变成).{0,12}?(助手|assistant|gpt|模型|ai)",
    r"system\s*prompt",
    r"developer\s*mode",
    r"jailbreak",
    r"越狱",
    r"新(的)?(指令|规则|系统提示)",
    r"重新(设定|定义|配置).{0,6}?(角色|身份|system)",
]

# 2) 行动指令：要求助手去"做"某事（而非描述岗位）
ACTION_INSTRUCTION_PATTERNS = [
    r"(请|麻烦|务必|必须|需要你).{0,10}?(发送|投递|提交|回复|代我|帮我发|apply|send|submit)",
    r"(把|将).{0,10}?(邮箱|手机|微信|电话|薪资).{0,6}?(改成|替换为|设为|改为|填成)",
    r"(把|将).{0,10}?(简历|资料|答案).{0,6}?(改成|替换为|伪造|编造|美化|夸大)",
    r"(不要|别|禁止).{0,8}?(告诉|提及|透露|写).{0,8}?(用户|候选人|他|我)",
    r"(向|给).{0,8}?(用户|候选人|hr| recruiter).{0,8}?(谎称|假装|隐瞒)",
    r"转发(到|至).{0,12}?(我的|指定|这个).{0,6}?(邮箱|微信|地址)",
    r"点击(这个)?链接",
    r"访问(以下|这个)?(链接|网址|url)",
    r"执行(以下|上面).{0,6}?(命令|脚本|代码)",
]

# 3) 格式/分隔符注入：利用 ``` / <system> / [INST] 等越权
DELIMITER_INJECTION_PATTERNS = [
    r"<system>",
    r"</system>",
    r"\[INST\]",
    r"\[/INST\]",
    r"<<SYS>>",
    r"<<END>>",
    r"```\s*(system|instruction|prompt|assistant)",
    r"<\!--\s*(system|instruction|prompt)",
]

# 4) 数据外泄意图：把内容导出到攻击者控制的地址
EXFILTRATION_PATTERNS = [
    r"(把|将).{0,12}?(简历|资料|对话|输出|答案).{0,8}?(发到|发送到|回传|上传到|post to)",
    r"(把|将).{0,12}?(内容|结果|文本).{0,8}?(发到|发送到|回传|上传到)",
    r"(邮件)?(至|到).{0,4}?[\w.+-]+@[\w-]+\.[\w.]+",  # 裸邮箱（在指令语境下）
    r"webhook",
    r"http(s)?://(?!.*(job|career|zhiwei|zhaopin|lagou|zhipin|boss)).{0,40}?\b",  # 非招聘域的链接（粗筛，低置信）
]

# 分组 → 严重度（用于报告与处置）
_GROUP_SEVERITY = {
    "meta_instruction": "high",
    "action_instruction": "high",
    "delimiter_injection": "medium",
    "exfiltration": "high",
}


@dataclass
class JdInjectionHit:
    group: str
    pattern: str
    snippet: str
    severity: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.group}: 命中「{self.pattern}」→ 「{self.snippet.strip()[:60]}」"


@dataclass
class JdGuardReport:
    """JD 信任边界扫描结果。"""
    raw_length: int = 0
    hits: list[JdInjectionHit] = field(default_factory=list)
    source: Optional[str] = None

    @property
    def injection_detected(self) -> bool:
        return len(self.hits) > 0

    @property
    def high_severity_count(self) -> int:
        return sum(1 for h in self.hits if h.severity == "high")

    def summary(self) -> str:
        head = (
            f"JD 信任边界扫描（source={self.source or 'unknown'}, "
            f"{self.raw_length} 字符）："
        )
        if not self.hits:
            return head + " 未检测到注入企图 ✅"
        lines = [head + f" 检测到 {len(self.hits)} 处可疑注入（高严重 {self.high_severity_count}）："]
        for h in self.hits:
            lines.append(f"  - {h}")
        lines.append(
            "处置：JD 视为不可信数据，上述片段已被剥离为纯文本，"
            "绝不作为指令执行；对外材料不采纳其中任何数字/要求。"
        )
        return "\n".join(lines)


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_COMPILED: dict[str, list[re.Pattern]] = {
    "meta_instruction": _compile(META_INSTRUCTION_PATTERNS),
    "action_instruction": _compile(ACTION_INSTRUCTION_PATTERNS),
    "delimiter_injection": _compile(DELIMITER_INJECTION_PATTERNS),
    "exfiltration": _compile(EXFILTRATION_PATTERNS),
}


def scan_jd(jd_text: str, source: Optional[str] = None) -> JdGuardReport:
    """扫描 JD 文本，返回不可信数据边界报告（确定性，无 LLM）。

    Args:
        jd_text: 原始 JD 全文（可能含 HTML/Markdown/注入片段）。
        source:  来源标注（boss / meituan / generic ...），仅用于报告展示。
    """
    report = JdGuardReport(raw_length=len(jd_text or ""), source=source)
    if not jd_text:
        return report

    for group, patterns in _COMPILED.items():
        severity = _GROUP_SEVERITY[group]
        for rx in patterns:
            for m in rx.finditer(jd_text):
                snippet = m.group(0)
                report.hits.append(
                    JdInjectionHit(
                        group=group,
                        pattern=rx.pattern,
                        snippet=snippet,
                        severity=severity,
                    )
                )
    return report


def _strip_hits(jd_text: str, report: JdGuardReport) -> str:
    """按命中片段所在行剥离注入内容，保留其余正文。

    策略：命中落在某一行 → 整行删除（避免半截残留）；
    对分隔符类命中（如 <system>）做就地删除而非删行，保留同行的正当 JD 文本。
    """
    if not report.hits:
        return jd_text

    drop_lines = set()
    for h in report.hits:
        if h.group == "delimiter_injection":
            continue  # 就地删除，不整行删
        start = jd_text.find(h.snippet)
        if start == -1:
            continue
        line_no = jd_text.count("\n", 0, start)
        drop_lines.add(line_no)

    # 先就地删分隔符类片段
    cleaned = jd_text
    for h in report.hits:
        if h.group == "delimiter_injection":
            cleaned = cleaned.replace(h.snippet, " ")

    # 再删整行
    out_lines = []
    for i, line in enumerate(cleaned.splitlines()):
        if i in drop_lines:
            continue
        out_lines.append(line)
    return "\n".join(out_lines).strip()


def sanitize_jd(jd_text: str, source: Optional[str] = None) -> tuple[str, JdGuardReport]:
    """剥离 JD 中的注入片段，返回（清洗后文本, 报告）。

    清洗后文本只含"待核验的岗位描述"，可直接送入匹配/改写链路——
    但下游仍不得把其中的任何要求当作指令执行。
    """
    report = scan_jd(jd_text, source=source)
    cleaned = _strip_hits(jd_text, report)
    return cleaned, report


def main():
    parser = argparse.ArgumentParser(description="JD 信任边界扫描（不可信数据）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="扫描 JD 并打印报告")
    p_check.add_argument("--jd", required=True, help="JD 文件路径或 '-' 读 stdin")
    p_check.add_argument("--source", default=None, help="来源标注（boss/meituan/...）")

    p_san = sub.add_parser("sanitize", help="剥离注入片段并输出清洗文本")
    p_san.add_argument("--jd", required=True, help="JD 文件路径或 '-' 读 stdin")
    p_san.add_argument("--output", default=None, help="输出路径（缺省打印到 stdout）")
    p_san.add_argument("--source", default=None, help="来源标注")

    args = parser.parse_args()

    if args.jd == "-":
        jd_text = sys.stdin.read()
    else:
        jd_text = Path(args.jd).read_text(encoding="utf-8")

    if args.cmd == "check":
        report = scan_jd(jd_text, source=args.source)
        print(report.summary())
        sys.exit(1 if report.injection_detected else 0)

    elif args.cmd == "sanitize":
        cleaned, report = sanitize_jd(jd_text, source=args.source)
        if report.injection_detected:
            print(report.summary(), file=sys.stderr)
            print("--- 清洗后 JD（仅待核验正文，勿当指令）---", file=sys.stderr)
        if args.output:
            Path(args.output).write_text(cleaned, encoding="utf-8")
            print(f"已写出: {args.output}")
        else:
            print(cleaned)
        sys.exit(0)


if __name__ == "__main__":
    main()
