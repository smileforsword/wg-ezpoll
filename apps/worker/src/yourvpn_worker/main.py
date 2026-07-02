from __future__ import annotations

import argparse
from datetime import UTC, datetime
import logging
import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from yourvpn_core.config import AppSettings, load_settings
from yourvpn_core.db.models import Job
from yourvpn_core.db.session import create_db_engine, create_session_factory
from yourvpn_core.domain.enums import JobStatus
from yourvpn_core.health import HealthStatus, build_health_status
from yourvpn_core.logging import configure_logging
from yourvpn_core.modules.wg_runtime import WgAgentClient, WgRuntimeModule

LOGGER = logging.getLogger(__name__)


def build_worker_health(settings: AppSettings | None = None) -> HealthStatus:
    resolved_settings = settings or load_settings()
    return build_health_status(
        service="worker",
        settings=resolved_settings,
        details={
            "job_polling": "database",
            "database_url_configured": bool(resolved_settings.database_url),
        },
    )


def run_once(settings: AppSettings | None = None) -> HealthStatus:
    health = build_worker_health(settings)
    LOGGER.info("worker heartbeat status=%s", health.status)
    return health


def run_pending_job_once(
    settings: AppSettings | None = None,
    *,
    session_factory: sessionmaker[OrmSession] | None = None,
    wg_agent_client: WgAgentClient | None = None,
    worker_id: str | None = None,
) -> Job | None:
    resolved_settings = settings or load_settings()
    if session_factory is None:
        engine = create_db_engine(resolved_settings.database_url)
        session_factory = create_session_factory(engine)
    runtime = WgRuntimeModule(client=wg_agent_client)
    resolved_worker_id = worker_id or f"worker-{uuid4()}"
    with session_factory() as db:
        job = db.scalars(
            select(Job)
            .where(Job.status == JobStatus.PENDING.value)
            .where(Job.job_type.in_(
                [
                    "apply_peer",
                    "remove_peer",
                    "apply_firewall",
                    "reconcile_runtime_state",
                    "sample_wg_status",
                ]
            ))
            .order_by(Job.created_at)
            .limit(1)
        ).first()
        if job is None:
            return None
        job.status = JobStatus.RUNNING.value
        job.locked_by = resolved_worker_id
        job.locked_at = datetime.now(UTC)
        job.attempts += 1
        db.flush()
        try:
            _execute_job(db, job=job, settings=resolved_settings, runtime=runtime, client=wg_agent_client)
            runtime.mark_job_succeeded(job)
        except Exception as exc:
            runtime.mark_job_failed(job, exc)
        db.commit()
        db.refresh(job)
        db.expunge(job)
        return job


def _execute_job(
    db: OrmSession,
    *,
    job: Job,
    settings: AppSettings,
    runtime: WgRuntimeModule,
    client: WgAgentClient | None,
) -> None:
    payload = job.payload_json or {}
    if job.job_type == "apply_peer":
        runtime.apply_peer_for_device(
            db,
            device_id=str(payload["device_id"]),
            settings=settings,
            client=client,
        )
        return
    if job.job_type == "remove_peer":
        runtime.remove_peer_for_device(
            db,
            device_id=str(payload["device_id"]),
            settings=settings,
            client=client,
        )
        return
    if job.job_type == "apply_firewall":
        runtime.apply_firewall(db, settings=settings, client=client)
        return
    if job.job_type == "reconcile_runtime_state":
        runtime.reconcile(db, settings=settings, client=client)
        return
    if job.job_type == "sample_wg_status":
        runtime.sample_status(db, settings=settings, client=client)
        return
    raise ValueError(f"Unsupported job type: {job.job_type}")


def main() -> int:
    parser = argparse.ArgumentParser(description="WirePortal worker process.")
    parser.add_argument("--once", action="store_true", help="Run one heartbeat and exit.")
    parser.add_argument("--job-once", action="store_true", help="Claim and run one pending job, then exit.")
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds.")
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings, service="worker")

    if args.once:
        print(run_once(settings).model_dump_json())
        return 0
    if args.job_once:
        job = run_pending_job_once(settings)
        print("{}" if job is None else job.id)
        return 0

    LOGGER.info("worker started")
    while True:
        run_pending_job_once(settings)
        run_once(settings)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
