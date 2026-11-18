"""Optional Anchor event parsing from transaction logs (corroboration only)."""

from __future__ import annotations

import base64
import logging
from typing import Any

from pumpfun_intel.constants import CREATE_EVENT_DISCRIMINATOR, TRADE_EVENT_DISCRIMINATOR
from pumpfun_intel.decoder.instructions import read_borsh_string, read_pubkey

logger = logging.getLogger(__name__)


def extract_program_data_blobs(logs: list[str] | None) -> list[bytes]:
    blobs: list[bytes] = []
    if not logs:
        return blobs
    for line in logs:
        if not isinstance(line, str):
            continue
        marker = "Program data: "
        if marker not in line:
            continue
        payload = line.split(marker, 1)[1].strip()
        try:
            blobs.append(base64.b64decode(payload))
        except Exception:  # noqa: BLE001
            continue
    return blobs


def parse_create_event(data: bytes) -> dict[str, Any] | None:
    if len(data) < 8 or data[:8] != CREATE_EVENT_DISCRIMINATOR:
        return None
    try:
        offset = 8
        name, offset = read_borsh_string(data, offset)
        symbol, offset = read_borsh_string(data, offset)
        uri, offset = read_borsh_string(data, offset)
        mint, offset = read_pubkey(data, offset)
        bonding_curve, offset = read_pubkey(data, offset)
        user, offset = read_pubkey(data, offset)
        return {
            "name": name,
            "symbol": symbol,
            "uri": uri,
            "mint": mint,
            "bonding_curve": bonding_curve,
            "user": user,
        }
    except ValueError as exc:
        logger.debug("CreateEvent parse failed: %s", exc)
        return None


def parse_trade_event(data: bytes) -> dict[str, Any] | None:
    """Best-effort TradeEvent parse; layout may evolve. Treat as corroboration."""
    if len(data) < 8 or data[:8] != TRADE_EVENT_DISCRIMINATOR:
        return None
    # Minimal: mint and user appear after several u64s in common layouts;
    # without a frozen IDL we only flag presence.
    return {"present": True, "raw_len": len(data)}


def events_from_tx(tx_json: dict[str, Any]) -> list[dict[str, Any]]:
    logs = (tx_json.get("meta") or {}).get("logMessages") or []
    out: list[dict[str, Any]] = []
    for blob in extract_program_data_blobs(logs):
        create = parse_create_event(blob)
        if create:
            out.append({"event": "CreateEvent", **create})
            continue
        trade = parse_trade_event(blob)
        if trade:
            out.append({"event": "TradeEvent", **trade})
    return out
