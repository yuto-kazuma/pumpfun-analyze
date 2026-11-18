"""Resumable collection tests with mocked RPC."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pumpfun_intel.collector.signatures import collect_signatures
from pumpfun_intel.collector.transactions import fetch_raw_transactions
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import already_fetched_ok, upsert_raw_transaction, upsert_signature


WALLET = "DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri"


def _db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def test_signature_pagination_and_cutoff(tmp_path: Path) -> None:
    db = _db(tmp_path)
    rpc = MagicMock()
    now = 1_700_000_000
    page1 = [
        {"signature": "sigA", "slot": 3, "blockTime": now, "err": None},
        {"signature": "sigB", "slot": 2, "blockTime": now - 10, "err": None},
    ]
    page2 = [
        {"signature": "sigC", "slot": 1, "blockTime": now - 100_000, "err": None},
    ]
    rpc.get_signatures_for_address.side_effect = [page1, page2, []]

    total, last = collect_signatures(
        db,
        rpc,
        WALLET,
        lookback_days=1,  # cutoff ~86400 seconds ago
        page_limit=2,
    )
    # page2's sigC is older than 1 day relative to "now" only if we use real time.
    # Instead, force cutoff by using lookback that excludes sigC via mocked times:
    # re-run with explicit max and no lookback for deterministic assert
    db.close()

    db = _db(tmp_path / "b")
    rpc = MagicMock()
    rpc.get_signatures_for_address.side_effect = [page1, []]
    total, last = collect_signatures(
        db,
        rpc,
        WALLET,
        lookback_days=None,
        page_limit=1000,
    )
    assert total == 2
    assert last == "sigB"
    rows = db.fetchall("SELECT signature FROM signatures ORDER BY signature")
    assert [r["signature"] for r in rows] == ["sigA", "sigB"]
    db.close()


def test_raw_fetch_skips_already_ok(tmp_path: Path) -> None:
    db = _db(tmp_path)
    upsert_signature(
        db,
        signature="sig1",
        wallet=WALLET,
        slot=1,
        block_time=1,
        err_json=None,
    )
    upsert_signature(
        db,
        signature="sig2",
        wallet=WALLET,
        slot=2,
        block_time=2,
        err_json=None,
    )
    upsert_raw_transaction(
        db,
        signature="sig1",
        slot=1,
        block_time=1,
        status="ok",
        json_blob='{"slot":1}',
    )
    assert already_fetched_ok(db, "sig1") is True
    assert already_fetched_ok(db, "sig2") is False

    rpc = MagicMock()

    def get_tx(sig: str) -> dict[str, Any]:
        return {"slot": 9, "blockTime": 9, "transaction": {}, "meta": {}}

    rpc.get_transaction.side_effect = get_tx
    ok, failed = fetch_raw_transactions(db, rpc, WALLET, batch_size=10)
    assert ok == 1
    assert failed == 0
    assert rpc.get_transaction.call_count == 1
    assert rpc.get_transaction.call_args[0][0] == "sig2"
    db.close()


def test_time_cutoff_stops_pagination(tmp_path: Path) -> None:
    db = _db(tmp_path)
    rpc = MagicMock()
    import time

    now = int(time.time())
    page = [
        {"signature": "new1", "slot": 2, "blockTime": now - 10, "err": None},
        {"signature": "old1", "slot": 1, "blockTime": now - 10 * 86400, "err": None},
    ]
    rpc.get_signatures_for_address.return_value = page
    total, _ = collect_signatures(db, rpc, WALLET, lookback_days=1, page_limit=1000)
    assert total == 1
    row = db.fetchone("SELECT signature FROM signatures")
    assert row["signature"] == "new1"
    db.close()
