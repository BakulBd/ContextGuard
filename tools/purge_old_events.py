"""Retention enforcement: delete event rows older than config's
``retention_days``. Structured events are already the privacy-friendly
alternative to raw video, but "we keep the DB forever" would quietly
defeat the point -- this is meant to run on a schedule (a systemd timer
or cron entry; see deploy/README.md), not just once by hand.

Usage:
    python tools/purge_old_events.py                 # use config.yaml's retention_days
    python tools/purge_old_events.py --days 14        # override
    python tools/purge_old_events.py --dry-run
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from contextguard.config import load_config, resolve_path
from contextguard.events import EventStore
from contextguard.logging_setup import get_logger

log = get_logger("purge")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=None, help="override config.yaml's retention_days")
    parser.add_argument("--dry-run", action="store_true", help="report what would be deleted without deleting it")
    args = parser.parse_args()

    config = load_config()
    days = args.days if args.days is not None else config.retention_days
    store = EventStore(resolve_path(config.db_path))

    if args.dry_run:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        count = store.count(time_to=cutoff)
        log.info("Dry run: %d event(s) older than %d days would be deleted (cutoff %s).", count, days, cutoff)
        return

    removed = store.purge_older_than(days)
    log.info("Purged %d event(s) older than %d days.", removed, days)


if __name__ == "__main__":
    main()
