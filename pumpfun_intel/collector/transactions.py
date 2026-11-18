"""Fetch and cache raw + enhanced transaction payloads."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pumpfun_intel.clients.helius import HeliusClient
from pumpfun_intel.clients.rpc import SolanaRpcClient
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import (
    already_fetched_ok,
    dumps,
    pending_signatures,
    upsert_enhanced_transaction,
    upsert_raw_transaction,
)

logger = logging.getLogger(__name__)


def _write_cache(cache_dir: Path | None, name: str, payload: Any) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / name
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fetch_one(rpc: SolanaRpcClient, sig: str) -> tuple[str, str, dict[str, Any] | None, str | None]:
    """Return (signature, status, tx_or_none, error_message)."""
    try:
        tx = rpc.get_transaction(sig)
        if tx is None:
            return sig, "missing", None, "getTransaction returned null"
        return sig, "ok", tx, None
    except Exception as exc:  # noqa: BLE001
        return sig, "failed", None, str(exc)[:500]


def fetch_raw_transactions(
    db: Database,
    rpc: SolanaRpcClient,
    wallet: str,
    *,
    batch_size: int = 200,
    workers: int = 12,
    cache_dir: Path | None = None,
) -> tuple[int, int]:
    """Fetch missing raw transactions in parallel. Returns (ok_count, fail_count)."""
    ok = 0
    failed = 0
    lock = threading.Lock()

    while True:
        pending = pending_signatures(db, wallet, limit=batch_size)
        if not pending:
            break
        pending = [s for s in pending if not already_fetched_ok(db, s)]
        if not pending:
            break

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch_one, rpc, sig): sig for sig in pending}
            for fut in as_completed(futures):
                sig, status, tx, err = fut.result()
                with lock:
                    if status == "ok" and tx is not None:
                        upsert_raw_transaction(
                            db,
                            signature=sig,
                            slot=tx.get("slot"),
                            block_time=tx.get("blockTime"),
                            status="ok",
                            json_blob=dumps(tx),
                        )
                        ok += 1
                    else:
                        upsert_raw_transaction(
                            db,
                            signature=sig,
                            slot=None,
                            block_time=None,
                            status=status,
                            json_blob=None,
                            error_message=err,
                        )
                        failed += 1
                        if err:
                            logger.warning("Failed to fetch tx %s: %s", sig, err)

        logger.info("Raw tx progress: ok=%d failed=%d", ok, failed)
        _write_cache(
            cache_dir,
            f"raw_progress_{wallet[:8]}.json",
            {"ok": ok, "failed": failed},
        )
    return ok, failed


def fetch_enhanced_batches(
    db: Database,
    helius: HeliusClient,
    signatures: list[str],
    *,
    batch_size: int = 100,
    cache_dir: Path | None = None,
) -> int:
    """Optional enrichment via Helius Enhanced Transactions API."""
    stored = 0
    for i in range(0, len(signatures), batch_size):
        chunk = signatures[i : i + batch_size]
        need: list[str] = []
        for sig in chunk:
            row = db.fetchone(
                "SELECT signature FROM enhanced_transactions WHERE signature = ?",
                (sig,),
            )
            if row is None:
                need.append(sig)
        if not need:
            continue
        try:
            txs = helius.get_transactions_batch(need)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Enhanced batch failed (%d sigs): %s", len(need), exc)
            continue
        _write_cache(cache_dir, f"helius_batch_{i}.json", txs)
        for tx in txs:
            sig = tx.get("signature")
            if not sig:
                continue
            upsert_enhanced_transaction(db, sig, dumps(tx))
            stored += 1
        logger.info("Enhanced txs stored this run: %d", stored)
    return stored
