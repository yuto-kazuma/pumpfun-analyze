from pathlib import Path
import json
import struct

from pumpfun_intel.constants import BUY_EXACT_QUOTE_IN_V3_DISCRIMINATOR, BUY_V3_DISCRIMINATOR
from pumpfun_intel.db.connection import Database
from pumpfun_intel.decoder.instructions import decode_data_bytes

db = Database(Path("data/pumpfun_intel.db"))
rows = db.fetchall(
    "SELECT signature, json_blob FROM raw_transactions WHERE status='ok' LIMIT 1200"
)
counts = {"buy_v3": 0, "buy_exact": 0}
for row in rows:
    tx = json.loads(row["json_blob"])
    message = (tx.get("transaction") or {}).get("message") or {}
    groups = [message.get("instructions") or []]
    for g in (tx.get("meta") or {}).get("innerInstructions") or []:
        groups.append(g.get("instructions") or [])
    for ixs in groups:
        for ix in ixs:
            data = decode_data_bytes(ix.get("data"))
            if not data or len(data) < 16:
                continue
            if data[:8] == BUY_V3_DISCRIMINATOR and counts["buy_v3"] < 3:
                a, b = struct.unpack_from("<QQ", data, 8)
                print("buy_v3", row["signature"][:16], "u64s", a, b, "sol_a", a / 1e9, "len", len(data))
                counts["buy_v3"] += 1
            if data[:8] == BUY_EXACT_QUOTE_IN_V3_DISCRIMINATOR and counts["buy_exact"] < 3:
                a, b = struct.unpack_from("<QQ", data, 8)
                print(
                    "exact",
                    row["signature"][:16],
                    "u64s",
                    a,
                    b,
                    "sol_a",
                    a / 1e9,
                    "len",
                    len(data),
                )
                counts["buy_exact"] += 1
    if counts["buy_v3"] >= 3 and counts["buy_exact"] >= 3:
        break
db.close()
