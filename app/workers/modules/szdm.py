from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.core.time import utc_now
from app.domain.exceptions import NonRetryableTaskError
from app.infrastructure.datasource.relational.session import session_scope
from app.infrastructure.datasource.s3.client import S3ClientProvider
from app.infrastructure.repositories.szdm_repository import SzdmRepository
from app.workers.contracts import TaskHandler, WorkerTaskContext


def szdm_sub_handler(payload: dict[str, Any], context: WorkerTaskContext) -> dict[str, Any]:
    job_id = int(payload["job_id"])
    item_id = int(payload["item_id"])
    settings = get_settings()
    s3 = S3ClientProvider(bucket=settings.szdm_s3_bucket, root_dir=settings.szdm_s3_root_dir).build()

    try:
        return _execute_szdm_sub(job_id=job_id, item_id=item_id, s3=s3, context=context)
    except Exception as exc:
        error_code = getattr(exc, "error_code", None) or "SZDM_SUB_FAILED"
        error_message = str(getattr(exc, "message", exc))
        with session_scope() as session:
            SzdmRepository(session).mark_item_failed(
                item_id=item_id,
                error_code=error_code,
                error_message=error_message,
            )
        raise


def _execute_szdm_sub(
    *,
    job_id: int,
    item_id: int,
    s3,
    context: WorkerTaskContext,
) -> dict[str, Any]:
    with session_scope() as session:
        repository = SzdmRepository(session)
        item = repository.mark_item_running(item_id=item_id, attempt_no=context.attempt_no)
        job = repository.get_job(job_id)
        if job is None:
            raise NonRetryableTaskError("SZDM job not found", error_code="SZDM_JOB_NOT_FOUND")
        item_key = item.item_key
        condition_key = item.condition_key
        reuse_window_seconds = job.reuse_window_seconds

    context.raise_if_canceled()
    reuse_key = _find_reusable_result_key(
        s3=s3,
        item_key=item_key,
        condition_key=condition_key,
        reuse_window_seconds=reuse_window_seconds,
    )
    now = utc_now()
    if reuse_key is not None:
        result_payload = s3.get_json(reuse_key)
        if not isinstance(result_payload, dict):
            result_payload = {"value": result_payload}
        metrics = dict(result_payload.get("metrics") or {})
        display_summary = dict(result_payload.get("display_summary") or {})
        with session_scope() as session:
            SzdmRepository(session).mark_item_succeeded(
                item_id=item_id,
                reuse_status="REUSED",
                result_s3_key=s3.to_uri(reuse_key),
                result_timestamp=_extract_timestamp_from_result_key(reuse_key) or now,
                metrics=metrics,
                display_summary=display_summary,
            )
        return {"job_id": job_id, "item_id": item_id, "reuse_status": "REUSED", "result_s3_key": s3.to_uri(reuse_key)}

    context.set_progress(25, "szdm_processing")
    result_payload = _build_item_result_payload(item_key=item_key, condition_key=condition_key, item_id=item_id)
    result_timestamp = utc_now()
    result_key = f"szdm/items/{item_key}/{condition_key}/{_format_timestamp(result_timestamp)}/result.json"
    result_s3_key = s3.put_json(result_key, result_payload)
    context.set_progress(90, "szdm_result_stored")
    with session_scope() as session:
        SzdmRepository(session).mark_item_succeeded(
            item_id=item_id,
            reuse_status="GENERATED",
            result_s3_key=result_s3_key,
            result_timestamp=result_timestamp,
            metrics=dict(result_payload["metrics"]),
            display_summary=dict(result_payload["display_summary"]),
        )
    context.set_progress(100, "completed")
    return {"job_id": job_id, "item_id": item_id, "reuse_status": "GENERATED", "result_s3_key": result_s3_key}


def szdm_aggregate_handler(payload: dict[str, Any], context: WorkerTaskContext) -> dict[str, Any]:
    job_id = int(payload["job_id"])
    settings = get_settings()
    s3 = S3ClientProvider(bucket=settings.szdm_s3_bucket, root_dir=settings.szdm_s3_root_dir).build()
    with session_scope() as session:
        repository = SzdmRepository(session)
        job = repository.get_job(job_id)
        if job is None:
            raise NonRetryableTaskError("SZDM job not found", error_code="SZDM_JOB_NOT_FOUND")
        items = repository.list_all_items(job_id=job_id)
        if any(item.status != "SUCCEEDED" for item in items):
            raise NonRetryableTaskError("All SZDM items must succeed before aggregation", error_code="SZDM_NOT_READY")
        job_s3_prefix = job.job_s3_prefix

    context.raise_if_canceled()
    item_results: list[dict[str, Any]] = []
    for item in items:
        if item.result_s3_key:
            result = s3.get_json(item.result_s3_key)
            if isinstance(result, dict):
                item_results.append(result)

    total_score = sum(float(result.get("metrics", {}).get("score", 0)) for result in item_results)
    summary = {
        "job_id": job_id,
        "item_count": len(items),
        "average_score": total_score / max(len(items), 1),
    }
    report_payload = {"summary": summary, "items": item_results}
    report_json = json.dumps(report_payload, sort_keys=True, separators=(",", ":"))
    report_hash = hashlib.sha256(report_json.encode("utf-8")).hexdigest()
    report_key = f"{_strip_s3_uri_prefix(job_s3_prefix)}/report.json"
    report_s3_key = s3.put_json(report_key, report_payload)
    with session_scope() as session:
        SzdmRepository(session).finish_report(
            job_id=job_id,
            report_s3_key=report_s3_key,
            report_hash=report_hash,
            summary=summary,
            metric_summary={"total_score": total_score},
        )
    context.set_progress(100, "completed")
    return {"job_id": job_id, "report_s3_key": report_s3_key, "summary": summary}


def _build_item_result_payload(*, item_key: str, condition_key: str, item_id: int) -> dict[str, Any]:
    score = float((len(item_key) + len(condition_key) + item_id) % 100) / 100
    return {
        "item_key": item_key,
        "condition_key": condition_key,
        "metrics": {"score": score},
        "display_summary": {"item_key": item_key, "condition_key": condition_key, "score": score},
    }


def _find_reusable_result_key(*, s3, item_key: str, condition_key: str, reuse_window_seconds: int) -> str | None:
    if reuse_window_seconds <= 0:
        return None
    prefix = f"szdm/items/{item_key}/{condition_key}"
    candidates = s3.list_json_keys(prefix)
    now = utc_now()
    for key in sorted(candidates, reverse=True):
        if not key.endswith("/result.json"):
            continue
        timestamp = _extract_timestamp_from_result_key(key)
        if timestamp is None:
            continue
        if (now - timestamp).total_seconds() <= reuse_window_seconds:
            return key
    return None


def _extract_timestamp_from_result_key(key: str) -> datetime | None:
    parts = key.split("/")
    if len(parts) < 5:
        return None
    try:
        return datetime.strptime(parts[-2], "%Y%m%dT%H%M%S%f")
    except ValueError:
        return None


def _format_timestamp(value) -> str:
    return value.strftime("%Y%m%dT%H%M%S%f")


def _strip_s3_uri_prefix(value: str) -> str:
    if value.startswith("s3://"):
        parts = value.split("/", 3)
        return parts[3] if len(parts) > 3 else ""
    return value


HANDLERS: dict[str, TaskHandler] = {
    "szdm.sub": szdm_sub_handler,
    "szdm.aggregate": szdm_aggregate_handler,
}
