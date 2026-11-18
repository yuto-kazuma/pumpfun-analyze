"""Inspect pump buy/sell account layouts from stored raw txs."""

from __future__ import annotations

import json
from pathlib import Path

from pumpfun_intel.constants import (
    BUY_DISCRIMINATOR,
    BUY_EXACT_SOL_IN_DISCRIMINATOR,
    BUY_V2_DISCRIMINATOR,
    INSTRUCTION_TYPE_BY_DISC,
    PUMP_FUN_PROGRAM_ID,
    SELL_DISCRIMINATOR,
    SELL_V2_DISCRIMINATOR,
)
from pumpfun_intel.db.connection import Database
from pumpfun_intel.decoder.accounts import resolve_account_keys
from pumpfun_intel.decoder.instructions import decode_data_bytes

WANTED = {
    BUY_DISCRIMINATOR,
    BUY_V2_DISCRIMINATOR,
    BUY_EXACT_SOL_IN_DISCRIMINATOR,
    SELL_DISCRIMINATOR,
    SELL_V2_DISCRIMINATOR,
}


def main() -> None:
    db = Database(Path("data/pumpfun_intel.db"))
    rows = db.fetchall(
        """
        SELECT signature, json_blob FROM raw_transactions
        WHERE status='ok' AND json_blob IS NOT NULL
        ORDER BY block_time DESC
        LIMIT 400
        """
    )
    shown = 0
    for row in rows:
        tx = json.loads(row["json_blob"])
        keys = resolve_account_keys(tx)
        message = (tx.get("transaction") or {}).get("message") or {}
        for ix in message.get("instructions") or []:
            if ix.get("programId") != PUMP_FUN_PROGRAM_ID:
                continue
            data = decode_data_bytes(ix.get("data"))
            if not data or data[:8] not in WANTED:
                continue
            ix_type = INSTRUCTION_TYPE_BY_DISC[data[:8]]
            accs = ix.get("accounts") or []
            print("=" * 60)
            print(row["signature"][:20], ix_type, "n_accounts", len(accs))
            for i, a in enumerate(accs):
                print(f"  [{i}] {a}")
            print("args_hex_tail", data[8:24].hex())
            shown += 1
            if shown >= 8:
                db.close()
                return
    print("shown", shown)
    db.close()


if __name__ == "__main__":
    main()
