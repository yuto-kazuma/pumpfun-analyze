"""Inspect create txs for co-located buys and program IDs."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pumpfun_intel.constants import INSTRUCTION_TYPE_BY_DISC, PUMP_FUN_PROGRAM_ID
from pumpfun_intel.db.connection import Database
from pumpfun_intel.decoder.accounts import resolve_account_keys
from pumpfun_intel.decoder.instructions import decode_data_bytes


def main() -> None:
    db = Database(Path("data/pumpfun_intel.db"))
    rows = db.fetchall(
        """
        SELECT l.mint, l.create_signature, r.json_blob
        FROM token_launches l
        JOIN raw_transactions r ON r.signature = l.create_signature
        WHERE r.status='ok'
        ORDER BY l.create_time DESC
        LIMIT 20
        """
    )
    disc_counter: Counter[str] = Counter()
    for row in rows:
        tx = json.loads(row["json_blob"])
        keys = resolve_account_keys(tx)
        message = (tx.get("transaction") or {}).get("message") or {}
        outer = message.get("instructions") or []
        meta = tx.get("meta") or {}
        inner_groups = meta.get("innerInstructions") or []
        print("=" * 60)
        print("mint", row["mint"][:12], "sig", row["create_signature"][:16])
        print("signers", [k for k in keys[:3]])
        print("outer_count", len(outer), "inner_groups", len(inner_groups))
        for ix in outer:
            pid = ix.get("programId")
            data = decode_data_bytes(ix.get("data"))
            ix_type = None
            if data and len(data) >= 8:
                ix_type = INSTRUCTION_TYPE_BY_DISC.get(data[:8], data[:8].hex())
            print("  OUTER", pid[:8] if isinstance(pid, str) else pid, ix_type)
            if isinstance(ix_type, str):
                disc_counter[ix_type] += 1
        for g in inner_groups:
            for ix in g.get("instructions") or []:
                pid = ix.get("programId")
                data = decode_data_bytes(ix.get("data"))
                ix_type = None
                if data and len(data) >= 8:
                    ix_type = INSTRUCTION_TYPE_BY_DISC.get(data[:8], data[:8].hex())
                if pid == PUMP_FUN_PROGRAM_ID or ix_type:
                    print(
                        "  INNER",
                        (pid[:8] if isinstance(pid, str) else pid),
                        ix_type,
                    )
                    if isinstance(ix_type, str):
                        disc_counter[f"inner:{ix_type}"] += 1
        # token balance changes
        posts = meta.get("postTokenBalances") or []
        owners = sorted({p.get("owner") for p in posts if p.get("mint") == row["mint"]})
        print("post_token_owners", owners)
    print("\nDISC COUNTS", dict(disc_counter))
    # global buy event count
    buys = db.fetchone(
        "SELECT COUNT(*) c FROM classified_events WHERE event_type LIKE '%buy%'"
    )
    sells = db.fetchone(
        "SELECT COUNT(*) c FROM classified_events WHERE event_type LIKE '%sell%'"
    )
    creates = db.fetchone(
        "SELECT COUNT(*) c FROM classified_events WHERE event_type='create'"
    )
    print("events create/buy/sell", creates["c"], buys["c"], sells["c"])
    db.close()


if __name__ == "__main__":
    main()
