"""Classifier tests over synthetic getTransaction-shaped payloads."""

from __future__ import annotations

import struct

import base58

from pumpfun_intel.constants import (
    BUY_DISCRIMINATOR,
    CREATE_DISCRIMINATOR,
    MIGRATE_DISCRIMINATOR,
    PUMP_FUN_PROGRAM_ID,
    PUMP_SWAP_PROGRAM_ID,
    SELL_DISCRIMINATOR,
)
from pumpfun_intel.decoder.instructions import decode_transaction_instructions


CREATOR = "DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri"
MINT = "So11111111111111111111111111111111111111112"
BONDING = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def _borsh_str(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _create_data() -> str:
    data = (
        CREATE_DISCRIMINATOR
        + _borsh_str("Alpha")
        + _borsh_str("ALP")
        + _borsh_str("https://example.com/a.json")
        + base58.b58decode(CREATOR)
    )
    return base58.b58encode(data).decode("ascii")


def _buy_data() -> str:
    data = BUY_DISCRIMINATOR + struct.pack("<QQ", 1_000_000, 50_000_000)
    return base58.b58encode(data).decode("ascii")


def _sell_data() -> str:
    data = SELL_DISCRIMINATOR + struct.pack("<QQ", 1_000_000, 1)
    return base58.b58encode(data).decode("ascii")


def _migrate_data() -> str:
    return base58.b58encode(MIGRATE_DISCRIMINATOR).decode("ascii")


def _tx(instructions: list[dict], account_keys: list[str], signature: str = "sig1") -> dict:
    return {
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [{"pubkey": k, "signer": False, "writable": True} for k in account_keys],
                "instructions": instructions,
            },
        },
        "meta": {"innerInstructions": [], "err": None, "logMessages": []},
        "slot": 1,
        "blockTime": 1_700_000_000,
    }


def test_decode_create_and_buy_in_one_tx() -> None:
    accounts = [
        MINT,
        "mint_auth",
        BONDING,
        "assoc",
        "global",
        "mpl",
        "meta",
        CREATOR,
        "buyer_ata",
        "extra1",
        "extra2",
        "extra3",
        "extra4",
        "extra5",
        CREATOR,
    ]
    # Minimal buy accounts layout: pad so index 2=mint, 6=user
    buy_accounts = [BONDING, "global", MINT, "assoc", "user_ata", "creator_vault", CREATOR]
    ix_create = {
        "programId": PUMP_FUN_PROGRAM_ID,
        "accounts": accounts[:8],
        "data": _create_data(),
    }
    ix_buy = {
        "programId": PUMP_FUN_PROGRAM_ID,
        "accounts": buy_accounts,
        "data": _buy_data(),
    }
    tx = _tx([ix_create, ix_buy], accounts)
    decoded = decode_transaction_instructions("sig1", tx)
    types = [d.ix_type for d in decoded]
    assert "create" in types
    assert "buy" in types
    create = next(d for d in decoded if d.ix_type == "create")
    assert create.args["name"] == "Alpha"
    assert create.args["mint"] == MINT
    assert create.args["creator"] == CREATOR


def test_sell_and_migrate_classification() -> None:
    accounts = [CREATOR, MINT, BONDING, "a", "b", "c", CREATOR]
    sell_accounts = [BONDING, "global", MINT, "assoc", "user_ata", "creator_vault", CREATOR]
    ix_sell = {
        "programId": PUMP_FUN_PROGRAM_ID,
        "accounts": sell_accounts,
        "data": _sell_data(),
    }
    ix_mig = {
        "programId": PUMP_FUN_PROGRAM_ID,
        "accounts": accounts,
        "data": _migrate_data(),
    }
    tx = _tx([ix_sell, ix_mig], accounts, signature="sig2")
    decoded = decode_transaction_instructions("sig2", tx)
    types = {d.ix_type for d in decoded}
    assert "sell" in types
    assert "migrate" in types


def test_pumpswap_buy_tagged_separately() -> None:
    buy_accounts = [BONDING, "global", MINT, "assoc", "user_ata", "creator_vault", CREATOR]
    ix_buy = {
        "programId": PUMP_SWAP_PROGRAM_ID,
        "accounts": buy_accounts,
        "data": _buy_data(),
    }
    tx = _tx([ix_buy], buy_accounts, signature="sig3")
    decoded = decode_transaction_instructions("sig3", tx)
    assert len(decoded) == 1
    assert decoded[0].ix_type == "pumpswap_buy"


def test_log_only_create_not_classified_without_instruction() -> None:
    """Logs alone must not produce create classification."""
    tx = _tx([], [CREATOR], signature="sig4")
    tx["meta"]["logMessages"] = [
        "Program log: Instruction: Create",
        "Program data: aaaaa",
    ]
    decoded = decode_transaction_instructions("sig4", tx)
    assert decoded == []
