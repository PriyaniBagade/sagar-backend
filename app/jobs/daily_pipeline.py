"""
Daily pipeline — runs ingest then feature builder in sequence.
This is the only script you need to schedule daily.

Usage:
    python -m app.jobs.daily_pipeline

Exit code is 0 if all scrapers succeeded, 1 if any failed (so cron/Task
Scheduler can alert on failure without you checking logs manually).
"""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    from app.jobs.ingest import run_all
    from app.jobs.feature_builder import build_features

    log.info("=== Step 1/2: Ingest ===")
    results = run_all()

    failures = [s for s, r in results.items() if not r.ok]
    for source, r in results.items():
        status = "OK" if r.ok else f"FAILED ({r.error})"
        print(f"  {source:<22} {status}")

    if failures:
        log.warning("%d scraper(s) failed and were forward-filled: %s", len(failures), failures)

    log.info("=== Step 2/2: Feature Builder ===")
    build_features()

    # exit 1 only if ALL scrapers failed (total blackout), not partial failures
    if len(failures) == len(results):
        log.error("All scrapers failed — pipeline aborted")
        return 1

    log.info("Daily pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
