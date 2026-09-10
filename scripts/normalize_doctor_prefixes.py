"""Normalize BatchIDForDoctor major prefixes to the codes vonbot matches on.

The clerk enters full program names ('TESOL-67E', 'BAmin-66E'), but the
curriculum requirements CSV has columns named 'TES' and 'BAD'. A student whose
prefix has no matching column silently gets zero required courses.

This rewrites the prefix in place, preserving the cohort suffix:
    TESOL-67E -> TES-67E        BAmin-66E -> BAD-66E
    TOU-68M   -> THM-68M

Dry run by default. Nothing is written without --apply.

    python scripts/normalize_doctor_prefixes.py            # preview
    python scripts/normalize_doctor_prefixes.py --apply    # write

Every change is saved to a timestamped backup CSV before the write, and
--revert replays that CSV to restore the previous values.
"""
import argparse
import csv
import sys
from datetime import datetime

from database.connection import get_db_connection

# Prefixes the clerk uses -> the column name in curriculum_requirements2.csv.
# Confirmed with the data owner: BAmin students take the BAD major requirements.
PREFIX_MAP = {
    "TESOL": "TES",
    "BAMIN": "BAD",
    "TOU": "THM",
}

SELECT_SQL = """
SELECT s.ID, LTRIM(RTRIM(s.BatchIDForDoctor)) AS Doctor, s.ModifiedDate
FROM Students s
WHERE s.BatchIDForDoctor IS NOT NULL AND LTRIM(RTRIM(s.BatchIDForDoctor)) <> ''
"""

UPDATE_SQL = """
UPDATE Students
SET BatchIDForDoctor = %s, ModifiedDate = GETDATE()
WHERE ID = %s
"""


def normalize(value: str):
    """Return the canonical value, or None if this row needs no change."""
    prefix, dash, cohort = value.partition("-")
    canonical = PREFIX_MAP.get(prefix.strip().upper())
    if canonical is None or canonical == prefix.strip():
        return None
    return f"{canonical}-{cohort}" if dash else canonical


def find_changes(cursor):
    cursor.execute(SELECT_SQL)
    changes = []
    for row in cursor.fetchall():
        new_value = normalize(row["Doctor"])
        if new_value:
            changes.append({
                "ID": row["ID"],
                "OldDoctor": row["Doctor"],
                "NewDoctor": new_value,
                "OldModifiedDate": row["ModifiedDate"],
            })
    return changes


def write_backup(changes):
    path = f"backup_doctor_prefixes_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["ID", "OldDoctor", "NewDoctor", "OldModifiedDate"])
        writer.writeheader()
        writer.writerows(changes)
    return path


def summarize(changes):
    by_prefix = {}
    for c in changes:
        key = (c["OldDoctor"].partition("-")[0], c["NewDoctor"].partition("-")[0])
        by_prefix[key] = by_prefix.get(key, 0) + 1
    print(f"{len(changes)} rows need normalizing:\n")
    for (old, new), n in sorted(by_prefix.items(), key=lambda kv: -kv[1]):
        print(f"  {old:<8} -> {new:<5} {n:>4} rows")
    print("\nsample:")
    for c in changes[:8]:
        print(f"  {c['ID']:<8} {c['OldDoctor']:<12} -> {c['NewDoctor']}")
    if len(changes) > 8:
        print(f"  ... and {len(changes) - 8} more")


def apply_changes(conn, changes, column="NewDoctor"):
    cursor = conn.cursor(as_dict=True)
    try:
        for c in changes:
            cursor.execute(UPDATE_SQL, (c[column], c["ID"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(changes)


def revert(conn, path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(f"reverting {len(rows)} rows from {path}")
    applied = apply_changes(conn, rows, column="OldDoctor")
    print(f"reverted {applied} rows")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default is a dry run)")
    parser.add_argument("--revert", metavar="BACKUP_CSV",
                        help="restore OldDoctor values from a backup CSV")
    args = parser.parse_args()

    conn = get_db_connection()
    try:
        if args.revert:
            revert(conn, args.revert)
            return 0

        changes = find_changes(conn.cursor(as_dict=True))
        if not changes:
            print("Nothing to normalize - every prefix already matches.")
            return 0

        summarize(changes)

        if not args.apply:
            print("\nDRY RUN - nothing written. Re-run with --apply to commit.")
            return 0

        backup = write_backup(changes)
        print(f"\nbackup written: {backup}")
        applied = apply_changes(conn, changes)
        print(f"committed {applied} rows")

        remaining = find_changes(conn.cursor(as_dict=True))
        print(f"verification: {len(remaining)} rows still unnormalized "
              f"({'OK' if not remaining else 'PROBLEM'})")
        return 0 if not remaining else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
