from pathlib import Path
import json

from pumpfun_intel.constants import CREATE_V2_DISCRIMINATOR, PUMP_FUN_PROGRAM_ID
from pumpfun_intel.db.connection import Database
from pumpfun_intel.decoder.instructions import decode_data_bytes

db = Database(Path("data/pumpfun_intel.db"))
rows = db.fetchall(
    """
    SELECT l.mint, l.symbol, l.create_signature, r.json_blob
    FROM token_launches l
    JOIN raw_transactions r ON r.signature = l.create_signature
    WHERE r.status='ok'
    ORDER BY l.create_time DESC
    LIMIT 3
    """
)
for row in rows:
    tx = json.loads(row["json_blob"])
    message = (tx.get("transaction") or {}).get("message") or {}
    print("=" * 60, row["symbol"], row["mint"][:12])
    for ix in message.get("instructions") or []:
        if ix.get("programId") != PUMP_FUN_PROGRAM_ID:
            continue
        data = decode_data_bytes(ix.get("data"))
        if not data or data[:8] != CREATE_V2_DISCRIMINATOR:
            continue
        for i, a in enumerate(ix.get("accounts") or []):
            print(f"  [{i}] {a}")
db.close()
