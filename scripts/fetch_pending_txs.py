"""Resume raw transaction fetches without re-paginating signatures."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pumpfun_intel.clients.rpc import SolanaRpcClient
from pumpfun_intel.config import load_settings, setup_logging
from pumpfun_intel.collector.transactions import fetch_raw_transactions
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import set_coverage


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    wallet = settings.target_wallet
    rps = float(os.getenv("RPC_RPS", str(settings.rpc_rps)))
    # Prefer a higher throughput for bulk backfill unless overridden.
    if "RPC_RPS" not in os.environ:
        rps = max(rps, 20.0)

    db = Database(settings.database_path)
    rpc = SolanaRpcClient(settings.rpc_url, rps=rps)
    logging.getLogger(__name__).info(
        "Fetching pending raw txs for %s at ~%.1f rps", wallet, rps
    )
    ok, failed = fetch_raw_transactions(
        db,
        rpc,
        wallet,
        batch_size=300,
        workers=16,
        cache_dir=settings.cache_dir,
    )
    set_coverage(db, "wallet", wallet, "txs_ok_delta", str(ok))
    set_coverage(db, "wallet", wallet, "txs_failed_delta", str(failed))
    print({"ok": ok, "failed": failed})
    db.close()


if __name__ == "__main__":
    main()
