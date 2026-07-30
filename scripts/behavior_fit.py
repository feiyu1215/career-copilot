#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""behavior_fit.py — 行为风格 × JD 要求 拟合评分（确定性，纯 stdlib，零网络）。

把 references/behavioral-profile.md §3 的「JD 关键词 ↔ 行为风格映射」落为可测代码：
给定 JD 文本 + 候选人的行为画像，给出 behavior_fit 分数（0~1）及命中/缺口。

行为维度采用 DISC 四轴（与 behavioral-profile.md §1 对齐）：
  D 支配/结果/决断；I 影响/沟通/人际；S 稳健/协作/可靠；C 审慎/分析/精确。

候选画像（config/behavioral_profile.json，可选）接受两种形态：
  - {"styles": {"D": 1.0, "I": 0.8, "S": 0.2, "C": 0.5}}   # 0~1 连续分
  - {"high": ["D","I"], "low": ["S","C"]}                    # 离散高低
缺失/空 → 中性画像（score 恒为 0.5，不误导）。
"""
from __future__ import annotations

import json
import os

# JD 关键词 → 隐含的行为维度（源自 behavioral-profile.md §3 的「强匹配写法」反推）。
# 每命中一个关键词，累加其隐含维度的权重（1.0）。
JD_BEHAVIOR_MAP = {
    # D 支配/结果
    "负责": "D", "主导": "D", "驱动": "D", "推动": "D", "决断": "D", "owner": "D",
    "ownership": "D", "结果导向": "D", "拿结果": "D", "带团队": "D", "lead": "D",
    "领导": "D", "管理": "D",
    # I 影响/沟通
    "沟通": "I", "表达": "I", "演讲": "I", "汇报": "I", "影响": "I", "人际": "I",
    "协调": "I", "跨团队": "I", "跨部门": "I", "presentation": "I",
    "客户": "I", "对外": "I",
    # S 稳健/协作
    "协作": "S", "配合": "S", "稳健": "S", "可靠": "S", "支持": "S", "服务": "S",
    "耐心": "S", "团队氛围": "S", "落地执行": "S", "细致": "S",
    # C 审慎/分析
    "分析": "C", "数据": "C", "精确": "C", "严谨": "C", "研究": "C", "方法论": "C",
    "体系": "C", "复盘": "C", "逻辑": "C", "风控": "C", "建模": "C", "量化": "C",
    "模型": "C",
}

_DIMS = ("D", "I", "S", "C")


def _profile_signals(profile: dict | None) -> dict:
    """把候选画像归一化为各维度的「强/弱」信号（0~1，1=强）。缺失 → 全 0.5（中性）。"""
    if not profile:
        return {d: 0.5 for d in _DIMS}
    styles = profile.get("styles")
    if isinstance(styles, dict):
        out = {d: 0.5 for d in _DIMS}
        for d in _DIMS:
            v = styles.get(d)
            if isinstance(v, (int, float)):
                out[d] = max(0.0, min(1.0, float(v)))
        return out
    out = {d: 0.5 for d in _DIMS}
    for d in profile.get("high", []) or []:
        if d in out:
            out[d] = 1.0
    for d in profile.get("low", []) or []:
        if d in out:
            out[d] = 0.0
    return out


def compute_behavior_fit(jd_text: str, profile: dict | None = None) -> dict:
    """给定 JD 文本 + 候选画像，返回 behavior_fit 诊断。

    返回：
      {
        "score": float,            # 0~1，中性 0.5
        "implied_dims": list,      # JD 隐含的行为维度（去重，顺序 D/I/S/C）
        "matched": list,           # 候选强匹配的关键词
        "gaps": list,              # 候选弱（缺口）的关键词
      }
    """
    signals = _profile_signals(profile)
    text = (jd_text or "").lower()
    implied: dict[str, list[str]] = {d: [] for d in _DIMS}
    for kw, dim in JD_BEHAVIOR_MAP.items():
        if kw.lower() in text:
            implied[dim].append(kw)
    implied_dims = [d for d in _DIMS if implied[d]]
    if not implied_dims:
        return {"score": 0.5, "implied_dims": [], "matched": [], "gaps": []}
    matched: list[str] = []
    gaps: list[str] = []
    fit = 0.0
    total = 0.0
    for d in implied_dims:
        for kw in implied[d]:
            s = signals[d]
            total += 1.0
            if s >= 0.5:
                fit += s          # 强匹配贡献其强度
                matched.append(kw)
            else:
                fit += max(0.0, s)  # 弱项：缺口，按强度计（不取负）
                gaps.append(kw)
    score = fit / total if total else 0.5
    return {
        "score": round(score, 3),
        "implied_dims": implied_dims,
        "matched": matched,
        "gaps": gaps,
    }


def load_behavioral_profile(path: str | None) -> dict:
    """读取候选行为画像 JSON（可选）。缺失/损坏 → 返回空 dict（中性）。"""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}
