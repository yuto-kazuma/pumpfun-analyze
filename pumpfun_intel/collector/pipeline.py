"""End-to-end collection orchestration with checkpoints."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pumpfun_intel.clients.helius import HeliusClient
from pumpfun_intel.clients.rpc import SolanaRpcClient
from pumpfun_intel.collector.signatures import collect_signatures
from pumpfun_intel.collector.transactions import fetch_enhanced_batches, fetch_raw_transactions
from pumpfun_intel.config import Settings
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import (
    create_collection_run,
    set_coverage,
    update_collection_run,
)

logger = logging.getLogger(__name__)


@dataclass
class CollectionResult:
    run_id: int
    wallet: str
    signatures_collected: int
    txs_ok: int
    txs_failed: int
    enhanced_stored: int


def collect_wallet_history(
    settings: Settings,
    *,
    wallet: str | None = None,
    lookback_days: int | None = 30,
    max_signatures: int | None = None,
    fetch_enhanced: bool = True,
    resume_run_id: int | None = None,
) -> CollectionResult:
    """
    Collect historical signatures and transactions for a wallet.

    lookback_days=0 or None => no time cutoff.
    """
    wallet = wallet or settings.target_wallet
    settings.cache_dir.mkdir(parents=True, exist_ok=True)

    db = Database(settings.database_path)
    rpc = SolanaRpcClient(settings.rpc_url, rps=settings.rpc_rps)
    helius = HeliusClient(settings.helius_api_key, rps=settings.helius_rps)

    if resume_run_id is not None:
        run_id = resume_run_id
        row = db.fetchone("SELECT * FROM collection_runs WHERE id = ?", (run_id,))
        if row is None:
            raise KeyError(f"Unknown collection run {run_id}")
        start_before = row["checkpoint_before"]
        update_collection_run(db, run_id, status="running")
    else:
        days = None if not lookback_days else lookback_days
        run_id = create_collection_run(db, wallet, days)
        start_before = None

    logger.info(
        "Starting collection run=%s wallet=%s lookback_days=%s",
        run_id,
        wallet,
        lookback_days,
    )

    def on_page(page, total: int) -> None:  # type: ignore[no-untyped-def]
        update_collection_run(
            db,
            run_id,
            checkpoint_before=page.next_before,
            signatures_collected=total,
        )

    try:
        sig_count, last_before = collect_signatures(
            db,
            rpc,
            wallet,
            lookback_days=lookback_days if lookback_days and lookback_days > 0 else None,
            max_signatures=max_signatures,
            start_before=start_before,
            on_page=on_page,
        )
        update_collection_run(
            db,
            run_id,
            checkpoint_before=last_before,
            signatures_collected=sig_count,
        )

        txs_ok, txs_failed = fetch_raw_transactions(
            db,
            rpc,
            wallet,
            cache_dir=settings.cache_dir,
        )
        update_collection_run(
            db,
            run_id,
            txs_fetched=txs_ok,
            txs_failed=txs_failed,
        )

        enhanced_stored = 0
        if fetch_enhanced:
            rows = db.fetchall(
                """
                SELECT signature FROM signatures
                WHERE wallet = ?
                ORDER BY block_time DESC
                """,
                (wallet,),
            )
            sigs = [str(r["signature"]) for r in rows]
            enhanced_stored = fetch_enhanced_batches(
                db,
                helius,
                sigs,
                cache_dir=settings.cache_dir,
            )

        set_coverage(
            db,
            "wallet",
            wallet,
            "signatures_collected",
            str(sig_count),
        )
        set_coverage(db, "wallet", wallet, "txs_ok", str(txs_ok))
        set_coverage(db, "wallet", wallet, "txs_failed", str(txs_failed))
        set_coverage(
            db,
            "wallet",
            wallet,
            "coverage_incomplete",
            "true" if txs_failed > 0 else "false",
        )

        update_collection_run(
            db,
            run_id,
            status="completed",
            finished=True,
            notes=f"enhanced_stored={enhanced_stored}",
        )
        logger.info(
            "Collection complete run=%s sigs=%d txs_ok=%d txs_failed=%d enhanced=%d",
            run_id,
            sig_count,
            txs_ok,
            txs_failed,
            enhanced_stored,
        )
        return CollectionResult(
            run_id=run_id,
            wallet=wallet,
            signatures_collected=sig_count,
            txs_ok=txs_ok,
            txs_failed=txs_failed,
            enhanced_stored=enhanced_stored,
        )
    except Exception as exc:
        update_collection_run(
            db,
            run_id,
            status="failed",
            finished=True,
            notes=str(exc)[:500],
        )
        raise
    finally:
        db.close()
