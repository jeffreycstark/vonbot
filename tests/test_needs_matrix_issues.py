"""Regression tests: students with an unrecognized major must be reported,
not silently returned as 'needs nothing'."""
import pandas as pd
import pytest

import logic.course_matching as cm


@pytest.fixture
def stub_sources(monkeypatch):
    """Stub out CSV/DB access so the matrix can be built offline."""
    reqs = pd.DataFrame({
        "course_code": ["ENGL-110", "ACCT-300", "IR-201"],
        "BAD": ["X", "X", ""], "THM": ["", "", ""], "FIN": ["", "X", ""],
        "TES": ["X", "", ""], "INT": ["X", "", "X"],
        "course_title": ["a", "b", "c"],
    })
    monkeypatch.setattr(cm, "load_requirements", lambda: reqs)
    monkeypatch.setattr(cm, "load_prerequisites_data", lambda: None)
    monkeypatch.setattr(cm, "get_bulk_transcripts", lambda ids: {})
    return reqs


def _student(sid, name, major):
    return {"StudentId": sid, "Name": name, "MajorCode": major,
            "Email": "", "Cohort": "", "LastActiveDate": "2026/06/29"}


def test_unmapped_majors_are_reported(stub_sources):
    students = pd.DataFrame([
        _student("1", "Valid", "TES-68E"),
        _student("2", "Tourism", "TOU-68M"),
        _student("3", "Blank", ""),
    ])

    needs_df, issues = cm.generate_needs_matrix(students)

    assert {u["StudentId"] for u in issues["unmapped"]} == {"2", "3"}
    assert {u["Prefix"] for u in issues["unmapped"]} == {"TOU", "(blank)"}
    # Unmapped students stay in the matrix - they are reported, not dropped
    assert len(needs_df) == 3


def test_all_valid_majors_report_nothing(stub_sources):
    students = pd.DataFrame([
        _student("1", "Tes", "TES-68E"),
        _student("2", "Int", "INT-68E"),
    ])

    _, issues = cm.generate_needs_matrix(students)

    assert issues["unmapped"] == []
    assert issues["requirements_missing"] is False


def test_missing_requirements_file_is_flagged(monkeypatch):
    monkeypatch.setattr(cm, "load_requirements", lambda: pd.DataFrame())
    monkeypatch.setattr(cm, "load_prerequisites_data", lambda: None)
    monkeypatch.setattr(cm, "get_bulk_transcripts", lambda ids: {})

    _, issues = cm.generate_needs_matrix(
        pd.DataFrame([_student("1", "Tes", "TES-68E")]))

    assert issues["requirements_missing"] is True


def test_empty_student_list_returns_pair(stub_sources):
    needs_df, issues = cm.generate_needs_matrix(pd.DataFrame())

    assert needs_df.empty
    assert issues == {"unmapped": [], "requirements_missing": False}


@pytest.mark.parametrize("major_code,expected", [
    ("TES-53E", "TES"), ("COMP-66M", "COMP"), ("BAD-68E", "BAD"),
    ("NA", "NA"), ("", ""), (None, ""),
])
def test_get_major_prefix(major_code, expected):
    assert cm.get_major_prefix(major_code) == expected
