"""Decode Pump.fun / PumpSwap instructions via program ID + discriminators."""

from __future__ import annotations

import base64
import logging
import struct
from dataclasses import dataclass, field
from typing import Any

import base58

from pumpfun_intel.constants import (
    BUY_INSTRUCTION_TYPES,
    BUY_MINT_ACCOUNT_INDEX,
    BUY_USER_ACCOUNT_INDEX,
    CREATE_BONDING_CURVE_ACCOUNT_INDEX,
    CREATE_INSTRUCTION_TYPES,
    CREATE_MINT_ACCOUNT_INDEX,
    CREATE_USER_ACCOUNT_INDEX,
    CREATE_V2_BONDING_CURVE_ACCOUNT_INDEX,
    CREATE_V2_MINT_ACCOUNT_INDEX,
    CREATE_V2_USER_ACCOUNT_INDEX,
    INSTRUCTION_TYPE_BY_DISC,
    PUMP_FUN_PROGRAM_ID,
    PUMP_SWAP_PROGRAM_ID,
    SELL_INSTRUCTION_TYPES,
    SYSTEM_PROGRAM_ID,
)
from pumpfun_intel.decoder.accounts import accounts_from_indexes, resolve_account_keys

logger = logging.getLogger(__name__)


@dataclass
class DecodedInstruction:
    signature: str
    ix_index: int
    inner_index: int | None
    is_inner: bool
    program_id: str
    discriminator: bytes | None
    ix_type: str | None
    accounts: list[str] = field(default_factory=list)
    args: dict[str, Any] = field(default_factory=dict)
    raw_data_b58: str | None = None


def decode_data_bytes(data: Any) -> bytes | None:
    """Decode instruction data from jsonParsed / base58 / base64 forms."""
    if data is None:
        return None
    if isinstance(data, bytes):
        return data
    if isinstance(data, list):
        # Sometimes [bytes, encoding]
        if len(data) == 2 and isinstance(data[0], str):
            payload, enc = data[0], data[1]
            if enc == "base64":
                return base64.b64decode(payload)
            if enc == "base58":
                return base58.b58decode(payload)
        try:
            return bytes(data)
        except Exception:  # noqa: BLE001
            return None
    if isinstance(data, str):
        # Prefer base58 (Solana default for non-parsed), fall back to base64
        try:
            return base58.b58decode(data)
        except Exception:  # noqa: BLE001
            try:
                return base64.b64decode(data)
            except Exception:  # noqa: BLE001
                return None
    return None


def read_borsh_string(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 4 > len(data):
        raise ValueError("truncated borsh string length")
    (length,) = struct.unpack_from("<I", data, offset)
    offset += 4
    if offset + length > len(data):
        raise ValueError("truncated borsh string body")
    text = data[offset : offset + length].decode("utf-8", errors="replace")
    return text, offset + length


def read_pubkey(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 32 > len(data):
        raise ValueError("truncated pubkey")
    raw = data[offset : offset + 32]
    return base58.b58encode(raw).decode("ascii"), offset + 32


def parse_create_args(data: bytes) -> dict[str, Any]:
    """Parse create / create_v2 args after the 8-byte discriminator."""
    offset = 8
    name, offset = read_borsh_string(data, offset)
    symbol, offset = read_borsh_string(data, offset)
    uri, offset = read_borsh_string(data, offset)
    creator, offset = read_pubkey(data, offset)
    out: dict[str, Any] = {
        "name": name,
        "symbol": symbol,
        "uri": uri,
        "creator": creator,
    }
    # create_v2 optional trailing flags
    if offset < len(data):
        out["is_mayhem_mode"] = bool(data[offset])
        offset += 1
    if offset < len(data):
        tag = data[offset]
        offset += 1
        if tag == 1 and offset < len(data):
            out["is_cashback_enabled"] = bool(data[offset])
        elif tag == 0:
            out["is_cashback_enabled"] = None
    return out


def parse_buy_sell_args(data: bytes, ix_type: str | None = None) -> dict[str, Any]:
    """Parse common buy/sell u64 args (amount, max_sol / min_sol / quote_in)."""
    offset = 8
    out: dict[str, Any] = {}
    if offset + 8 > len(data):
        return out
    (first,) = struct.unpack_from("<Q", data, offset)
    offset += 8
    second: int | None = None
    if offset + 8 <= len(data):
        (second,) = struct.unpack_from("<Q", data, offset)

    # buy_exact_quote_in_v3: spendable quote (SOL lamports), then min tokens / flag
    if ix_type == "buy_exact_quote_in_v3":
        out["sol_limit_lamports"] = first
        out["sol_limit"] = first / 1_000_000_000
        out["sol_amount"] = out["sol_limit"]
        if second is not None:
            out["min_tokens_or_flag"] = second
        return out

    # Default / buy_v3 / sell*: token amount then SOL limit
    out["token_amount"] = first
    if second is not None:
        out["sol_limit_lamports"] = second
        out["sol_limit"] = second / 1_000_000_000
        if ix_type in {"buy", "buy_v2", "buy_v3", "buy_exact_sol_in"}:
            out["sol_amount"] = out["sol_limit"]
    return out


def _program_id_from_ix(ix: dict[str, Any], account_keys: list[str]) -> str | None:
    if "programId" in ix and isinstance(ix["programId"], str):
        return ix["programId"]
    if "programIdIndex" in ix:
        idx = ix["programIdIndex"]
        if isinstance(idx, int) and 0 <= idx < len(account_keys):
            return account_keys[idx]
    parsed = ix.get("parsed")
    if isinstance(parsed, dict) and "programId" in parsed:
        return str(parsed["programId"])
    return None


def _accounts_from_ix(ix: dict[str, Any], account_keys: list[str]) -> list[str]:
    if "accounts" in ix and ix["accounts"] and isinstance(ix["accounts"][0], str):
        return list(ix["accounts"])
    if "accounts" in ix and ix["accounts"] and isinstance(ix["accounts"][0], int):
        return accounts_from_indexes(account_keys, list(ix["accounts"]))
    # jsonParsed sometimes uses accountKey objects
    accs = ix.get("accounts") or []
    out: list[str] = []
    for a in accs:
        if isinstance(a, str):
            out.append(a)
        elif isinstance(a, dict) and "pubkey" in a:
            out.append(str(a["pubkey"]))
        elif isinstance(a, int):
            out.extend(accounts_from_indexes(account_keys, [a]))
    return out


def _data_from_ix(ix: dict[str, Any]) -> Any:
    if "data" in ix:
        return ix["data"]
    parsed = ix.get("parsed")
    if isinstance(parsed, dict) and "data" in parsed:
        return parsed["data"]
    return None


def classify_pump_instruction(
    program_id: str,
    data: bytes | None,
    accounts: list[str],
) -> tuple[str | None, bytes | None, dict[str, Any]]:
    if program_id not in (PUMP_FUN_PROGRAM_ID, PUMP_SWAP_PROGRAM_ID):
        return None, None, {}
    if not data or len(data) < 8:
        return None, None, {}
    disc = data[:8]
    ix_type = INSTRUCTION_TYPE_BY_DISC.get(disc)
    if ix_type is None:
        return "unknown_pump", disc, {}

    args: dict[str, Any] = {}
    if ix_type in CREATE_INSTRUCTION_TYPES:
        try:
            args = parse_create_args(data)
        except ValueError as exc:
            logger.debug("create args parse failed: %s", exc)
            args = {"parse_error": str(exc)}
        if ix_type == "create":
            mint_i = CREATE_MINT_ACCOUNT_INDEX
            bc_i = CREATE_BONDING_CURVE_ACCOUNT_INDEX
            user_i = CREATE_USER_ACCOUNT_INDEX
        else:
            mint_i = CREATE_V2_MINT_ACCOUNT_INDEX
            bc_i = CREATE_V2_BONDING_CURVE_ACCOUNT_INDEX
            user_i = CREATE_V2_USER_ACCOUNT_INDEX
        args["mint"] = accounts[mint_i] if len(accounts) > mint_i else None
        args["bonding_curve"] = accounts[bc_i] if len(accounts) > bc_i else None
        args["user"] = accounts[user_i] if len(accounts) > user_i else None
        if not args.get("creator") and args.get("user"):
            args["creator"] = args["user"]
    elif ix_type in BUY_INSTRUCTION_TYPES or ix_type in SELL_INSTRUCTION_TYPES:
        args = parse_buy_sell_args(data, ix_type=ix_type)
        # Classic buy/sell: mint@2 user@6.
        # buy_v3 / buy_exact_quote_in_v3 / sell_v3 (17 accounts):
        #   mint@1, bonding_curve@5, user@8
        if ix_type in {"buy_v3", "buy_exact_quote_in_v3", "sell_v3", "multi_hop_curve_swap"}:
            if len(accounts) > 1:
                args["mint"] = accounts[1]
            if len(accounts) > 5:
                args["bonding_curve"] = accounts[5]
            if len(accounts) > 8:
                args["user"] = accounts[8]
        else:
            if len(accounts) > BUY_MINT_ACCOUNT_INDEX:
                args["mint"] = accounts[BUY_MINT_ACCOUNT_INDEX]
            if len(accounts) > BUY_USER_ACCOUNT_INDEX:
                args["user"] = accounts[BUY_USER_ACCOUNT_INDEX]
        if not args.get("mint") and accounts:
            args["mint"] = accounts[0]
        if not args.get("user") and accounts:
            args["user"] = accounts[-1]
    elif ix_type == "migrate":
        if accounts:
            args["user"] = accounts[0]
        if len(accounts) > 1:
            args["mint"] = accounts[1] if len(accounts) > 2 else accounts[-1]
        # Prefer known layout: mint often near front after user
        for cand in accounts[:6]:
            if cand and cand != args.get("user"):
                args.setdefault("mint", cand)
                break

    if program_id == PUMP_SWAP_PROGRAM_ID and ix_type in (
        "buy",
        "sell",
        "buy_v2",
        "sell_v2",
    ):
        ix_type = f"pumpswap_{ix_type}"

    return ix_type, disc, args


def decode_transaction_instructions(
    signature: str,
    tx_json: dict[str, Any],
) -> list[DecodedInstruction]:
    account_keys = resolve_account_keys(tx_json)
    message = (tx_json.get("transaction") or {}).get("message") or {}
    outer = message.get("instructions") or []
    meta = tx_json.get("meta") or {}
    inner_groups = meta.get("innerInstructions") or []

    decoded: list[DecodedInstruction] = []

    for ix_index, ix in enumerate(outer):
        program_id = _program_id_from_ix(ix, account_keys)
        if not program_id:
            continue
        accounts = _accounts_from_ix(ix, account_keys)
        raw = _data_from_ix(ix)
        data = decode_data_bytes(raw)
        ix_type, disc, args = classify_pump_instruction(program_id, data, accounts)

        # System transfers (SOL)
        if program_id == SYSTEM_PROGRAM_ID:
            parsed = ix.get("parsed")
            if isinstance(parsed, dict) and parsed.get("type") == "transfer":
                info = parsed.get("info") or {}
                ix_type = "sol_transfer"
                args = {
                    "source": info.get("source"),
                    "destination": info.get("destination"),
                    "lamports": info.get("lamports"),
                    "sol": (int(info["lamports"]) / 1_000_000_000)
                    if info.get("lamports") is not None
                    else None,
                }
                disc = None

        if ix_type is None and program_id not in (
            PUMP_FUN_PROGRAM_ID,
            PUMP_SWAP_PROGRAM_ID,
        ):
            continue

        decoded.append(
            DecodedInstruction(
                signature=signature,
                ix_index=ix_index,
                inner_index=None,
                is_inner=False,
                program_id=program_id,
                discriminator=disc,
                ix_type=ix_type,
                accounts=accounts,
                args=args,
                raw_data_b58=base58.b58encode(data).decode("ascii") if data else None,
            )
        )

    for group in inner_groups:
        outer_index = group.get("index", 0)
        for inner_index, ix in enumerate(group.get("instructions") or []):
            program_id = _program_id_from_ix(ix, account_keys)
            if not program_id:
                continue
            accounts = _accounts_from_ix(ix, account_keys)
            raw = _data_from_ix(ix)
            data = decode_data_bytes(raw)
            ix_type, disc, args = classify_pump_instruction(program_id, data, accounts)

            if program_id == SYSTEM_PROGRAM_ID:
                parsed = ix.get("parsed")
                if isinstance(parsed, dict) and parsed.get("type") == "transfer":
                    info = parsed.get("info") or {}
                    ix_type = "sol_transfer"
                    args = {
                        "source": info.get("source"),
                        "destination": info.get("destination"),
                        "lamports": info.get("lamports"),
                        "sol": (int(info["lamports"]) / 1_000_000_000)
                        if info.get("lamports") is not None
                        else None,
                    }
                    disc = None

            if ix_type is None and program_id not in (
                PUMP_FUN_PROGRAM_ID,
                PUMP_SWAP_PROGRAM_ID,
            ):
                continue

            decoded.append(
                DecodedInstruction(
                    signature=signature,
                    ix_index=int(outer_index),
                    inner_index=inner_index,
                    is_inner=True,
                    program_id=program_id,
                    discriminator=disc,
                    ix_type=ix_type,
                    accounts=accounts,
                    args=args,
                    raw_data_b58=base58.b58encode(data).decode("ascii") if data else None,
                )
            )

    return decoded
