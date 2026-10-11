"""Copy an existing SQLite database to Railway's mounted volume safely."""

import argparse
import os
import sqlite3
import sys
from pathlib import Path


def copy_database(source: Path, destination: Path) -> dict[str, int]:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source database does not exist: {source}")
    if destination.exists():
        raise FileExistsError(
            f"Destination already exists; refusing to overwrite it: {destination}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        destination,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    os.close(descriptor)
    source_db: sqlite3.Connection | None = None
    destination_db: sqlite3.Connection | None = None
    try:
        source_db = sqlite3.connect(source, timeout=30)
        destination_db = sqlite3.connect(destination, timeout=30)
        source_db.execute("PRAGMA busy_timeout=30000")
        destination_db.execute("PRAGMA busy_timeout=30000")
        source_db.backup(destination_db, pages=256, sleep=0.01)
        destination_db.commit()
        integrity = destination_db.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise sqlite3.DatabaseError("Copied database failed integrity_check.")
        table_names = [
            row[0]
            for row in destination_db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        counts = {
            name: destination_db.execute(
                f'SELECT COUNT(*) FROM "{name}"'
            ).fetchone()[0]
            for name in table_names
        }
        source_counts = {
            name: source_db.execute(
                f'SELECT COUNT(*) FROM "{name}"'
            ).fetchone()[0]
            for name in table_names
        }
        if counts != source_counts:
            raise sqlite3.DatabaseError(
                "Source and copied database table counts do not match."
            )
        return counts
    except BaseException:
        if destination_db is not None:
            destination_db.close()
            destination_db = None
        if source_db is not None:
            source_db.close()
            source_db = None
        destination.unlink(missing_ok=True)
        raise
    finally:
        if destination_db is not None:
            destination_db.close()
        if source_db is not None:
            source_db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Existing SQLite database path on the current Railway deployment",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("/data/school_notes.db"),
        help="New database path on the Railway Volume (default: /data/school_notes.db)",
    )
    args = parser.parse_args()
    try:
        counts = copy_database(args.source, args.destination)
    except Exception as exc:
        print(
            f"Database copy failed ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 1
    print(
        f"Verified SQLite copy created at {args.destination}; "
        f"{len(counts)} tables; {sum(counts.values())} rows."
    )
    print("The source database was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
