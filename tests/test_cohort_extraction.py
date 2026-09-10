"""Cohort must be split on the dash, not sliced at a fixed offset.

The old SUBSTRING(BatchIDForDoctor, 5, 3) assumed a 3-character major prefix
and produced '-63' / '-67' for 4-character ones like COMP / ACCT.
"""
import pandas as pd
import pytest

from logic.student_selection import STUDENT_COLUMNS, get_cohort


@pytest.mark.parametrize("major_code,expected", [
    # 3-char prefixes - the case the old offset happened to get right
    ("TES-53E", "53E"),
    ("BAD-68E", "68E"),
    ("INT-63E", "63E"),
    # 4-char prefixes - the case the old offset got wrong ('-63', '-67')
    ("COMP-63E", "63E"),
    ("ACCT-67E", "67E"),
    ("COMP-68M", "68M"),
    # Odd prefixes seen in live data
    ("F&B-68E", "68E"),
    ("BAmin-66E", "66E"),
    # No dash: nothing to report
    ("NA", ""),
    ("", ""),
    (None, ""),
    # Whitespace and multi-dash values
    ("  TES-68E  ", "68E"),
    ("TES-68E-2", "68E-2"),
])
def test_get_cohort(major_code, expected):
    assert get_cohort(major_code) == expected


def test_get_cohort_never_returns_leading_dash():
    """The specific regression: a 4-char prefix must not yield '-NN'."""
    for code in ["COMP-63E", "ACCT-67E", "BAmin-66E"]:
        assert not get_cohort(code).startswith("-")


def test_get_cohort_handles_nan():
    """Blank majors arrive from the DB as '' but may become NaN via pandas."""
    series = pd.Series(["TES-68E", None, float("nan")], dtype=object)
    assert [get_cohort(v) for v in series] == ["68E", "", ""]


def test_student_columns_contract():
    """app.py selects these by name; the frame must always carry them."""
    assert STUDENT_COLUMNS == [
        "StudentId", "Name", "Email", "MajorCode", "Cohort", "LastActiveDate"]
