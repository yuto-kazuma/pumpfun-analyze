"""Bonding curve account decode tests."""

from __future__ import annotations

import struct

import base58

from pumpfun_intel.constants import BONDING_CURVE_ACCOUNT_DISCRIMINATOR
from pumpfun_intel.decoder.bonding_curve import decode_bonding_curve_account


def test_decode_bonding_curve_account() -> None:
    creator = base58.b58decode("DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri")
    body = BONDING_CURVE_ACCOUNT_DISCRIMINATOR + struct.pack(
        "<5Q",
        800_000_000_000,
        30_000_000_000,
        700_000_000_000,
        10_000_000_000,
        1_000_000_000_000,
    )
    body += bytes([0])  # complete=false
    body += creator
    state = decode_bonding_curve_account(body)
    assert state is not None
    assert state.complete is False
    assert state.real_sol_reserves == 10_000_000_000
    assert state.creator == "DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri"


def test_reject_wrong_discriminator() -> None:
    assert decode_bonding_curve_account(b"\x00" * 64) is None
