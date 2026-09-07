"""
Scheduler — two cron jobs:
  1. Daily pipeline  — every day at 00:00 (ingest + feature builder)
  2. Monthly retrain — 1st of every month at 00:00

Run with:
    python -m app.jobs.scheduler

Keep this process alive (e.g. as a background service or alongside uvicorn).
"""

import logging
import sys
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def run_daily_pipeline() -> None:
    log.info("=== DAILY PIPELINE START ===")
    try:
        from app.jobs.ingest import run_all
        from app.jobs.feature_builder import build_features

        results = run_all()
        failures = [s for s, r in results.items() if not r.ok]
        for source, r in results.items():
            status = "OK" if r.ok else f"FAILED ({r.error})"
            log.info("  ingest %-22s %s", source, status)

        if failures:
            log.warning(
                "%d scraper(s) failed, forward-filled: %s", len(failures), failures
            )

        build_features()
        log.info("=== DAILY PIPELINE COMPLETE ===")
    except Exception:
        log.exception("Daily pipeline crashed")


def run_monthly_retrain() -> None:
    log.info("=== MONTHLY RETRAIN START ===")
    try:
        from app.jobs.retrain import run_retrain

        results = run_retrain()
        if "error" in results:
            log.warning("Retrain skipped: %s", results["error"])
        else:
            for idx, metrics in results.items():
                log.info(
                    "  retrain %-5s  MAE new=%.1f current=%s  promoted=%s",
                    idx,
                    metrics.get("new_mae", -1),
                    metrics.get("current_mae", "n/a"),
                    metrics.get("promoted", False),
                )
        log.info("=== MONTHLY RETRAIN COMPLETE ===")
    except Exception:
        log.exception("Monthly retrain crashed")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SAGAR job scheduler")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run both jobs immediately and exit (for testing)",
    )
    parser.add_argument(
        "--daily", action="store_true", help="Run only the daily pipeline now and exit"
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Run only the monthly retrain now and exit",
    )
    args = parser.parse_args()

    if args.now:
        log.info("--now flag: running both jobs immediately")
        run_daily_pipeline()
        run_monthly_retrain()
        log.info("Done.")
        sys.exit(0)

    if args.daily:
        run_daily_pipeline()
        sys.exit(0)

    if args.retrain:
        run_monthly_retrain()
        sys.exit(0)

    # Normal mode — start the blocking scheduler
    scheduler = BlockingScheduler(timezone="UTC")

    # Daily at 00:00 UTC every day
    scheduler.add_job(
        run_daily_pipeline,
        trigger=CronTrigger(hour=0, minute=0),
        id="daily_pipeline",
        name="Daily ingest + feature builder",
        replace_existing=True,
    )

    # Monthly: 1st of every month at 00:00 UTC
    scheduler.add_job(
        run_monthly_retrain,
        trigger=CronTrigger(day=1, hour=0, minute=0),
        id="monthly_retrain",
        name="Monthly model retrain",
        replace_existing=True,
    )

    log.info("Scheduler started. Jobs:")
    log.info("  daily_pipeline  — every day        at 00:00 UTC")
    log.info("  monthly_retrain — 1st of the month at 00:00 UTC")
    log.info("  (run with --now to fire both jobs immediately)")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")
