"""Mint/bonding-curve scoped collection for early buyer / bundler discovery."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pumpfun_intel.analyzer.activity import persist_classified_event, sol_delta_for_wallet
from pumpfun_intel.clients.rpc import SolanaRpcClient
from pumpfun_intel.collector.transactions import _fetch_one
from pumpfun_intel.constants import BUY_INSTRUCTION_TYPES, PUMP_FUN_PROGRAM_ID
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import dumps, upsert_raw_transaction, upsert_signature, utc_now_iso
from pumpfun_intel.decoder.instructions import decode_transaction_instructions

logger = logging.getLogger(__name__)


@dataclass
class MintProbeResult:
    mint: str
    bonding_curve: str | None
    signatures_seen: int
    txs_ok: int
    early_buyers: list[dict]


def _ensure_sig(db: Database, signature: str, wallet_tag: str, item: dict) -> None:
    upsert_signature(
        db,
        signature=signature,
        wallet=wallet_tag,
        slot=item.get("slot"),
        block_time=int(item["blockTime"]) if item.get("blockTime") is not None else None,
        err_json=json.dumps(item.get("err")) if item.get("err") is not None else None,
        confirmation_status=item.get("confirmationStatus"),
    )


def _load_tx(db: Database, rpc: SolanaRpcClient, sig: str) -> dict | None:
    existing = db.fetchone(
        "SELECT status, json_blob FROM raw_transactions WHERE signature = ?",
        (sig,),
    )
    if existing and existing["status"] == "ok" and existing["json_blob"]:
        return json.loads(existing["json_blob"])
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


def _collect_window_signatures(
    rpc: SolanaRpcClient,
    db: Database,
    address: str,
    tag: str,
    create_time: int,
    cutoff: int,
    create_signature: str,
    max_pages: int = 5,
    max_keep: int = 80,
) -> list[str]:
    """
    Walk bonding-curve signatures newest→oldest until past create_time.
    Keep only signatures in [create_time, cutoff], plus the create signature.
    """
    before: str | None = None
    kept: list[str] = []
    seen: set[str] = set()

    for _ in range(max_pages):
        page = rpc.get_signatures_for_address(address, before=before, limit=1000)
        if not page:
            break
        stop = False
        for item in page:
            sig = item.get("signature")
            if not sig:
                continue
            bt = item.get("blockTime")
            _ensure_sig(db, sig, tag, item)
            if bt is None:
                continue
            bti = int(bt)
            if bti > cutoff:
                continue
            if bti < create_time:
                stop = True
                break
            if sig not in seen:
                kept.append(sig)
                seen.add(sig)
            if len(kept) >= max_keep:
                stop = True
                break
        before = page[-1].get("signature")
        if stop or len(page) < 1000:
            break

    if create_signature not in seen:
        kept.append(create_signature)
        seen.add(create_signature)
    return kept


def probe_mint_early_activity(
    db: Database,
    rpc: SolanaRpcClient,
    *,
    mint: str,
    bonding_curve: str | None,
    create_time: int,
    create_signature: str,
    early_window_seconds: int = 30,
    creator: str | None = None,
    max_txs: int = 40,
) -> MintProbeResult:
    address = bonding_curve or mint
    tag = f"curve:{address}" if bonding_curve else f"mint:{mint}"
    cutoff = create_time + early_window_seconds

    sigs = _collect_window_signatures(
        rpc,
        db,
        address,
        tag,
        create_time,
        cutoff,
        create_signature,
    )
    # Prefer create tx + earliest window txs (signatures are newest-first from RPC pages).
    # Re-sort by fetching block times from signatures table when available.
    timed: list[tuple[int, str]] = []
    untimed: list[str] = []
    for sig in sigs:
        row = db.fetchone(
            "SELECT block_time FROM signatures WHERE signature = ?",
            (sig,),
        )
        if row and row["block_time"] is not None:
            timed.append((int(row["block_time"]), sig))
        else:
            untimed.append(sig)
    timed.sort(key=lambda x: x[0])
    ordered = [create_signature] + [s for _, s in timed if s != create_signature] + [
        s for s in untimed if s != create_signature
    ]
    # de-dupe preserve order
    seen_order: set[str] = set()
    sigs = []
    for s in ordered:
        if s not in seen_order:
            seen_order.add(s)
            sigs.append(s)
    sigs = sigs[:max_txs]

    txs_ok = 0
    early_buyers: dict[str, dict] = {}

    for sig in sigs:
        tx = _load_tx(db, rpc, sig)
        if tx is None:
            continue
        txs_ok += 1
        bt = tx.get("blockTime")
        in_window = sig == create_signature or (
            bt is not None and create_time <= int(bt) <= cutoff
        )
        if not in_window:
            continue

        decoded = decode_transaction_instructions(sig, tx)
        for ix in decoded:
            is_buy = ix.ix_type in BUY_INSTRUCTION_TYPES or (
                ix.ix_type is not None and ix.ix_type.startswith("pumpswap_buy")
            )
            if not is_buy:
                continue
            ix_mint = ix.args.get("mint")
            if ix_mint and ix_mint != mint:
                continue
            buyer = ix.args.get("user")
            if not buyer:
                continue
            if bonding_curve and buyer == bonding_curve:
                continue
            sol = ix.args.get("sol_amount") or ix.args.get("sol_limit")
            if sol is None:
                delta = sol_delta_for_wallet(tx, buyer)
                if delta is not None and delta < 0:
                    sol = abs(delta)
            persist_classified_event(
                db,
                signature=sig,
                slot=tx.get("slot"),
                block_time=bt,
                event_type="buy",
                mint=mint,
                wallet=buyer,
                sol_amount=float(sol) if sol is not None else None,
                token_amount=float(ix.args["token_amount"])
                if ix.args.get("token_amount") is not None
                else None,
                program_id=ix.program_id or PUMP_FUN_PROGRAM_ID,
                details={
                    "source": "mint_probe",
                    "ix_type": ix.ix_type,
                    "probed_address": address,
                },
                evidence_level="instruction",
            )
            prev = early_buyers.get(buyer)
            if prev is None or (
                bt is not None and (prev.get("block_time") or 10**18) > int(bt)
            ):
                early_buyers[buyer] = {
                    "wallet": buyer,
                    "signature": sig,
                    "block_time": int(bt) if bt is not None else None,
                    "sol_amount": float(sol) if sol is not None else None,
                    "delay_s": (int(bt) - create_time) if bt is not None else None,
                    "is_creator": bool(creator and buyer == creator),
                }

        if sig == create_signature:
            meta = tx.get("meta") or {}
            for entry in meta.get("postTokenBalances") or []:
                if entry.get("mint") != mint:
                    continue
                owner = entry.get("owner")
                if (
                    not owner
                    or owner in early_buyers
                    or (bonding_curve and owner == bonding_curve)
                ):
                    continue
                early_buyers[owner] = {
                    "wallet": owner,
                    "signature": sig,
                    "block_time": create_time,
                    "sol_amount": None,
                    "delay_s": 0,
                    "source": "postTokenBalances",
                    "is_creator": bool(creator and owner == creator),
                }

    logger.info(
        "Mint probe %s: sigs=%d txs_ok=%d early_buyers=%d non_creator=%d",
        mint[:8],
        len(sigs),
        txs_ok,
        len(early_buyers),
        sum(1 for b in early_buyers.values() if not b.get("is_creator")),
    )
    return MintProbeResult(
        mint=mint,
        bonding_curve=bonding_curve,
        signatures_seen=len(sigs),
        txs_ok=txs_ok,
        early_buyers=list(early_buyers.values()),
    )


def probe_recent_launches(
    db: Database,
    rpc: SolanaRpcClient,
    *,
    limit: int = 40,
    early_window_seconds: int = 30,
) -> list[MintProbeResult]:
    rows = db.fetchall(
        """
        SELECT mint, bonding_curve, create_time, create_signature, symbol, creator
        FROM token_launches
        WHERE create_time IS NOT NULL AND bonding_curve IS NOT NULL
        ORDER BY create_time DESC
        LIMIT ?
        """,
        (limit,),
    )
    results: list[MintProbeResult] = []
    for row in rows:
        try:
            results.append(
                probe_mint_early_activity(
                    db,
                    rpc,
                    mint=row["mint"],
                    bonding_curve=row["bonding_curve"],
                    create_time=int(row["create_time"]),
                    create_signature=row["create_signature"],
                    early_window_seconds=early_window_seconds,
                    creator=row["creator"],
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Mint probe failed for %s: %s", row["mint"][:8], exc)
    db.execute(
        """
        INSERT INTO coverage_meta (scope, scope_key, metric, value, recorded_at)
        VALUES ('analysis', 'mint_probe', 'launches_probed', ?, ?)
        ON CONFLICT(scope, scope_key, metric) DO UPDATE SET
            value = excluded.value,
            recorded_at = excluded.recorded_at
        """,
        (str(len(results)), utc_now_iso()),
    )
    return results
