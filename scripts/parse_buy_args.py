from pathlib import Path
import json

from pumpfun_intel.constants import BUY_EXACT_QUOTE_IN_V3_DISCRIMINATOR, BUY_V3_DISCRIMINATOR
from pumpfun_intel.db.connection import Database
from pumpfun_intel.decoder.instructions import decode_data_bytes, parse_buy_sell_args

db = Database(Path("data/pumpfun_intel.db"))
rows = db.fetchall(
    "SELECT json_blob FROM raw_transactions WHERE status='ok' LIMIT 800"
)
for row in rows:
    tx = json.loads(row["json_blob"])
    message = (tx.get("transaction") or {}).get("message") or {}
    groups = [message.get("instructions") or []]
    for g in (tx.get("meta") or {}).get("innerInstructions") or []:
        groups.append(g.get("instructions") or [])
    for ixs in groups:
        for ix in ixs:
            data = decode_data_bytes(ix.get("data"))
            if not data:
                continue
            if data[:8] in (BUY_V3_DISCRIMINATOR, BUY_EXACT_QUOTE_IN_V3_DISCRIMINATOR):
                print(data[:8].hex(), parse_buy_sell_args(data), "raw_len", len(data))
                print("full_after_disc", data[8:].hex())
                db.close()
                raise SystemExit
print("none")
db.close()
