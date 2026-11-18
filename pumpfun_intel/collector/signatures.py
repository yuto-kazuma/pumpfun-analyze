"""Paginated, resumable signature crawling."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Callable

from pumpfun_intel.clients.rpc import SolanaRpcClient
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import upsert_signature

logger = logging.getLogger(__name__)


@dataclass
class SignaturePageResult:
    signatures: list[str]
    oldest_block_time: int | None
    next_before: str | None
    exhausted: bool


def collect_signatures(
    db: Database,
    rpc: SolanaRpcClient,
    wallet: str,
    *,
    lookback_days: int | None = 30,
    page_limit: int = 1000,
    max_signatures: int | None = None,
    start_before: str | None = None,
    on_page: Callable[[SignaturePageResult, int], None] | None = None,
) -> tuple[int, str | None]:
    """
    Fetch signatures for wallet into SQLite.

    lookback_days=None or 0 means no time cutoff (full history until exhausted
    or max_signatures).
    """
    cutoff: int | None = None
    if lookback_days and lookback_days > 0:
        cutoff = int(time.time()) - lookback_days * 86400

    before = start_before
    total = 0
    last_before = start_before

    while True:
        if max_signatures is not None and total >= max_signatures:
            break

        limit = page_limit
        if max_signatures is not None:
            limit = min(limit, max_signatures - total)

        page = rpc.get_signatures_for_address(wallet, before=before, limit=limit)
        if not page:
            result = SignaturePageResult([], None, before, True)
            if on_page:
                on_page(result, total)
            break

        oldest_bt: int | None = None
        batch_sigs: list[str] = []
        stop_time = False

        for item in page:
            sig = item.get("signature")
            if not sig:
                continue
            bt = item.get("blockTime")
            if cutoff is not None and bt is not None and int(bt) < cutoff:
                stop_time = True
                break

            err = item.get("err")
            upsert_signature(
                db,
                signature=sig,
                wallet=wallet,
                slot=item.get("slot"),
                block_time=int(bt) if bt is not None else None,
                err_json=json.dumps(err) if err is not None else None,
                confirmation_status=item.get("confirmationStatus"),
                memo=item.get("memo"),
            )
            batch_sigs.append(sig)
            oldest_bt = int(bt) if bt is not None else oldest_bt
            total += 1

        next_before = page[-1].get("signature")
        last_before = next_before
        result = SignaturePageResult(
            signatures=batch_sigs,
            oldest_block_time=oldest_bt,
            next_before=next_before,
            exhausted=stop_time or len(page) < limit,
        )
        logger.info(
            "Signature page: +%d (total=%d) before=%s oldest_bt=%s",
            len(batch_sigs),
            total,
            before,
            oldest_bt,
        )
        if on_page:
            on_page(result, total)

        if stop_time or len(page) < limit:
            break
        before = next_before

    return total, last_before
