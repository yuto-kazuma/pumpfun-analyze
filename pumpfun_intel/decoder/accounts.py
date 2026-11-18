"""Resolve account keys for legacy and v0 (ALT) transactions."""

from __future__ import annotations

from typing import Any


def _key_str(entry: Any) -> str | None:
    if entry is None:
        return None
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        pk = entry.get("pubkey")
        if isinstance(pk, str):
            return pk
        if isinstance(pk, dict) and "toString" not in pk:
            # Rare nested forms
            return str(pk)
    return str(entry)


def resolve_account_keys(tx_json: dict[str, Any]) -> list[str]:
    """
    Build the full account key list for a getTransaction jsonParsed payload.

    For v0 transactions, append loadedAddresses.writable then .readonly.
    """
    message = (tx_json.get("transaction") or {}).get("message") or {}
    keys_raw = message.get("accountKeys") or []
    keys: list[str] = []
    for entry in keys_raw:
        s = _key_str(entry)
        if s:
            keys.append(s)

    meta = tx_json.get("meta") or {}
    loaded = meta.get("loadedAddresses") or {}
    for entry in loaded.get("writable") or []:
        s = _key_str(entry)
        if s:
            keys.append(s)
    for entry in loaded.get("readonly") or []:
        s = _key_str(entry)
        if s:
            keys.append(s)
    return keys


def accounts_from_indexes(account_keys: list[str], indexes: list[int]) -> list[str]:
    out: list[str] = []
    for idx in indexes:
        if 0 <= idx < len(account_keys):
            out.append(account_keys[idx])
        else:
            out.append("")
    return out
