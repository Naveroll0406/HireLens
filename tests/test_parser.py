"""Unit tests for processing/parser.py — pure regex extraction, no network."""

from __future__ import annotations

from processing.parser import (
    detect_hiring_signal,
    extract_emails,
    extract_experience,
    extract_locations,
    extract_skills,
)


class TestExperience:
    def test_range_hyphen(self):
        assert extract_experience("Looking for 2-4 years experience") == (2, 4)

    def test_range_to_word(self):
        assert extract_experience("needs 2 to 4 years") == (2, 4)

    def test_range_decimal(self):
        assert extract_experience("0.5 - 2 years") == (0, 2)

    def test_plus(self):
        assert extract_experience("3+ years required") == (3, None)

    def test_fresher(self):
        assert extract_experience("Freshers welcome to apply") == (0, 1)

    def test_none_when_absent(self):
        assert extract_experience("Great opportunity, apply now") == (None, None)

    def test_garbage_separator_not_matched(self):
        # The old [-–to]+ char-class bug matched "2ttto4"; the fix must not.
        assert extract_experience("2ttto4 years") == (None, None)


class TestLocations:
    def test_canonical_match(self):
        assert "Bangalore" in extract_locations("Role based in Bangalore")

    def test_alias_blr(self):
        assert extract_locations("Hiring in BLR") == ["Bangalore"]

    def test_alias_hyd(self):
        assert extract_locations("Position in HYD") == ["Hyderabad"]

    def test_alias_maps_to_canonical_once(self):
        # "Bangalore" and "BLR" in the same text should not duplicate.
        assert extract_locations("Bangalore (BLR) office").count("Bangalore") == 1

    def test_no_false_substring(self):
        # "hyd" must not fire inside "hydrogen".
        assert "Hyderabad" not in extract_locations("We work on hydrogen fuel")

    def test_empty_when_absent(self):
        assert extract_locations("Fully distributed team") == []


class TestSkills:
    def test_finds_known_skills(self):
        skills = extract_skills("Must know Python and LangChain for RAG work")
        assert "Python" in skills
        assert "LangChain" in skills
        assert "RAG" in skills


class TestEmails:
    def test_extracts_and_lowercases(self):
        assert extract_emails("Send CV to Hiring@Acme.com") == ["hiring@acme.com"]

    def test_none_when_absent(self):
        assert extract_emails("No contact here") == []


class TestHiringSignal:
    def test_positive(self):
        ok, conf = detect_hiring_signal("We are hiring an AI Engineer! Apply now.")
        assert ok is True
        assert conf > 0

    def test_open_to_work_rejected(self):
        ok, conf = detect_hiring_signal("I am open to work, please review my resume.")
        assert ok is False
        assert conf == 0.0

    def test_non_hiring_content(self):
        ok, _ = detect_hiring_signal("Join our webinar about the AI ecosystem.")
        assert ok is False
