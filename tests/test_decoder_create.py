"""Unit tests for create / create_v2 instruction decoding."""

from __future__ import annotations

import struct

import base58
import pytest

from pumpfun_intel.constants import (
    CREATE_DISCRIMINATOR,
    CREATE_V2_DISCRIMINATOR,
    PUMP_FUN_PROGRAM_ID,
    _anchor_disc,
)
from pumpfun_intel.decoder.instructions import (
    classify_pump_instruction,
    parse_create_args,
)


def _borsh_str(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _pubkey(b58: str) -> bytes:
    return base58.b58decode(b58)


CREATOR = "DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri"
MINT = "So11111111111111111111111111111111111111112"
BONDING = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
USER = CREATOR


def _build_create_data(*, v2: bool = False) -> bytes:
    disc = CREATE_V2_DISCRIMINATOR if v2 else CREATE_DISCRIMINATOR
    body = (
        _borsh_str("TestToken")
        + _borsh_str("TEST")
        + _borsh_str("https://example.com/meta.json")
        + _pubkey(CREATOR)
    )
    if v2:
        body += bytes([0])  # is_mayhem_mode
        body += bytes([0])  # OptionBool None
    return disc + body


def test_anchor_discriminators_match_documented_bytes() -> None:
    assert CREATE_DISCRIMINATOR == _anchor_disc("create")
    assert CREATE_V2_DISCRIMINATOR == _anchor_disc("create_v2")


def test_parse_create_args() -> None:
    data = _build_create_data(v2=False)
    args = parse_create_args(data)
    assert args["name"] == "TestToken"
    assert args["symbol"] == "TEST"
    assert args["uri"] == "https://example.com/meta.json"
    assert args["creator"] == CREATOR


def test_parse_create_v2_args() -> None:
    data = _build_create_data(v2=True)
    args = parse_create_args(data)
    assert args["name"] == "TestToken"
    assert args["creator"] == CREATOR
    assert args.get("is_mayhem_mode") is False


def test_classify_create_instruction_accounts() -> None:
    data = _build_create_data(v2=False)
    # create user is index 7
    accounts = [MINT, "mint_auth", BONDING, "abc", "global", "mpl", "meta", USER]
    ix_type, disc, args = classify_pump_instruction(PUMP_FUN_PROGRAM_ID, data, accounts)
    assert ix_type == "create"
    assert disc == CREATE_DISCRIMINATOR
    assert args["mint"] == MINT
    assert args["bonding_curve"] == BONDING
    assert args["user"] == USER
    assert args["creator"] == CREATOR


def test_classify_create_v2_user_index() -> None:
    data = _build_create_data(v2=True)
    accounts = [MINT, "mint_auth", BONDING, "abc", "global", USER]
    ix_type, disc, args = classify_pump_instruction(PUMP_FUN_PROGRAM_ID, data, accounts)
    assert ix_type == "create_v2"
    assert disc == CREATE_V2_DISCRIMINATOR
    assert args["user"] == USER
    assert args["mint"] == MINT


def test_non_pump_program_ignored() -> None:
    data = _build_create_data()
    ix_type, disc, args = classify_pump_instruction("11111111111111111111111111111111", data, [])
    assert ix_type is None
    assert disc is None
    assert args == {}
