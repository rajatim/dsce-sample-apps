import argparse
import sys
from pathlib import Path


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))

from sqlalchemy.orm import sessionmaker

from database import build_engine
from legacy_import.importer import import_snapshot
from legacy_import.reader import load_legacy_snapshot


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Import legacy loan data")
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def _print_report(report, anomalies, apply):
    print(f"mode={'apply' if apply else 'dry-run'}")
    for field in (
        "users_seen",
        "applications_seen",
        "events_seen",
        "anomalies_seen",
        "users_inserted",
        "applications_inserted",
        "events_inserted",
        "anomalies_inserted",
    ):
        print(f"{field}={getattr(report, field)}")
    print(f"total_inserted={report.total_inserted}")
    for anomaly in sorted(anomalies, key=lambda item: (item.kind, item.source_id)):
        print(f"anomaly={anomaly.kind}:{anomaly.source_id}")


def main(argv=None):
    args = _parse_args(argv)
    engine = None
    try:
        snapshot = load_legacy_snapshot(args.sqlite, args.logs)
        engine = build_engine(args.database_url)
        session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
        )
        report = import_snapshot(snapshot, session_factory, apply=args.apply)
        _print_report(report, snapshot.anomalies, args.apply)
        return 0
    except Exception:
        print(
            "Migration failed: invalid legacy data or target database error",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
