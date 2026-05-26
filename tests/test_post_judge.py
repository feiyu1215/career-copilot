"""post_judge.py 单元测试 — 覆盖确定性后处理的纯函数逻辑"""

import sys
from pathlib import Path

# 让 import 能找到 scripts/
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from post_judge import (
    detect_english_requirement,
    apply_english_penalty,
    detect_core_team,
    apply_core_team_penalty,
    detect_tech_strong,
    apply_tech_penalty,
    enforce_distribution,
    post_judge,
)


# ============================================================
# detect_english_requirement
# ============================================================

class TestDetectEnglishRequirement:
    def test_fluent_level(self):
        assert detect_english_requirement("Fluent in English required") == "fluent"

    def test_fluent_chinese(self):
        assert detect_english_requirement("英语流利，能进行日常沟通") == "fluent"

    def test_preferred_level(self):
        assert detect_english_requirement("CET-6 优先") == "preferred"

    def test_preferred_bilingual(self):
        assert detect_english_requirement("bilingual communication skills") == "preferred"

    def test_implicit_global(self):
        assert detect_english_requirement("Join our global team in Singapore") == "implicit"

    def test_implicit_tiktok(self):
        assert detect_english_requirement("TikTok 商业化产品经理") == "implicit"

    def test_implicit_crossborder(self):
        assert detect_english_requirement("跨境电商运营") == "implicit"

    def test_no_requirement(self):
        assert detect_english_requirement("负责推荐算法迭代") is None

    def test_priority_fluent_over_preferred(self):
        # 同时包含 fluent 和 preferred 信号时，应返回更严格的
        text = "Fluent in English, CET-6 is a plus"
        assert detect_english_requirement(text) == "fluent"


# ============================================================
# apply_english_penalty
# ============================================================

class TestApplyEnglishPenalty:
    def _make_job(self, score: float, tier: str = "A") -> dict:
        return {"job_id": "T1", "score": score, "tier": tier}

    def test_fluent_caps_at_40(self):
        job = self._make_job(92)
        result = apply_english_penalty(job, "basic", "fluent")
        assert result["score"] == 40
        assert result["tier"] == "C"

    def test_fluent_no_penalty_for_fluent_candidate(self):
        job = self._make_job(92)
        result = apply_english_penalty(job, "fluent", "fluent")
        assert result["score"] == 92  # 未变

    def test_preferred_penalty_for_basic(self):
        job = self._make_job(85)
        result = apply_english_penalty(job, "basic", "preferred")
        assert result["score"] == 70  # min(85-15, 70) = 70
        assert result["tier"] == "B"

    def test_implicit_small_penalty_for_unknown(self):
        job = self._make_job(90)
        result = apply_english_penalty(job, "unknown", "implicit")
        assert result["score"] == 85  # min(90-5, 85) = 85


# ============================================================
# detect_core_team
# ============================================================

class TestDetectCoreTeam:
    def test_generic_signal(self):
        assert detect_core_team("加入我们的核心团队") is True

    def test_strategic_signal(self):
        assert detect_core_team("S级战略项目") is True

    def test_custom_signal_from_profile(self):
        profile = {"core_team_signals": ["豆包", "火山方舟"]}
        assert detect_core_team("豆包大模型团队", profile) is True

    def test_no_signal(self):
        assert detect_core_team("普通业务线运营岗") is False

    def test_no_profile(self):
        assert detect_core_team("基础架构团队招人", None) is True


# ============================================================
# apply_core_team_penalty
# ============================================================

class TestApplyCoreTeamPenalty:
    def _make_job(self, score: float, tier: str = "A") -> dict:
        return {"job_id": "T1", "score": score, "tier": tier}

    def test_weak_education_caps_60(self):
        job = self._make_job(95)
        result = apply_core_team_penalty(job, "weak", True)
        assert result["score"] == 60
        assert result["tier"] == "C"

    def test_medium_education_caps_75(self):
        job = self._make_job(90)
        result = apply_core_team_penalty(job, "medium", True)
        assert result["score"] == 75
        assert result["tier"] == "B"

    def test_strong_education_no_change(self):
        job = self._make_job(95)
        result = apply_core_team_penalty(job, "strong", True)
        assert result["score"] == 95
        assert result["tier"] == "A"

    def test_not_core_team_no_change(self):
        job = self._make_job(95)
        result = apply_core_team_penalty(job, "weak", False)
        assert result["score"] == 95


# ============================================================
# detect_tech_strong
# ============================================================

class TestDetectTechStrong:
    def test_coding_ability(self):
        assert detect_tech_strong("需要具备编程能力，熟悉 Python") is True

    def test_technical_pm(self):
        assert detect_tech_strong("技术产品经理，需要 technical background") is True

    def test_no_tech_requirement(self):
        assert detect_tech_strong("负责市场策略制定和品牌推广") is False


# ============================================================
# apply_tech_penalty
# ============================================================

class TestApplyTechPenalty:
    def test_penalty_when_no_tech(self):
        job = {"job_id": "T1", "score": 80, "tier": "A"}
        result = apply_tech_penalty(job, has_tech=False, is_tech_strong=True)
        assert result["score"] == 70

    def test_no_penalty_when_has_tech(self):
        job = {"job_id": "T1", "score": 80, "tier": "A"}
        result = apply_tech_penalty(job, has_tech=True, is_tech_strong=True)
        assert result["score"] == 80

    def test_no_penalty_when_not_tech_strong(self):
        job = {"job_id": "T1", "score": 80, "tier": "A"}
        result = apply_tech_penalty(job, has_tech=False, is_tech_strong=False)
        assert result["score"] == 80


# ============================================================
# enforce_distribution
# ============================================================

class TestEnforceDistribution:
    def test_demotes_excess_a_tier(self):
        # 20 个岗位，max_a_ratio=0.25 → max_a_count = max(3, 5) = 5
        jobs = [
            {"job_id": f"J{i}", "score": 95 - i, "tier": "A"}
            for i in range(8)
        ] + [
            {"job_id": f"B{i}", "score": 70 - i, "tier": "B"}
            for i in range(12)
        ]
        result = enforce_distribution(jobs, max_a_ratio=0.25)
        a_count = sum(1 for j in result if j["tier"] == "A")
        assert a_count == 5  # 8 → 5

    def test_no_demotion_when_within_limit(self):
        jobs = [
            {"job_id": "J1", "score": 95, "tier": "A"},
            {"job_id": "J2", "score": 90, "tier": "A"},
            {"job_id": "B1", "score": 70, "tier": "B"},
        ] + [{"job_id": f"C{i}", "score": 50, "tier": "C"} for i in range(17)]
        result = enforce_distribution(jobs, max_a_ratio=0.25)
        a_count = sum(1 for j in result if j["tier"] == "A")
        assert a_count == 2  # 不变，在 max(3, 5) 范围内


# ============================================================
# post_judge (集成级)
# ============================================================

class TestPostJudge:
    def test_full_pipeline(self):
        """确保 post_judge 不崩溃，能正确应用多规则"""
        jobs = [
            {
                "job_id": "J1", "title": "TikTok PM", "score": 92, "tier": "A",
                "full_text": "TikTok 商业化产品经理，英语流利，核心团队",
                "risks": [], "match_reasons": [],
            },
            {
                "job_id": "J2", "title": "后端开发", "score": 85, "tier": "B",
                "full_text": "负责推荐系统后端开发，3年经验",
                "risks": [], "match_reasons": [],
            },
        ]
        profile = {
            "english_evidence": {"level": "basic"},
            "education": {"tier": "medium"},
            "core_experiences": [
                {"scenario": "AI产品", "signal_words": ["AI"], "what_i_did": "做产品"}
            ],
            "core_team_signals": [],
        }
        result = post_judge(jobs, profile)
        # J1 应被英语硬门槛 + 核心团队同时惩罚
        j1 = next(j for j in result if j["job_id"] == "J1")
        assert j1["score"] < 92
        assert j1["tier"] != "A"
        assert len(j1.get("post_penalties", [])) > 0
        # J2 应基本不受影响（无英语/核心团队信号）
        j2 = next(j for j in result if j["job_id"] == "J2")
        assert j2["score"] == 85
