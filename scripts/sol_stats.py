from collections import Counter
from pathlib import Path

from pumpfun_intel.db.connection import Database

db = Database(Path("data/pumpfun_intel.db"))
rows = db.fetchall(
    "SELECT initial_buy_sol FROM token_launches WHERE initial_buy_sol IS NOT NULL"
)
vals = sorted(float(r["initial_buy_sol"]) for r in rows)
print("n", len(vals))
if vals:
    print("min", vals[0], "p50", vals[len(vals)//2], "p90", vals[int(len(vals)*0.9)], "max", vals[-1])
    buckets = Counter()
    for v in vals:
        if v < 0.1:
            buckets["<0.1"] += 1
        elif v < 1:
            buckets["0.1-1"] += 1
        elif v < 5:
            buckets["1-5"] += 1
        elif v < 20:
            buckets["5-20"] += 1
        else:
            buckets[">=20"] += 1
    print(dict(buckets))

# helper account frequency on create txs
helpers = db.fetchall(
    """
    SELECT json_extract(details_json, '$.user') AS u, COUNT(*) c
    FROM classified_events
    WHERE event_type='create'
    GROUP BY 1
    """
)
print("create users", [(r["u"], r["c"]) for r in helpers[:5]])
db.close()
