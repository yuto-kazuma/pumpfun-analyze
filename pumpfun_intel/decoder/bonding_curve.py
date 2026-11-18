"""Bonding curve account layout helpers.

Prefer bonding_curve pubkeys taken from create/create_v2 instruction accounts.
PDA derivation is intentionally omitted here to avoid fragile pure-Python
ed25519 off-curve checks; use on-chain account indexes as source of truth.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

import base58

from pumpfun_intel.constants import BONDING_CURVE_ACCOUNT_DISCRIMINATOR


@dataclass
class BondingCurveState:
    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    token_total_supply: int
    complete: bool
    creator: str | None = None


def decode_bonding_curve_account(data: bytes) -> BondingCurveState | None:
    if len(data) < 49:
        return None
    if data[:8] != BONDING_CURVE_ACCOUNT_DISCRIMINATOR:
        return None
    values = struct.unpack_from("<5Q", data, 8)
    complete = bool(data[48])
    creator = None
    if len(data) >= 49 + 32:
        creator = base58.b58encode(data[49:81]).decode("ascii")
    return BondingCurveState(
        virtual_token_reserves=values[0],
        virtual_sol_reserves=values[1],
        real_token_reserves=values[2],
        real_sol_reserves=values[3],
        token_total_supply=values[4],
        complete=complete,
        creator=creator,
    )


def curve_progress_approx(state: BondingCurveState) -> float | None:
    """Approximate bonding-curve progress from real SOL reserves (legacy heuristic)."""
    target = 85_000_000_000  # ~85 SOL historical graduation threshold
    return min(1.0, state.real_sol_reserves / target)


def summarize_curve(state: BondingCurveState) -> dict[str, Any]:
    return {
        "virtual_token_reserves": state.virtual_token_reserves,
        "virtual_sol_reserves": state.virtual_sol_reserves,
        "real_token_reserves": state.real_token_reserves,
        "real_sol_reserves": state.real_sol_reserves,
        "token_total_supply": state.token_total_supply,
        "complete": state.complete,
        "creator": state.creator,
        "progress_approx": curve_progress_approx(state),
    }
