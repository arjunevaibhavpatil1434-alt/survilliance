import csv
import os
import sqlite3
import sys
from datetime import datetime

DB_PATH = "/home/server/sur-floders/faces.db"
EXPORT_DIR = "/home/server/sur-floders/attendance_exports"


def export_attendance(date_filter=None):
    os.makedirs(EXPORT_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if date_filter:
        rows = conn.execute(
            """
            SELECT person_name, date, time, timestamp
            FROM attendance
            WHERE date = ?
            ORDER BY timestamp
            """,
            (date_filter,)
        ).fetchall()

        filename = f"attendance_{date_filter}.csv"

    else:
        rows = conn.execute(
            """
            SELECT person_name, date, time, timestamp
            FROM attendance
            ORDER BY timestamp
            """
        ).fetchall()

        filename = f"attendance_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    conn.close()

    export_path = os.path.join(EXPORT_DIR, filename)

    with open(export_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Person Name", "Date", "Time", "Timestamp"])

        for row in rows:
            writer.writerow([
                row["person_name"],
                row["date"],
                row["time"],
                row["timestamp"]
            ])

    print(f"Exported {len(rows)} record(s) to {export_path}")

    return export_path


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    export_attendance(date_arg)
