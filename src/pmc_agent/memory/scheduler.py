from __future__ import annotations

from datetime import date, datetime, time, timedelta
import argparse
import os
import time as time_module

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.env import load_env_file
from pmc_agent.memory.daily_review import run_daily_memory_review


logger = get_logger(__name__)


def run_memory_review_scheduler(run_at: str | None = None, once: bool = False):
    load_env_file(override=False)
    target_time = _parse_run_time(run_at or os.getenv("PMC_AGENT_MEMORY_REVIEW_TIME") or "18:00")
    logger.info("memory review scheduler started", extra=log_extra("memory_review_scheduler_started", run_at=target_time.isoformat()))
    while True:
        now = datetime.now()
        next_run = _next_run_at(now, target_time)
        sleep_seconds = max(0.0, (next_run - now).total_seconds())
        logger.info(
            "memory review scheduler waiting",
            extra=log_extra("memory_review_scheduler_waiting", next_run=next_run.isoformat(), sleep_seconds=round(sleep_seconds, 2)),
        )
        if not once:
            time_module.sleep(sleep_seconds)
        result = run_daily_memory_review(review_date=next_run.date() if not once else date.today())
        logger.info(
            "memory review scheduler completed run",
            extra=log_extra(
                "memory_review_scheduler_run_completed",
                review_date=result.review_date,
                conversation_count=result.conversation_count,
                interaction_count=result.interaction_count,
                error_count=result.error_count,
                memory_count=result.memory_count,
                milvus_memory_count=result.milvus_memory_count,
                review_path=str(result.review_path),
            ),
        )
        if once:
            return result


def _next_run_at(now: datetime, run_time: time) -> datetime:
    candidate = datetime.combine(now.date(), run_time)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _parse_run_time(value: str) -> time:
    try:
        hour, minute = value.strip().split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except Exception as exc:
        raise ValueError("run time must use HH:MM format") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PMC memory review scheduler.")
    parser.add_argument("--run-at", help="Daily local time in HH:MM. Defaults to PMC_AGENT_MEMORY_REVIEW_TIME or 18:00.")
    parser.add_argument("--once", action="store_true", help="Run one review immediately and exit.")
    args = parser.parse_args()
    result = run_memory_review_scheduler(run_at=args.run_at, once=args.once)
    if result is not None:
        print(f"Review date: {result.review_date}")
        print(f"Conversations: {result.conversation_count}")
        print(f"Interactions: {result.interaction_count}")
        print(f"Errors: {result.error_count}")
        print(f"Memories written: {result.memory_count}")
        print(f"Milvus memories written: {result.milvus_memory_count}")
        print(f"Review path: {result.review_path}")
        print(f"Memory path: {result.memory_path}")


if __name__ == "__main__":
    main()
