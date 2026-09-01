"""Unit tests for processing/filters.py."""

from __future__ import annotations

from processing.filters import (
    apply_all_filters,
    filter_by_ai_role,
    filter_by_experience,
    filter_by_location,
)


class TestExperienceFilter:
    def test_overlap_accepted(self, make_parsed):
        p = make_parsed(experience_min=2, experience_max=4)
        ok, _ = filter_by_experience(p, user_min=0, user_max=10)
        assert ok is True

    def test_too_senior_rejected(self, make_parsed):
        p = make_parsed(experience_min=12, experience_max=15)
        ok, _ = filter_by_experience(p, user_min=0, user_max=10)
        assert ok is False

    def test_absent_accepted(self, make_parsed):
        p = make_parsed(experience_min=None, experience_max=None)
        ok, _ = filter_by_experience(p, user_min=0, user_max=10)
        assert ok is True


class TestLocationFilter:
    def test_absent_accepted(self, make_parsed):
        p = make_parsed(locations=[])
        ok, _ = filter_by_location(p)
        assert ok is True

    def test_target_match_accepted(self, make_parsed):
        p = make_parsed(locations=["Bangalore"])
        ok, _ = filter_by_location(p)
        assert ok is True

    def test_non_target_rejected(self, make_parsed):
        p = make_parsed(locations=["Berlin"])
        ok, _ = filter_by_location(p)
        assert ok is False


class TestAiRoleFilter:
    def test_ai_role_accepted(self, make_parsed):
        p = make_parsed(role="AI Engineer")
        ok, _ = filter_by_ai_role(p)
        assert ok is True

    def test_non_ai_role_rejected(self, make_parsed):
        p = make_parsed(role="Java Developer", content="Backend Java role, Spring Boot")
        ok, _ = filter_by_ai_role(p)
        assert ok is False

    def test_generic_role_with_ai_content_accepted(self, make_parsed):
        p = make_parsed(role=None, content="Software role building RAG with LangChain")
        ok, _ = filter_by_ai_role(p)
        assert ok is True


class TestApplyAllFilters:
    def test_full_pass_returns_filteredpost(self, make_parsed):
        p = make_parsed(
            role="AI Engineer",
            experience_min=2,
            experience_max=4,
            locations=["Bangalore"],
            is_hiring=True,
            content="We are hiring an AI Engineer in Bangalore, 2-4 years. Apply now.",
        )
        result = apply_all_filters(p)
        assert result is not None
        assert result.parsed is p

    def test_non_ai_role_returns_none(self, make_parsed):
        p = make_parsed(role="QA Engineer", is_hiring=True, content="Hiring QA Engineer")
        assert apply_all_filters(p) is None

    def test_not_hiring_returns_none(self, make_parsed):
        p = make_parsed(role="AI Engineer", is_hiring=False)
        assert apply_all_filters(p) is None
