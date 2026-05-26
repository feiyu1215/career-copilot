"""pre_filter.py 单元测试 — 覆盖确定性预过滤的纯函数逻辑"""

import sys
from pathlib import Path

# 让 import 能找到 scripts/
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from pre_filter import (
    detect_experience_requirement,
    has_english_hard_gate,
    extract_direction_keywords,
    compute_direction_score,
    pre_filter,
    DEFAULT_FILTER_CONFIG,
)


# ============================================================
# detect_experience_requirement
# ============================================================

class TestDetectExperienceRequirement:
    def test_chinese_pattern(self):
        assert detect_experience_requirement("需要5年以上工作经验") == 5

    def test_chinese_pattern_at_least(self):
        assert detect_experience_requirement("至少3年相关经历") == 3

    def test_chinese_pattern_and_above(self):
        assert detect_experience_requirement("8年及以上产品经验") == 8

    def test_english_pattern(self):
        assert detect_experience_requirement("5+ years of experience in backend") == 5

    def test_english_pattern_no_plus(self):
        assert detect_experience_requirement("3 years experience required") == 3

    def test_no_requirement(self):
        assert detect_experience_requirement("熟悉 Python 开发") is None

    def test_empty_string(self):
        assert detect_experience_requirement("") is None


# ============================================================
# has_english_hard_gate
# ============================================================

class TestHasEnglishHardGate:
    def test_fluent_english(self):
        assert has_english_hard_gate("Fluent in English is required") is True

    def test_chinese_signal(self):
        assert has_english_hard_gate("全英文工作环境，需要英语流利") is True

    def test_native_english(self):
        assert has_english_hard_gate("Native English speaker preferred") is True

    def test_no_english_requirement(self):
        assert has_english_hard_gate("熟悉推荐算法，有大数据经验优先") is False

    def test_empty_string(self):
        assert has_english_hard_gate("") is False

    def test_case_insensitive(self):
        assert has_english_hard_gate("ENGLISH AS WORKING LANGUAGE") is True


# ============================================================
# extract_direction_keywords
# ============================================================

class TestExtractDirectionKeywords:
    def test_basic_extraction(self):
        profile = {
            "direction_anchors": ["AI产品", "推荐系统"],
            "core_experiences": [
                {
                    "scenario": "搜索推荐优化",
                    "signal_words": ["CTR", "召回率", "排序模型"],
                    "transferable_to": ["广告算法", "内容分发"],
                    "NOT_transferable_to": ["芯片设计", "硬件开发"],
                }
            ],
            "hard_negatives": ["前端开发", "iOS 开发"],
        }
        pos, neg = extract_direction_keywords(profile)
        # 正向应包含 direction_anchors + signal_words + scenario + transferable_to
        assert "AI产品" in pos
        assert "CTR" in pos
        assert "搜索推荐优化" in pos
        assert "广告算法" in pos
        # 负向应包含 hard_negatives + NOT_transferable_to
        assert "前端开发" in neg
        assert "芯片设计" in neg

    def test_empty_profile(self):
        pos, neg = extract_direction_keywords({})
        assert pos == []
        assert neg == []

    def test_deduplication(self):
        profile = {
            "direction_anchors": ["AI产品", "AI产品"],
            "core_experiences": [],
            "hard_negatives": [],
        }
        pos, neg = extract_direction_keywords(profile)
        assert pos.count("AI产品") == 1


# ============================================================
# compute_direction_score
# ============================================================

class TestComputeDirectionScore:
    def test_full_match(self):
        score, matched_pos, matched_neg = compute_direction_score(
            "本岗位需要 CTR 优化和排序模型经验",
            ["CTR", "排序模型"],
            ["芯片设计"],
        )
        assert score == 1.0
        assert "CTR" in matched_pos
        assert "排序模型" in matched_pos
        assert matched_neg == []

    def test_negative_penalty(self):
        score, matched_pos, matched_neg = compute_direction_score(
            "芯片设计工程师，需要 CTR 相关",
            ["CTR"],
            ["芯片设计"],
        )
        # pos_rate = 1.0, neg_penalty = 0.15 → score = 0.85
        assert score == 0.85
        assert "芯片设计" in matched_neg

    def test_no_match(self):
        score, matched_pos, matched_neg = compute_direction_score(
            "护士岗位，三甲医院",
            ["CTR", "推荐系统"],
            [],
        )
        assert score == 0.0
        assert matched_pos == []

    def test_empty_keywords(self):
        score, _, _ = compute_direction_score("任意文本", [], [])
        assert score == 0.5  # 无正向词时默认 0.5


# ============================================================
# pre_filter (集成级)
# ============================================================

class TestPreFilter:
    def _make_job(self, title: str, text: str) -> dict:
        return {"job_id": "TEST_1", "title": title, "full_text": text}

    def test_exclude_intern(self):
        jobs = [self._make_job("算法实习生", "实习岗位，日薪200")]
        profile = {"english_evidence": {"level": "fluent"}, "core_experiences": []}
        filtered, stats = pre_filter(jobs, profile, config={"include_intern": False, "include_outsource": False, "max_year_requirement": 10})
        assert stats["excluded_intern"] == 1
        assert len(filtered) == 0

    def test_include_intern(self):
        jobs = [self._make_job("算法实习生", "实习岗位，日薪200")]
        profile = {"english_evidence": {"level": "fluent"}, "core_experiences": []}
        filtered, stats = pre_filter(jobs, profile, config={"include_intern": True, "include_outsource": False, "max_year_requirement": 10})
        assert stats["excluded_intern"] == 0
        assert len(filtered) == 1

    def test_exclude_outsource(self):
        jobs = [self._make_job("外包运维", "外包岗位，驻场服务")]
        profile = {"english_evidence": {"level": "fluent"}, "core_experiences": []}
        filtered, stats = pre_filter(jobs, profile, config={"include_intern": False, "include_outsource": False, "max_year_requirement": 10})
        assert stats["excluded_outsource"] == 1

    def test_exclude_by_year_requirement(self):
        jobs = [self._make_job("高级架构师", "需要15年以上工作经验")]
        profile = {"english_evidence": {"level": "fluent"}, "core_experiences": []}
        filtered, stats = pre_filter(jobs, profile, config={"include_intern": False, "include_outsource": False, "max_year_requirement": 10})
        assert stats["excluded_experience"] == 1

    def test_pass_normal_job(self):
        jobs = [self._make_job("AI 产品经理", "负责推荐系统产品规划，3年以上经验")]
        profile = {
            "english_evidence": {"level": "fluent"},
            "core_experiences": [{"scenario": "推荐系统", "signal_words": ["推荐"], "NOT_transferable_to": [], "transferable_to": []}],
            "hard_negatives": [],
            "direction_anchors": ["AI产品"],
        }
        filtered, stats = pre_filter(jobs, profile, config=DEFAULT_FILTER_CONFIG)
        assert len(filtered) == 1
        assert "pre_filter_meta" in filtered[0]

    def test_english_hard_gate_excludes_basic_candidate(self):
        jobs = [self._make_job("PM", "全英文工作环境，英语作为工作语言")]
        profile = {"english_evidence": {"level": "basic"}, "core_experiences": []}
        filtered, stats = pre_filter(jobs, profile, exclude_english_hard=True, config=DEFAULT_FILTER_CONFIG)
        assert stats["excluded_english"] == 1
