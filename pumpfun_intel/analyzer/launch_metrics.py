"""Phase 4: per-launch pattern metrics."""

from __future__ import annotations

from typing import Any

import pandas as pd

from pumpfun_intel.db.connection import Database


def compute_launch_metrics(db: Database) -> pd.DataFrame:
    launches = db.fetchall(
        """
        SELECT mint, name, symbol, creator, create_signature, create_time,
               initial_buy_sol, initial_buyer_count, early_buyer_count,
               subsequent_buy_count, sell_count, migrated, pumpswap_touched,
               create_ix_type, bonding_curve
        FROM token_launches
        ORDER BY create_time DESC
        """
    )
    events = db.fetchall(
        """
        SELECT mint, wallet, event_type, signature, block_time, sol_amount, token_amount
        FROM classified_events
        WHERE mint IS NOT NULL
        """
    )
    by_mint: dict[str, list[Any]] = {}
    for e in events:
        by_mint.setdefault(str(e["mint"]), []).append(e)

    rows: list[dict[str, Any]] = []
    for L in launches:
        mint = str(L["mint"])
        create_t = L["create_time"]
        ev = by_mint.get(mint, [])
        buys = [
            e
            for e in ev
            if e["event_type"] in ("buy", "pumpswap_buy") and e["block_time"] is not None
        ]
        sells = [
            e
            for e in ev
            if e["event_type"] in ("sell", "pumpswap_sell") and e["block_time"] is not None
        ]
        buys.sort(key=lambda x: int(x["block_time"]))
        sells.sort(key=lambda x: int(x["block_time"]))

        first_buy_delay = None
        buy_gaps: list[float] = []
        if create_t is not None and buys:
            first_buy_delay = int(buys[0]["block_time"]) - int(create_t)
            for i in range(1, min(len(buys), 20)):
                buy_gaps.append(int(buys[i]["block_time"]) - int(buys[i - 1]["block_time"]))

        first_sell_delay = None
        if create_t is not None and sells:
            first_sell_delay = int(sells[0]["block_time"]) - int(create_t)

        wallets = {e["wallet"] for e in buys if e["wallet"]}
        sol_by_wallet: dict[str, float] = {}
        for e in buys:
            if not e["wallet"] or e["sol_amount"] is None:
                continue
            sol_by_wallet[e["wallet"]] = sol_by_wallet.get(e["wallet"], 0.0) + float(
                e["sol_amount"]
            )
        total_sol = sum(sol_by_wallet.values())
        top_share = (
            (max(sol_by_wallet.values()) / total_sol) if sol_by_wallet and total_sol > 0 else None
        )
        creator_sells = sum(1 for e in sells if e["wallet"] == L["creator"])

        rows.append(
            {
                "mint": mint,
                "name": L["name"],
                "symbol": L["symbol"],
                "create_time": create_t,
                "create_ix_type": L["create_ix_type"],
                "initial_buy_sol": L["initial_buy_sol"],
                "first_buy_delay_s": first_buy_delay,
                "median_buy_gap_s": (
                    sorted(buy_gaps)[len(buy_gaps) // 2] if buy_gaps else None
                ),
                "unique_buyers_observed": len(wallets),
                "buy_count_observed": len(buys),
                "sell_count_observed": len(sells),
                "first_sell_delay_s": first_sell_delay,
                "creator_sell_count": creator_sells,
                "buy_concentration_top_wallet": top_share,
                "total_buy_sol_observed": total_sol if total_sol else None,
                "migrated": L["migrated"],
                "pumpswap_touched": L["pumpswap_touched"],
                "coverage_note": "metrics from observed/classified txs only; not full market tape",
            }
        )
    return pd.DataFrame(rows)
