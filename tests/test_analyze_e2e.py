"""End-to-end analyze path using synthetic stored transactions (no network)."""

from __future__ import annotations

import struct
from pathlib import Path

import base58

from pumpfun_intel.analyzer.launches import analyze_launches
from pumpfun_intel.config import Settings
from pumpfun_intel.constants import BUY_DISCRIMINATOR, CREATE_DISCRIMINATOR, PUMP_FUN_PROGRAM_ID
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import dumps, upsert_raw_transaction, upsert_signature

WALLET = "DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri"
MINT = "So11111111111111111111111111111111111111112"
BONDING = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def _borsh_str(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _create_data() -> str:
    data = (
        CREATE_DISCRIMINATOR
        + _borsh_str("E2EToken")
        + _borsh_str("E2E")
        + _borsh_str("https://example.com/e2e.json")
        + base58.b58decode(WALLET)
    )
    return base58.b58encode(data).decode("ascii")


def _buy_data() -> str:
    data = BUY_DISCRIMINATOR + struct.pack("<QQ", 1_000_000, 100_000_000)
    return base58.b58encode(data).decode("ascii")


def test_analyze_builds_launch_from_raw_tx(tmp_path: Path) -> None:
    db_path = tmp_path / "e2e.db"
    db = Database(db_path)
    sig = "e2eSigCreateBuy111111111111111111111111111111111"
    accounts = [
        MINT,
        "mint_auth",
        BONDING,
        "assoc",
        "global",
        "mpl",
        "meta",
        WALLET,
    ]
    buy_accounts = [BONDING, "global", MINT, "assoc", "user_ata", "creator_vault", WALLET]
    tx = {
        "slot": 42,
        "blockTime": 1_700_000_000,
        "transaction": {
            "signatures": [sig],
            "message": {
                "accountKeys": [{"pubkey": k} for k in accounts + buy_accounts],
                "instructions": [
                    {
                        "programId": PUMP_FUN_PROGRAM_ID,
                        "accounts": accounts,
                        "data": _create_data(),
                    },
                    {
                        "programId": PUMP_FUN_PROGRAM_ID,
                        "accounts": buy_accounts,
                        "data": _buy_data(),
                    },
                ],
            },
        },
        "meta": {
            "err": None,
            "innerInstructions": [],
            "preBalances": [10_000_000_000] * 20,
            "postBalances": [9_900_000_000] + [10_000_000_000] * 19,
            "preTokenBalances": [],
            "postTokenBalances": [
                {
                    "mint": MINT,
                    "owner": WALLET,
                    "uiTokenAmount": {"uiAmount": 1000.0},
                }
            ],
            "logMessages": [],
        },
    }
    upsert_signature(
        db,
        signature=sig,
        wallet=WALLET,
        slot=42,
        block_time=1_700_000_000,
        err_json=None,
    )
    upsert_raw_transaction(
        db,
        signature=sig,
        slot=42,
        block_time=1_700_000_000,
        status="ok",
        json_blob=dumps(tx),
    )
    db.close()

    settings = Settings(
        helius_api_key="test-key-not-used",
        rpc_url="http://127.0.0.1:8899",
        target_wallet=WALLET,
        database_path=db_path,
        cache_dir=tmp_path / "cache",
        rpc_rps=1.0,
        helius_rps=1.0,
        log_level="WARNING",
    )
    result = analyze_launches(settings, wallet=WALLET, enrich_das=False)
    assert result.launches == 1
    assert result.events >= 2

    db = Database(db_path)
    launch = db.fetchone("SELECT * FROM token_launches WHERE mint = ?", (MINT,))
    assert launch is not None
    assert launch["symbol"] == "E2E"
    assert launch["creator"] == WALLET
    assert launch["create_signature"] == sig
    parts = db.fetchall("SELECT role, wallet FROM launch_participants WHERE mint = ?", (MINT,))
    roles = {(r["role"], r["wallet"]) for r in parts}
    assert ("creator", WALLET) in roles
    assert ("initial_buyer", WALLET) in roles
    db.close()
