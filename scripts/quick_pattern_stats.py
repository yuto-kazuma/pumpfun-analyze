from collections import Counter
from pathlib import Path

from pumpfun_intel.db.connection import Database

db = Database(Path("data/pumpfun_intel.db"))
rows = db.fetchall("SELECT * FROM token_launches")
print("launches", len(rows))
sols = sorted(float(r["initial_buy_sol"]) for r in rows if r["initial_buy_sol"] is not None)
if sols:
    print("sol n/min/p50/p90/max", len(sols), sols[0], sols[len(sols)//2], sols[int(len(sols)*0.9)], sols[-1])
    buckets = Counter()
    for v in sols:
        if v < 0.05:
            buckets["dust_<0.05"] += 1
        elif v < 1:
            buckets["0.05-1"] += 1
        elif 2.5 <= v <= 3.5:
            buckets["~3"] += 1
        elif 3.5 < v <= 4.5:
            buckets["~4"] += 1
        elif 4.5 < v <= 5.5:
            buckets["~5"] += 1
        else:
            buckets["other"] += 1
    print("buckets", dict(buckets))
sells = sum(1 for r in rows if (r["sell_count"] or 0) > 0)
print("sell_rate", sells / max(len(rows), 1))
# burst launches same minute
from datetime import datetime, timezone
times = [r["create_time"] for r in rows if r["create_time"]]
minute = Counter(t // 60 for t in times)
bursts = sum(1 for _, c in minute.items() if c >= 2)
print("minutes_with_2plus_launches", bursts)
print("max_launches_same_minute", max(minute.values()) if minute else 0)
db.close()
