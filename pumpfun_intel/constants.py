"""On-chain program IDs and Anchor discriminators for Pump.fun / PumpSwap."""

from __future__ import annotations

import hashlib
from typing import Final

# Programs
PUMP_FUN_PROGRAM_ID: Final[str] = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_SWAP_PROGRAM_ID: Final[str] = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMP_FEES_PROGRAM_ID: Final[str] = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
SYSTEM_PROGRAM_ID: Final[str] = "11111111111111111111111111111111"
TOKEN_PROGRAM_ID: Final[str] = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID: Final[str] = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ASSOCIATED_TOKEN_PROGRAM_ID: Final[str] = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
WSOL_MINT: Final[str] = "So11111111111111111111111111111111111111112"

DEFAULT_TARGET_WALLET: Final[str] = "DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri"

LAMPORTS_PER_SOL: Final[int] = 1_000_000_000


def _anchor_disc(name: str) -> bytes:
    return hashlib.sha256(f"global:{name}".encode("utf-8")).digest()[:8]


def _account_disc(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode("utf-8")).digest()[:8]


def _event_disc(name: str) -> bytes:
    return hashlib.sha256(f"event:{name}".encode("utf-8")).digest()[:8]


# Instruction discriminators (verified against public IDL / docs)
CREATE_DISCRIMINATOR: Final[bytes] = bytes([24, 30, 200, 40, 5, 28, 7, 119])
CREATE_V2_DISCRIMINATOR: Final[bytes] = bytes([214, 144, 76, 236, 95, 139, 49, 180])
BUY_DISCRIMINATOR: Final[bytes] = bytes([102, 6, 61, 18, 1, 218, 235, 234])
SELL_DISCRIMINATOR: Final[bytes] = bytes([51, 230, 133, 164, 1, 127, 131, 173])
BUY_EXACT_SOL_IN_DISCRIMINATOR: Final[bytes] = bytes([56, 252, 116, 8, 158, 223, 205, 95])
BUY_V2_DISCRIMINATOR: Final[bytes] = bytes([184, 23, 238, 97, 103, 197, 211, 61])
SELL_V2_DISCRIMINATOR: Final[bytes] = bytes([93, 246, 130, 60, 231, 233, 64, 178])
# Post-Oct 2026 Pump.fun trade instructions (documented discriminators)
BUY_V3_DISCRIMINATOR: Final[bytes] = bytes.fromhex("07051dc4f5176550")
SELL_V3_DISCRIMINATOR: Final[bytes] = bytes.fromhex("1c92de7726c469d5")
BUY_EXACT_QUOTE_IN_V3_DISCRIMINATOR: Final[bytes] = bytes.fromhex("e1f7501ed5b38488")
MULTI_HOP_CURVE_SWAP_DISCRIMINATOR: Final[bytes] = bytes.fromhex("e19a7516d756f667")
MIGRATE_DISCRIMINATOR: Final[bytes] = bytes([155, 234, 231, 146, 236, 158, 162, 30])

# Sanity-check against Anchor naming (fail loudly if IDL drift in tests)
assert CREATE_DISCRIMINATOR == _anchor_disc("create")
assert CREATE_V2_DISCRIMINATOR == _anchor_disc("create_v2")
assert BUY_DISCRIMINATOR == _anchor_disc("buy")
assert SELL_DISCRIMINATOR == _anchor_disc("sell")
assert MIGRATE_DISCRIMINATOR == _anchor_disc("migrate")

BONDING_CURVE_ACCOUNT_DISCRIMINATOR: Final[bytes] = _account_disc("BondingCurve")
CREATE_EVENT_DISCRIMINATOR: Final[bytes] = _event_disc("CreateEvent")
TRADE_EVENT_DISCRIMINATOR: Final[bytes] = _event_disc("TradeEvent")

# Account indices for create (legacy Token + Metaplex metadata)
# mint=0, mint_authority=1, bonding_curve=2, associated_bonding_curve=3,
# global=4, mpl_token_metadata=5, metadata=6, user=7
CREATE_USER_ACCOUNT_INDEX: Final[int] = 7
CREATE_MINT_ACCOUNT_INDEX: Final[int] = 0
CREATE_BONDING_CURVE_ACCOUNT_INDEX: Final[int] = 2

# Account indices for create_v2
# mint=0, mint_authority=1, bonding_curve=2, associated_bonding_curve=3,
# global=4, user=5, ...
CREATE_V2_USER_ACCOUNT_INDEX: Final[int] = 5
CREATE_V2_MINT_ACCOUNT_INDEX: Final[int] = 0
CREATE_V2_BONDING_CURVE_ACCOUNT_INDEX: Final[int] = 2

# Buy instruction: user is commonly account index 6 on bonding-curve buy
BUY_USER_ACCOUNT_INDEX: Final[int] = 6
BUY_MINT_ACCOUNT_INDEX: Final[int] = 2

INSTRUCTION_TYPE_BY_DISC: Final[dict[bytes, str]] = {
    CREATE_DISCRIMINATOR: "create",
    CREATE_V2_DISCRIMINATOR: "create_v2",
    BUY_DISCRIMINATOR: "buy",
    SELL_DISCRIMINATOR: "sell",
    BUY_EXACT_SOL_IN_DISCRIMINATOR: "buy_exact_sol_in",
    BUY_V2_DISCRIMINATOR: "buy_v2",
    SELL_V2_DISCRIMINATOR: "sell_v2",
    BUY_V3_DISCRIMINATOR: "buy_v3",
    SELL_V3_DISCRIMINATOR: "sell_v3",
    BUY_EXACT_QUOTE_IN_V3_DISCRIMINATOR: "buy_exact_quote_in_v3",
    MULTI_HOP_CURVE_SWAP_DISCRIMINATOR: "multi_hop_curve_swap",
    MIGRATE_DISCRIMINATOR: "migrate",
}

BUY_INSTRUCTION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "buy",
        "buy_exact_sol_in",
        "buy_v2",
        "buy_v3",
        "buy_exact_quote_in_v3",
        "multi_hop_curve_swap",
    }
)
SELL_INSTRUCTION_TYPES: Final[frozenset[str]] = frozenset(
    {"sell", "sell_v2", "sell_v3"}
)
CREATE_INSTRUCTION_TYPES: Final[frozenset[str]] = frozenset({"create", "create_v2"})
