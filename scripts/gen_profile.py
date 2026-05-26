#!/usr/bin/env python3
"""
gen_profile.py — 从简历文本自动生成 boundary_profile.json + candidate_summary.txt

核心功能：
  1. 读取简历文本（从 PDF/TXT 读入）
  2. 调用 gpt-4.1 生成结构化 boundary_profile.json
  3. 生成精炼的 candidate_summary.txt（供 Stage 1 使用）

使用方式：
    python3 gen_profile.py \
        --resume /path/to/resume.pdf \
        --output-dir /path/to/output/ \
        [--model gpt-4.1]

输出：
  - output_dir/boundary_profile.json
  - output_dir/candidate_summary.txt
"""

from __future__ import annotations

import os
import sys
import json
import asyncio
import argparse
from pathlib import Path

# 共享 LLM 客户端
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from llm_client import LLMClient  # noqa: E402


# ============================================================
# 简历读取
# ============================================================

def read_resume(filepath: str) -> str:
    """读取简历文本（支持 .txt 和 .pdf）"""
    p = Path(filepath)

    if p.suffix.lower() == ".pdf":
        # 尝试 PyPDF2 → pdfminer → pypdf
        text = None
        try:
            import PyPDF2
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            pass

        if not text:
            try:
                from pdfminer.high_level import extract_text
                text = extract_text(filepath)
            except ImportError:
                pass

        if not text:
            try:
                import pypdf
                reader = pypdf.PdfReader(filepath)
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError:
                pass

        if not text:
            raise ImportError(
                "读取PDF需要安装: pip install PyPDF2 或 pip install pdfminer.six 或 pip install pypdf"
            )
        return text

    else:
        # 默认作为文本文件读取
        return p.read_text(encoding="utf-8")


# ============================================================
# Profile 生成
# ============================================================

PROFILE_SYSTEM_PROMPT = """你是一位资深人力资源专家和行业分析师。你需要从候选人的简历中提取核心能力边界画像。

## 你的任务

分析简历，输出一个精确的 boundary_profile JSON。这个 JSON 的核心目的是：
帮助 AI 在岗位匹配时，既能识别真正适合的岗位，又能排除"表面相似但实际不匹配"的岗位。

## 输出格式

```json
{
  "role_type": "候选人的精确角色定位（如：AI产品经理（偏算法/智能化方向））",
  "direction_anchors": [
    "2-4个核心方向的简短标签（4-8字），用于快速锚定匹配方向",
    "例如：AI自动化评测、RAG知识检索、AI标注平台、推荐算法优化"
  ],
  "core_experiences": [
    {
      "what_i_did": "用1-2句话精确描述做了什么",
      "scenario": "归纳为一个通用的业务场景名称",
      "evidence_level": "L1/L2/L3（见下方定义）",
      "signal_words": [
        "从简历中提取的 3-6 个精确关键词，用于后续 JD 匹配"
      ],
      "signal_words_self_check": [
        "对每个 signal_word 的验证：'XX一词是否在金融/电商/通用 JD 中也会出现？如果是则太泛，需要替换为更精确的词'"
      ],
      "transferable_to": [
        "这个经验可以迁移到的岗位方向（3-5个）"
      ],
      "NOT_transferable_to": [
        "看起来相关但其实不适用的方向（2-4个）"
      ],
      "boundary_explanation": "为什么不可迁移？一句话说清本质差异"
    }
  ],
  "hard_negatives": [
    "整体不匹配的方向（5-8个）",
    "这些是候选人完全没有经验或明显不适合的大方向"
  ],
  "adjacent_but_different": [
    "容易被混淆的角色类型（2-4个）",
    "说明：XX（侧重YY，而非候选人的ZZ）"
  ],
  "english_evidence": {
    "level": "fluent/preferred/basic/unknown",
    "signals": ["从简历中找到的英语能力证据列表"],
    "explanation": "判断依据说明"
  },
  "education": {
    "degree": "本科/硕士/博士/其他",
    "tier": "strong/medium/weak",
    "school": "学校名称",
    "undergrad_school": "本科学校名称（如有）",
    "major": "专业方向"
  }
}
```

## evidence_level 定义（关键！）

每条 core_experience 必须标注证据层级：
- **L1（实习/初步接触）**：仅有实习经验，或"参与"但非核心贡献者。标志词：实习、参与、辅助、了解
- **L2（项目级/独立负责）**：独立负责过完整项目或模块，有产出。标志词：负责、主导、从0到1、独立完成
- **L3（技能/体系级）**：在该方向有体系化认知和可复用方法论。标志词：搭建体系、方法论沉淀、培训他人、推动全组/全部门

## signal_words 精确化规则（关键！）

signal_words 必须通过自我检查：
1. 提取候选人简历中的关键词作为初始候选
2. 对每个词问自己："一个金融产品经理/电商运营/通用互联网岗位的 JD 里是否也会出现这个词？"
3. 如果答案是"是"，这个词太泛了，必须替换为更精确的上下文相关词
4. 示例：
   - "数据分析" → 太泛（几乎所有 JD 都有）→ 替换为 "标注质量数据分析" 或 "模型效果数据分析"
   - "产品方案" → 太泛 → 替换为 "AI评测产品方案" 或 "RAG检索产品设计"
   - "项目管理" → 太泛 → 替换为 "算法迭代项目管理"
5. signal_words_self_check 字段必须包含这个验证过程的记录

## english_evidence 判断规则

- **fluent**：海外留学/工作经历、全英文简历、明确标注雅思7+/托福100+/六级600+
- **preferred**：有英语相关证书(六级550+/雅思6.5+)、部分英文工作经验、英文发表
- **basic**：仅列出四六级、无其他英语证据
- **unknown**：简历中完全没有英语相关信息

## education.tier 判断规则（关键！与核心团队降级直接挂钩）

tier 由"本科+研究生"组合决定，规则如下：

- **strong**：985硕及以上（不论本科）、211本+985硕、985本在读（无研究生）、双非本+985硕、985本+任何硕
- **medium**：211本+211硕、211本+双非硕、双非本+211硕、211本在读（无研究生）、任何本科+211硕
- **weak**：双非本+双非硕、双非本在读（无研究生）、专升本、二本及以下无985/211研究生

注意：
- "985" 仅指 C9 + 其余 985 工程高校（共39所），211 ≠ 985
- 暨南大学、华南师范大学等属于 211 但非 985
- 海外 Top 30 ≈ 985，Top 30-100 ≈ 211，其余按双非处理
- 核心逻辑：**研究生比本科权重更高**，985硕可以弥补本科短板

## 关键原则

1. **精确性**：scenario 要足够具体，不要用太泛的词（如"AI产品"太宽泛）
2. **边界清晰**：NOT_transferable_to 是关键 —— 它防止 AI 把候选人推到"看着像但不是"的岗位
3. **行业知识**：如果简历涉及特定行业术语（如评测、RAG、标注），要准确理解其含义
4. **hard_negatives 要诚实**：不要列太多，只列真正不匹配的
5. **adjacent_but_different**：列出最容易被误判的 2-4 个相邻角色
6. **signal_words 必须精确**：泛化词汇会导致所有 JD 都看起来匹配，这是致命错误
7. **evidence_level 要诚实**：不要给实习经验标 L3，证据层级决定匹配置信度

只输出 JSON，不要额外解释。"""


SUMMARY_SYSTEM_PROMPT = """你是一位简历精炼专家。将候选人的完整简历浓缩为 400-600 字的核心摘要。

## 要求
1. 用第三人称
2. 重点突出：方向定位 + 核心项目 + 量化成果 + 技能特长
3. 保留所有关键的技术名词和方法论名称
4. **必须保留教育背景**：学校、学历层次、专业方向（这是后续评估的关键信号）
5. **必须保留英语能力信息**：如有英语证书、海外经历、英文工作经验等，一定要保留
6. 语言精炼，每句话都有信息量
7. 如有获奖/竞赛（尤其是含金量高的），也要保留

## 格式
直接输出纯文本摘要，不需要标题或分段符号。第一句标明教育背景（学校+学历+专业），随后展开经验描述。"""


async def generate_profile(resume_text: str, model: str = "gpt-4.1", provider: str | None = None) -> dict:
    """调用 LLM 生成 boundary_profile"""
    client = LLMClient(model=model, max_concurrent=1, provider=provider)

    # 截断超长简历
    if len(resume_text) > 6000:
        resume_text = resume_text[:6000] + "\n\n[简历内容已截断]"

    content = await client.chat(
        system=PROFILE_SYSTEM_PROMPT,
        user=f"以下是候选人的简历：\n\n{resume_text}",
        temperature=0.0,
        max_tokens=3500,
    )

    # 解析 JSON
    content = content.strip()
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:])
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    if content.startswith("json"):
        content = content[4:].strip()

    import re
    # 清理 JSON 字符串值中的非法控制字符（保留 \n \r \t）
    def _clean_json(s):
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)

    try:
        profile = json.loads(_clean_json(content))
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            profile = json.loads(_clean_json(content[start:end + 1]))
        else:
            raise ValueError(f"无法解析 LLM 输出为 JSON:\n{content[:500]}")

    return profile


async def generate_summary(resume_text: str, model: str = "gpt-4.1", provider: str | None = None) -> str:
    """调用 LLM 生成精炼的候选人摘要"""
    client = LLMClient(model=model, max_concurrent=1, provider=provider)

    if len(resume_text) > 6000:
        resume_text = resume_text[:6000] + "\n\n[简历内容已截断]"

    return (await client.chat(
        system=SUMMARY_SYSTEM_PROMPT,
        user=f"以下是候选人的简历：\n\n{resume_text}",
        temperature=0.0,
        max_tokens=800,
    )).strip()


# ============================================================
# 主流程
# ============================================================

async def run(args):
    print("=" * 60)
    print("Gen Profile — 简历 → 边界画像 + 摘要")
    print("=" * 60)

    # 读取简历
    print(f"\n读取简历: {args.resume}")
    resume_text = read_resume(args.resume)
    print(f"  字数: {len(resume_text)}")

    # 并行生成 profile 和 summary
    provider = getattr(args, 'provider', None)
    print(f"\n生成中... (模型: {args.model}, provider: {provider or 'default'})")
    profile_task = generate_profile(resume_text, args.model, provider=provider)
    summary_task = generate_summary(resume_text, args.model, provider=provider)
    profile, summary = await asyncio.gather(profile_task, summary_task)

    # 保存
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_path = output_dir / "boundary_profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ Profile 已保存: {profile_path}")
    print(f"  role_type: {profile.get('role_type', '?')}")
    print(f"  core_experiences: {len(profile.get('core_experiences', []))} 个")
    print(f"  hard_negatives: {len(profile.get('hard_negatives', []))} 个")
    print(f"  english_level: {profile.get('english_evidence', {}).get('level', '?')}")
    print(f"\n  direction_anchors（方向锚点）:")
    for anchor in profile.get("direction_anchors", []):
        print(f"    - {anchor}")
    if profile.get("core_team_signals"):
        print(f"  core_team_signals: {profile.get('core_team_signals')}")
    print(f"\n  ⚠️  请确认以上方向锚点是否准确。如有偏差请手动修正 profile 文件。")

    summary_path = output_dir / "candidate_summary.txt"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"\n✓ Summary 已保存: {summary_path}")
    print(f"  字数: {len(summary)}")

    # 打印摘要预览
    print(f"\n{'='*60}")
    print("摘要预览:")
    print(f"{'='*60}")
    print(summary[:300] + "..." if len(summary) > 300 else summary)

    return profile, summary


def main():
    parser = argparse.ArgumentParser(description="从简历生成 boundary_profile + candidate_summary")
    parser.add_argument("--resume", required=True, help="简历文件路径 (.pdf 或 .txt)")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--model", default="gpt-4.1", help="使用的模型（默认 gpt-4.1）")
    parser.add_argument("--provider", default=None, help="LLM provider (internal/external)")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
