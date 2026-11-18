"""Print account metas for buy_v3 / buy_exact_quote_in_v3 instructions."""

from __future__ import annotations

import json
from pathlib import Path

from pumpfun_intel.constants import (
    BUY_EXACT_QUOTE_IN_V3_DISCRIMINATOR,
    BUY_V3_DISCRIMINATOR,
    PUMP_FUN_PROGRAM_ID,
)
from pumpfun_intel.db.connection import Database
from pumpfun_intel.decoder.instructions import decode_data_bytes

WANTED = {BUY_V3_DISCRIMINATOR, BUY_EXACT_QUOTE_IN_V3_DISCRIMINATOR}


def main() -> None:
    db = Database(Path("data/pumpfun_intel.db"))
    rows = db.fetchall(
        """
        SELECT signature, json_blob FROM raw_transactions
        WHERE status='ok' LIMIT 800
        """
    )
    shown = 0
    for row in rows:
        tx = json.loads(row["json_blob"])
        message = (tx.get("transaction") or {}).get("message") or {}
        groups = [(False, message.get("instructions") or [])]
        for g in (tx.get("meta") or {}).get("innerInstructions") or []:
            groups.append((True, g.get("instructions") or []))
        for is_inner, ixs in groups:
            for ix in ixs:
                if ix.get("programId") != PUMP_FUN_PROGRAM_ID:
                    continue
                data = decode_data_bytes(ix.get("data"))
                if not data or data[:8] not in WANTED:
                    continue
                label = "buy_v3" if data[:8] == BUY_V3_DISCRIMINATOR else "buy_exact_quote_in_v3"
                accs = ix.get("accounts") or []
                print("=" * 50, label, "inner" if is_inner else "outer")
                print("sig", row["signature"][:24], "n", len(accs))
                for i, a in enumerate(accs):
                    print(f"  [{i}] {a}")
                shown += 1
                if shown >= 6:
                    db.close()
                    return
    print("shown", shown)
    db.close()


if __name__ == "__main__":
    main()
