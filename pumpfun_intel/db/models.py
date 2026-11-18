"""Typed helpers for inserting / reading SQLite rows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pumpfun_intel.db.connection import Database


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def loads(text: str | None) -> Any:
    if text is None:
        return None
    return json.loads(text)


def create_collection_run(
    db: Database,
    wallet: str,
    lookback_days: int | None,
) -> int:
    cur = db.execute(
        """
        INSERT INTO collection_runs (wallet, lookback_days, status, started_at)
        VALUES (?, ?, 'running', ?)
        """,
        (wallet, lookback_days, utc_now_iso()),
    )
    return int(cur.lastrowid)


def update_collection_run(
    db: Database,
    run_id: int,
    *,
    status: str | None = None,
    checkpoint_before: str | None = None,
    signatures_collected: int | None = None,
    txs_fetched: int | None = None,
    txs_failed: int | None = None,
    notes: str | None = None,
    finished: bool = False,
) -> None:
    row = db.fetchone("SELECT * FROM collection_runs WHERE id = ?", (run_id,))
    if row is None:
        raise KeyError(f"collection_run {run_id} not found")
    db.execute(
        """
        UPDATE collection_runs SET
            status = COALESCE(?, status),
            checkpoint_before = COALESCE(?, checkpoint_before),
            signatures_collected = COALESCE(?, signatures_collected),
            txs_fetched = COALESCE(?, txs_fetched),
            txs_failed = COALESCE(?, txs_failed),
            notes = COALESCE(?, notes),
            finished_at = CASE WHEN ? THEN ? ELSE finished_at END
        WHERE id = ?
        """,
        (
            status,
            checkpoint_before,
            signatures_collected,
            txs_fetched,
            txs_failed,
            notes,
            1 if finished else 0,
            utc_now_iso() if finished else None,
            run_id,
        ),
    )


def upsert_signature(
    db: Database,
    *,
    signature: str,
    wallet: str,
    slot: int | None,
    block_time: int | None,
    err_json: str | None,
    confirmation_status: str | None = None,
    memo: str | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO signatures (
            signature, wallet, slot, block_time, err_json, memo,
            confirmation_status, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(signature) DO UPDATE SET
            wallet = excluded.wallet,
            slot = COALESCE(excluded.slot, signatures.slot),
            block_time = COALESCE(excluded.block_time, signatures.block_time),
            err_json = COALESCE(excluded.err_json, signatures.err_json),
            confirmation_status = COALESCE(
                excluded.confirmation_status, signatures.confirmation_status
            )
        """,
        (
            signature,
            wallet,
            slot,
            block_time,
            err_json,
            memo,
            confirmation_status,
            utc_now_iso(),
        ),
    )


def upsert_raw_transaction(
    db: Database,
    *,
    signature: str,
    slot: int | None,
    block_time: int | None,
    status: str,
    json_blob: str | None,
    error_message: str | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO raw_transactions (
            signature, slot, block_time, status, error_message, json_blob, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(signature) DO UPDATE SET
            slot = COALESCE(excluded.slot, raw_transactions.slot),
            block_time = COALESCE(excluded.block_time, raw_transactions.block_time),
            status = excluded.status,
            error_message = excluded.error_message,
            json_blob = COALESCE(excluded.json_blob, raw_transactions.json_blob),
            fetched_at = excluded.fetched_at
        """,
        (signature, slot, block_time, status, error_message, json_blob, utc_now_iso()),
    )


def upsert_enhanced_transaction(db: Database, signature: str, json_blob: str) -> None:
    db.execute(
        """
        INSERT INTO enhanced_transactions (signature, json_blob, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(signature) DO UPDATE SET
            json_blob = excluded.json_blob,
            fetched_at = excluded.fetched_at
        """,
        (signature, json_blob, utc_now_iso()),
    )


def pending_signatures(db: Database, wallet: str, limit: int = 100) -> list[str]:
    rows = db.fetchall(
        """
        SELECT s.signature
        FROM signatures s
        LEFT JOIN raw_transactions r ON r.signature = s.signature
        WHERE s.wallet = ?
          AND (r.signature IS NULL OR r.status IN ('pending', 'failed'))
        ORDER BY s.block_time DESC
        LIMIT ?
        """,
        (wallet, limit),
    )
    return [str(r["signature"]) for r in rows]


def already_fetched_ok(db: Database, signature: str) -> bool:
    row = db.fetchone(
        "SELECT status FROM raw_transactions WHERE signature = ?",
        (signature,),
    )
    return row is not None and row["status"] == "ok"


def set_coverage(
    db: Database,
    scope: str,
    scope_key: str,
    metric: str,
    value: str,
) -> None:
    db.execute(
        """
        INSERT INTO coverage_meta (scope, scope_key, metric, value, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(scope, scope_key, metric) DO UPDATE SET
            value = excluded.value,
            recorded_at = excluded.recorded_at
        """,
        (scope, scope_key, metric, value, utc_now_iso()),
    )
