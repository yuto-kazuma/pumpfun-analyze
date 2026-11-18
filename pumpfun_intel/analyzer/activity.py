"""Extract buy/sell/transfer activity around known mints."""

from __future__ import annotations

import logging
from typing import Any

from pumpfun_intel.constants import (
    BUY_INSTRUCTION_TYPES,
    CREATE_INSTRUCTION_TYPES,
    LAMPORTS_PER_SOL,
    PUMP_FUN_PROGRAM_ID,
    PUMP_SWAP_PROGRAM_ID,
    SELL_INSTRUCTION_TYPES,
)
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import dumps, loads
from pumpfun_intel.decoder.instructions import DecodedInstruction, decode_transaction_instructions

logger = logging.getLogger(__name__)


def persist_decoded_instructions(db: Database, decoded: list[DecodedInstruction]) -> None:
    for ix in decoded:
        db.execute(
            """
            INSERT INTO decoded_instructions (
                signature, ix_index, inner_index, is_inner, program_id,
                discriminator_hex, ix_type, accounts_json, args_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signature, ix_index, inner_index) DO UPDATE SET
                program_id = excluded.program_id,
                discriminator_hex = excluded.discriminator_hex,
                ix_type = excluded.ix_type,
                accounts_json = excluded.accounts_json,
                args_json = excluded.args_json
            """,
            (
                ix.signature,
                ix.ix_index,
                ix.inner_index if ix.inner_index is not None else -1,
                1 if ix.is_inner else 0,
                ix.program_id,
                ix.discriminator.hex() if ix.discriminator else None,
                ix.ix_type,
                dumps(ix.accounts),
                dumps(ix.args),
            ),
        )


def persist_classified_event(
    db: Database,
    *,
    signature: str,
    slot: int | None,
    block_time: int | None,
    event_type: str,
    mint: str | None,
    wallet: str | None,
    sol_amount: float | None,
    token_amount: float | None,
    program_id: str | None,
    details: dict[str, Any],
    evidence_level: str = "instruction",
) -> None:
    db.execute(
        """
        INSERT INTO classified_events (
            signature, slot, block_time, event_type, mint, wallet,
            sol_amount, token_amount, program_id, details_json, evidence_level
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(signature, event_type, mint, wallet, program_id) DO UPDATE SET
            slot = COALESCE(excluded.slot, classified_events.slot),
            block_time = COALESCE(excluded.block_time, classified_events.block_time),
            sol_amount = COALESCE(excluded.sol_amount, classified_events.sol_amount),
            token_amount = COALESCE(excluded.token_amount, classified_events.token_amount),
            details_json = excluded.details_json,
            evidence_level = CASE
                WHEN classified_events.evidence_level = 'instruction' THEN classified_events.evidence_level
                ELSE excluded.evidence_level
            END
        """,
        (
            signature,
            slot,
            block_time,
            event_type,
            mint,
            wallet,
            sol_amount,
            token_amount,
            program_id,
            dumps(details),
            evidence_level,
        ),
    )


def sol_delta_for_wallet(tx_json: dict[str, Any], wallet: str) -> float | None:
    meta = tx_json.get("meta") or {}
    message = (tx_json.get("transaction") or {}).get("message") or {}
    keys = message.get("accountKeys") or []
    idx = None
    for i, k in enumerate(keys):
        pk = k["pubkey"] if isinstance(k, dict) else k
        if pk == wallet:
            idx = i
            break
    if idx is None:
        return None
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if idx >= len(pre) or idx >= len(post):
        return None
    return (post[idx] - pre[idx]) / LAMPORTS_PER_SOL


def token_delta_for_wallet_mint(
    tx_json: dict[str, Any],
    wallet: str,
    mint: str,
) -> float | None:
    meta = tx_json.get("meta") or {}
    pre = meta.get("preTokenBalances") or []
    post = meta.get("postTokenBalances") or []

    def _amount(entries: list[dict[str, Any]]) -> float:
        total = 0.0
        for e in entries:
            if e.get("mint") != mint:
                continue
            if e.get("owner") != wallet:
                continue
            ui = (e.get("uiTokenAmount") or {}).get("uiAmount")
            if ui is not None:
                total += float(ui)
        return total

    return _amount(post) - _amount(pre)


def decode_and_classify_all(db: Database) -> tuple[int, int]:
    """
    Decode all raw_transactions with status=ok into instructions + classified events.

    Returns (tx_count, event_count).
    """
    rows = db.fetchall(
        """
        SELECT signature, slot, block_time, json_blob
        FROM raw_transactions
        WHERE status = 'ok' AND json_blob IS NOT NULL
        """
    )
    # Clear rebuildable derived instruction/event rows for consistency
    db.execute("DELETE FROM decoded_instructions")
    db.execute("DELETE FROM classified_events")

    tx_count = 0
    event_count = 0
    for row in rows:
        sig = row["signature"]
        tx_json = loads(row["json_blob"])
        if not isinstance(tx_json, dict):
            continue
        decoded = decode_transaction_instructions(sig, tx_json)
        persist_decoded_instructions(db, decoded)
        tx_count += 1

        slot = row["slot"]
        block_time = row["block_time"]

        for ix in decoded:
            if not ix.ix_type:
                continue
            mint = ix.args.get("mint")
            wallet = ix.args.get("user") or ix.args.get("source")
            sol_amount = ix.args.get("sol") or ix.args.get("sol_limit")
            token_amount = ix.args.get("token_amount")

            event_type = ix.ix_type
            if ix.ix_type in CREATE_INSTRUCTION_TYPES:
                event_type = "create"
            elif ix.ix_type in BUY_INSTRUCTION_TYPES or ix.ix_type.startswith("pumpswap_buy"):
                event_type = "buy" if "pumpswap" not in ix.ix_type else "pumpswap_buy"
                if wallet and mint:
                    td = token_delta_for_wallet_mint(tx_json, wallet, mint)
                    sd = sol_delta_for_wallet(tx_json, wallet)
                    if td is not None:
                        token_amount = td
                    if sd is not None:
                        # buys typically decrease SOL
                        sol_amount = abs(sd) if sd < 0 else sol_amount
            elif ix.ix_type in SELL_INSTRUCTION_TYPES or ix.ix_type.startswith("pumpswap_sell"):
                event_type = "sell" if "pumpswap" not in ix.ix_type else "pumpswap_sell"
                if wallet and mint:
                    td = token_delta_for_wallet_mint(tx_json, wallet, mint)
                    sd = sol_delta_for_wallet(tx_json, wallet)
                    if td is not None:
                        token_amount = abs(td)
                    if sd is not None:
                        sol_amount = sd if sd > 0 else sol_amount
            elif ix.ix_type == "migrate":
                event_type = "migrate"
            elif ix.ix_type == "sol_transfer":
                event_type = "sol_transfer"
                wallet = ix.args.get("source")
                sol_amount = ix.args.get("sol")

            persist_classified_event(
                db,
                signature=sig,
                slot=slot,
                block_time=block_time,
                event_type=event_type,
                mint=mint,
                wallet=wallet,
                sol_amount=float(sol_amount) if sol_amount is not None else None,
                token_amount=float(token_amount) if token_amount is not None else None,
                program_id=ix.program_id,
                details=ix.args,
            )
            event_count += 1

            # Mark PumpSwap touch as separate flag event
            if ix.program_id == PUMP_SWAP_PROGRAM_ID and mint:
                persist_classified_event(
                    db,
                    signature=sig,
                    slot=slot,
                    block_time=block_time,
                    event_type="pumpswap_touch",
                    mint=mint,
                    wallet=wallet,
                    sol_amount=None,
                    token_amount=None,
                    program_id=PUMP_SWAP_PROGRAM_ID,
                    details={"ix_type": ix.ix_type},
                )
                event_count += 1

        # Same-tx initial holders from token balance deltas (covers bundler buys
        # that share the create transaction even when buy ix layout varies).
        create_ixs = [ix for ix in decoded if ix.ix_type in CREATE_INSTRUCTION_TYPES]
        for cix in create_ixs:
            mint = cix.args.get("mint")
            if not mint:
                continue
            creator = cix.args.get("creator") or cix.args.get("user")
            bonding_curve = cix.args.get("bonding_curve")
            meta = tx_json.get("meta") or {}
            posts = meta.get("postTokenBalances") or []
            for entry in posts:
                if entry.get("mint") != mint:
                    continue
                owner = entry.get("owner")
                # Bonding curve holds reserves, not an early buyer.
                if not owner or owner == creator or owner == bonding_curve:
                    continue
                ui = (entry.get("uiTokenAmount") or {}).get("uiAmount")
                token_amount = float(ui) if ui is not None else None
                sol_spent = sol_delta_for_wallet(tx_json, owner)
                if sol_spent is not None and sol_spent < 0:
                    sol_spent = abs(sol_spent)
                else:
                    sol_spent = None
                persist_classified_event(
                    db,
                    signature=sig,
                    slot=slot,
                    block_time=block_time,
                    event_type="buy",
                    mint=mint,
                    wallet=owner,
                    sol_amount=sol_spent,
                    token_amount=token_amount,
                    program_id=PUMP_FUN_PROGRAM_ID,
                    details={
                        "source": "postTokenBalances_same_tx_as_create",
                        "create_ix_type": cix.ix_type,
                    },
                    evidence_level="balance_delta",
                )
                event_count += 1

    logger.info("Decoded %d txs into %d classified events", tx_count, event_count)
    return tx_count, event_count
