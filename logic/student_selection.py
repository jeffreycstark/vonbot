"""
Student selection logic with caching optimizations.

Key optimizations:
1. Cached student fetching (5 minute TTL)
2. Helper function to clear cache when needed
"""

import pandas as pd
import streamlit as st
from database.connection import db_cursor

STUDENT_COLUMNS = [
    "StudentId",
    "Name",
    "Email",
    "MajorCode",
    "Cohort",
    "LastActiveDate",
]


def get_cohort(major_code) -> str:
    """Extract the cohort from a BatchIDForDoctor value ('TES-53E' -> '53E').

    Splits on the first dash rather than slicing a fixed offset. Prefixes are
    not all three characters ('COMP-63E', 'ACCT-67E', 'F&B-68E'), and the old
    SUBSTRING(x, 5, 3) sliced the wrong window for those, yielding '-63'/'-67'.

    Returns "" when there is no dash to split on ('NA', '') - there is no
    cohort to report, and a blank sorts cleanly in the cohort filter.
    """
    if major_code is None or pd.isna(major_code):
        return ""
    _prefix, dash, cohort = str(major_code).strip().partition("-")
    return cohort.strip() if dash else ""


@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_active_students(months_back: int = 6):
    """
    Fetch students who have been active in the last X months.

    CACHED: This function hits the database only once per 5 minutes for each
    unique months_back value. Subsequent calls return cached data instantly.

    Cohort is derived from MajorCode in pandas (see get_cohort), not sliced
    positionally in SQL.

    Students with a blank BatchIDForDoctor are INCLUDED, with MajorCode and
    Cohort returned as empty strings rather than NULL. They cannot be matched
    to requirements, so generate_needs_matrix reports them as unmapped and the
    UI warns about them. Filtering them out here would hide them entirely.

    Args:
        months_back (int): Number of months to look back for activity.

    Returns:
        pd.DataFrame: DataFrame of active students.
    """
    query = """
    SELECT DISTINCT
        s.ID as StudentId,
        s.Name,
        s.schoolemail as Email,
        LTRIM(RTRIM(ISNULL(s.BatchIDForDoctor, ''))) as MajorCode,
        MAX(v.termstart) as LastActiveDate
    FROM vw_BAlatestgrade v
    JOIN Students s ON v.id = s.ID
    WHERE v.termstart >= CONVERT(varchar, DATEADD(month, -%d, GETDATE()), 111)
    GROUP BY s.ID, s.Name, s.schoolemail,
             LTRIM(RTRIM(ISNULL(s.BatchIDForDoctor, '')))
    ORDER BY LastActiveDate DESC
    """

    try:
        with db_cursor() as cursor:
            cursor.execute(query % months_back)
            data = cursor.fetchall()

            if not data:
                return pd.DataFrame(columns=STUDENT_COLUMNS)

            df = pd.DataFrame(data)
            df["Cohort"] = df["MajorCode"].apply(get_cohort)
            return df[STUDENT_COLUMNS]

    except Exception as e:
        print(f"Error fetching students: {e}")
        return pd.DataFrame(columns=STUDENT_COLUMNS)


def clear_student_cache():
    """
    Clear the student cache to force a fresh database query.

    Call this when you need to refresh student data immediately,
    such as after a data import or manual database update.
    """
    get_active_students.clear()