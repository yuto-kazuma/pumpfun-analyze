"""Phase 5: fixed-window performance metrics (coverage-aware)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from pumpfun_intel.db.connection import Database

WINDOWS_S = {
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
}


def _proxy_price(sol_amount: float | None, token_amount: float | None) -> float | None:
    if sol_amount is None or token_amount is None:
        return None
    if float(token_amount) <= 0:
        return None
    return float(sol_amount) / float(token_amount)


def compute_performance_windows(db: Database) -> pd.DataFrame:
    """
    Approximate window metrics from classified buy/sell events.

    This is NOT exchange-grade mark-to-market. Missing mint-tape coverage means
    volume/unique traders are lower bounds. Price is a crude sol/token proxy
    from trade legs when both sides are present.
    """
    launches = db.fetchall(
        "SELECT mint, symbol, create_time, initial_buy_sol, migrated FROM token_launches"
    )
    events = db.fetchall(
        """
        SELECT mint, wallet, event_type, block_time, sol_amount, token_amount
        FROM classified_events
        WHERE mint IS NOT NULL AND block_time IS NOT NULL
          AND event_type IN ('buy','sell','pumpswap_buy','pumpswap_sell')
        """
    )
    by_mint: dict[str, list[Any]] = {}
    for e in events:
        by_mint.setdefault(str(e["mint"]), []).append(e)

    rows: list[dict[str, Any]] = []
    for L in launches:
        mint = str(L["mint"])
        create_t = L["create_time"]
        if create_t is None:
            continue
        create_t = int(create_t)
        ev = by_mint.get(mint, [])
        for label, secs in WINDOWS_S.items():
            end = create_t + secs
            window = [e for e in ev if create_t <= int(e["block_time"]) <= end]
            buys = [e for e in window if "buy" in e["event_type"]]
            sells = [e for e in window if "sell" in e["event_type"]]
            buyers = {e["wallet"] for e in buys if e["wallet"]}
            sellers = {e["wallet"] for e in sells if e["wallet"]}
            buy_sol = sum(float(e["sol_amount"]) for e in buys if e["sol_amount"] is not None)
            sell_sol = sum(float(e["sol_amount"]) for e in sells if e["sol_amount"] is not None)
            prices = [
                p
                for e in window
                for p in [_proxy_price(e["sol_amount"], e["token_amount"])]
                if p is not None
            ]
            max_px = max(prices) if prices else None
            min_px = min(prices) if prices else None
            start_px = prices[0] if prices else None
            drawdown = None
            if max_px and min_px is not None and max_px > 0:
                drawdown = (max_px - min_px) / max_px

            rows.append(
                {
                    "mint": mint,
                    "symbol": L["symbol"],
                    "window": label,
                    "window_seconds": secs,
                    "unique_buyers": len(buyers),
                    "unique_sellers": len(sellers),
                    "buy_sol_volume": buy_sol,
                    "sell_sol_volume": sell_sol,
                    "net_sol_flow_proxy": buy_sol - sell_sol,
                    "trade_count": len(window),
                    "max_price_proxy": max_px,
                    "min_price_proxy": min_px,
                    "start_price_proxy": start_px,
                    "drawdown_proxy": drawdown,
                    "migrated_flag": L["migrated"],
                    "initial_buy_sol": L["initial_buy_sol"],
                    "coverage": "partial_observed_events_only",
                    "realized_pnl": None,  # requires full position accounting; not claimed
                    "notes": "Price/volume are proxies from decoded legs; fees/slippage not fully netted",
                }
            )
    return pd.DataFrame(rows)
