"""Golden corpus: real-shaped posts with expected extraction + accept/reject.

Every regex tweak in processing/ runs against this file. When a post is
misclassified in production, add it here (with the expected values) and fix
the rule until the whole corpus passes — that is the tuning loop.

Fixture format (tests/fixtures/posts.jsonl), one JSON object per line:
  id        short unique name
  keyword   the search keyword that "found" the post
  content   the post text
  expect    any of:
              role                exact extracted title
              exp                 [min, max] (null for open ends)
              locations           exact list (order-insensitive)
              locations_include   subset that must be present
              is_hiring           bool
              senior              bool
              accept              bool — passes the default score threshold
              skills_include      subset of extracted skills
              emails              exact list
              primary_url_contains substring of the primary URL
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from processing.filters import apply_all_filters
from processing.parser import parse_post

FIXTURE = Path(__file__).parent / "fixtures" / "posts.jsonl"


def _load_cases() -> list[dict]:
    cases = []
    with FIXTURE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                cases.append(json.loads(line))
    return cases


CASES = _load_cases()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_post(case, make_raw, monkeypatch):
    # Never hit the network for shorteners in tests.
    monkeypatch.setattr("processing.parser.resolve_shortened_url", lambda url, timeout=None: url)

    raw = make_raw(content=case["content"], keyword_matched=case.get("keyword", "AI Engineer"),
                   post_urn=f"urn:li:activity:{case['id']}")
    parsed = parse_post(raw)
    accepted = apply_all_filters(parsed) is not None
    exp = case["expect"]
    ctx = f"[{case['id']}] role={parsed.role!r} exp=({parsed.experience_min},{parsed.experience_max}) " \
          f"loc={parsed.locations} hiring={parsed.is_hiring} score={parsed.relevance_score} " \
          f"breakdown={parsed.filter_reason}"

    if "role" in exp:
        assert parsed.role == exp["role"], ctx
    if "exp" in exp:
        assert [parsed.experience_min, parsed.experience_max] == exp["exp"], ctx
    if "locations" in exp:
        assert sorted(parsed.locations) == sorted(exp["locations"]), ctx
    if "locations_include" in exp:
        assert set(exp["locations_include"]) <= set(parsed.locations), ctx
    if "is_hiring" in exp:
        assert parsed.is_hiring is exp["is_hiring"], ctx
    if "senior" in exp:
        assert parsed.is_senior_role is exp["senior"], ctx
    if "accept" in exp:
        assert accepted is exp["accept"], ctx
    if "skills_include" in exp:
        assert set(exp["skills_include"]) <= set(parsed.skills), ctx
    if "emails" in exp:
        assert parsed.emails == exp["emails"], ctx
    if "primary_url_contains" in exp:
        assert parsed.primary_url and exp["primary_url_contains"] in parsed.primary_url, ctx


def test_corpus_has_both_classes():
    """Guard against a corpus that only exercises one side of the threshold."""
    accepts = sum(1 for c in CASES if c["expect"].get("accept") is True)
    rejects = sum(1 for c in CASES if c["expect"].get("accept") is False)
    assert accepts >= 10 and rejects >= 10
