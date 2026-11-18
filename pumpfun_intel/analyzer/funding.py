"""Funding-flow analysis for repeated early buyers (research only)."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from pumpfun_intel.clients.rpc import SolanaRpcClient
from pumpfun_intel.collector.transactions import _fetch_one
from pumpfun_intel.constants import LAMPORTS_PER_SOL, SYSTEM_PROGRAM_ID
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import dumps, upsert_raw_transaction, upsert_signature

logger = logging.getLogger(__name__)


@dataclass
class FundingHit:
    to_wallet: str
    from_wallet: str
    sol: float
    signature: str
    block_time: int | None


def _load_or_fetch(db: Database, rpc: SolanaRpcClient, sig: str, tag: str, meta: dict) -> dict | None:
    upsert_signature(
        db,
        signature=sig,
        wallet=tag,
        slot=meta.get("slot"),
        block_time=int(meta["blockTime"]) if meta.get("blockTime") is not None else None,
        err_json=json.dumps(meta.get("err")) if meta.get("err") is not None else None,
        confirmation_status=meta.get("confirmationStatus"),
    )
    row = db.fetchone(
        "SELECT status, json_blob FROM raw_transactions WHERE signature = ?",
        (sig,),
    )
    if row and row["status"] == "ok" and row["json_blob"]:
        return json.loads(row["json_blob"])
    _, status, tx, err = _fetch_one(rpc, sig)
    if status == "ok" and tx is not None:
        upsert_raw_transaction(
            db,
            signature=sig,
            slot=tx.get("slot"),
            block_time=tx.get("blockTime"),
            status="ok",
            json_blob=dumps(tx),
        )
        return tx
    upsert_raw_transaction(
        db,
        signature=sig,
        slot=None,
        block_time=None,
        status=status,
        json_blob=None,
        error_message=err,
    )
    return None


def extract_sol_inbound(
    tx: dict[str, Any],
    wallet: str,
) -> list[tuple[str, float]]:
    """Return list of (source_wallet, sol_amount) transferred into wallet."""
    hits: list[tuple[str, float]] = []
    message = (tx.get("transaction") or {}).get("message") or {}
    groups = [message.get("instructions") or []]
    for g in (tx.get("meta") or {}).get("innerInstructions") or []:
        groups.append(g.get("instructions") or [])
    for ixs in groups:
        for ix in ixs:
            if ix.get("programId") != SYSTEM_PROGRAM_ID:
                continue
            parsed = ix.get("parsed")
            if not isinstance(parsed, dict) or parsed.get("type") != "transfer":
                continue
            info = parsed.get("info") or {}
            if info.get("destination") != wallet:
                continue
            lamports = info.get("lamports")
            src = info.get("source")
            if src and lamports is not None:
                hits.append((str(src), int(lamports) / LAMPORTS_PER_SOL))
    return hits


def probe_wallet_funding(
    db: Database,
    rpc: SolanaRpcClient,
    wallet: str,
    *,
    max_signatures: int = 80,
) -> list[FundingHit]:
    tag = f"fund:{wallet}"
    page = rpc.get_signatures_for_address(wallet, limit=min(max_signatures, 1000))
    hits: list[FundingHit] = []
    for item in page:
        sig = item.get("signature")
        if not sig:
            continue
        tx = _load_or_fetch(db, rpc, sig, tag, item)
        if tx is None:
            continue
        for src, sol in extract_sol_inbound(tx, wallet):
            if sol <= 0:
                continue
            hits.append(
                FundingHit(
                    to_wallet=wallet,
                    from_wallet=src,
                    sol=sol,
                    signature=sig,
                    block_time=tx.get("blockTime"),
                )
            )
    return hits


def analyze_candidate_funding(
    db: Database,
    rpc: SolanaRpcClient,
    candidates: list[str],
    *,
    creator: str,
    max_signatures: int = 60,
) -> dict[str, Any]:
    funder_counts: Counter[str] = Counter()
    by_wallet: dict[str, Counter[str]] = defaultdict(Counter)
    amount_by_pair: dict[tuple[str, str], list[float]] = defaultdict(list)
    creator_funded: list[str] = []

    for wallet in candidates:
        try:
            hits = probe_wallet_funding(
                db, rpc, wallet, max_signatures=max_signatures
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Funding probe failed for %s: %s", wallet[:8], exc)
            continue
        sources = Counter(h.from_wallet for h in hits)
        by_wallet[wallet] = sources
        for h in hits:
            funder_counts[h.from_wallet] += 1
            amount_by_pair[(h.from_wallet, wallet)].append(h.sol)
        if creator in sources:
            creator_funded.append(wallet)
        logger.info(
            "Funding %s: inbound_sources=%d top=%s",
            wallet[:8],
            len(sources),
            sources.most_common(3),
        )

    common_funders = [
        (f, c)
        for f, c in funder_counts.most_common(20)
        if f != creator and c >= 2
    ]
    return {
        "creator": creator,
        "candidates": candidates,
        "creator_funded_wallets": creator_funded,
        "funder_counts": funder_counts.most_common(25),
        "common_funders": common_funders,
        "by_wallet_top": {
            w: sources.most_common(5) for w, sources in by_wallet.items()
        },
        "repeat_amounts": {
            f"{a[:6]}…->{b[:6]}…": {
                "n": len(vals),
                "median": sorted(vals)[len(vals) // 2],
                "sum": sum(vals),
            }
            for (a, b), vals in amount_by_pair.items()
            if len(vals) >= 2
        },
    }
