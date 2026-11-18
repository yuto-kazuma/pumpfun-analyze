"""Quick preview of launch findings for client update."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pumpfun_intel.db.connection import Database


def main() -> None:
    db = Database(Path("data/pumpfun_intel.db"))
    launches = db.fetchall(
        """
        SELECT mint, name, symbol, creator, create_user, create_ix_type,
               create_time, initial_buy_sol, initial_buyer_count, early_buyer_count,
               subsequent_buy_count, sell_count, migrated, pumpswap_touched
        FROM token_launches
        ORDER BY create_time DESC
        """
    )
    print(f"launches={len(launches)}")
    times = [r["create_time"] for r in launches if r["create_time"]]
    if times:
        span_h = (max(times) - min(times)) / 3600
        print(f"create_time_span_hours={span_h:.1f}")
        print(
            "first",
            datetime.fromtimestamp(min(times), tz=timezone.utc).isoformat(),
        )
        print(
            "last",
            datetime.fromtimestamp(max(times), tz=timezone.utc).isoformat(),
        )
        if span_h > 0:
            print(f"launches_per_day={len(times) / (span_h / 24):.2f}")

    ix = Counter(r["create_ix_type"] or "?" for r in launches)
    print("create_ix_types", dict(ix))
    migrated = sum(1 for r in launches if r["migrated"])
    print(f"migrated={migrated}")
    with_initial = sum(1 for r in launches if (r["initial_buy_sol"] or 0) > 0)
    print(f"with_initial_buy_sol={with_initial}")
    print(
        "avg_initial_buy_sol",
        round(
            sum(r["initial_buy_sol"] or 0 for r in launches) / max(len(launches), 1),
            4,
        ),
    )

    creators = Counter(r["creator"] for r in launches if r["creator"])
    print("top_creators", creators.most_common(5))

    # Same-tx buys / early buyers from events
    buys = db.fetchall(
        """
        SELECT e.mint, e.wallet, e.signature, e.sol_amount, e.block_time, l.create_signature, l.create_time
        FROM classified_events e
        JOIN token_launches l ON l.mint = e.mint
        WHERE e.event_type IN ('buy', 'pumpswap_buy')
        """
    )
    same_tx_buyers: Counter[str] = Counter()
    early_buyers: Counter[str] = Counter()
    for b in buys:
        if not b["wallet"]:
            continue
        if b["signature"] == b["create_signature"]:
            same_tx_buyers[b["wallet"]] += 1
        if (
            b["block_time"] is not None
            and b["create_time"] is not None
            and int(b["block_time"]) - int(b["create_time"]) <= 60
        ):
            early_buyers[b["wallet"]] += 1

    print("unique_same_tx_buyers", len(same_tx_buyers))
    print("top_same_tx_buyers", same_tx_buyers.most_common(10))
    print("unique_early_buyers_60s", len(early_buyers))
    print("top_early_buyers_60s", early_buyers.most_common(10))

    print("\nRecent launches:")
    for r in launches[:15]:
        ts = (
            datetime.fromtimestamp(r["create_time"], tz=timezone.utc).isoformat()
            if r["create_time"]
            else "?"
        )
        print(
            f"  {ts} {r['symbol'] or '?':8} ix={r['create_ix_type']} "
            f"init_sol={r['initial_buy_sol']} early={r['early_buyer_count']} "
            f"sells={r['sell_count']} mig={r['migrated']} mint={r['mint'][:8]}…"
        )

    cov = db.fetchall(
        "SELECT metric, value FROM coverage_meta WHERE scope='wallet'"
    )
    print("\ncoverage", {r["metric"]: r["value"] for r in cov})
    db.close()


if __name__ == "__main__":
    main()
