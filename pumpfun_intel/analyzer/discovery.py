"""Phase 6: pattern discovery without lookahead / causation claims."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from pumpfun_intel.analyzer.launch_metrics import compute_launch_metrics
from pumpfun_intel.analyzer.performance import compute_performance_windows
from pumpfun_intel.db.connection import Database


def _hour_utc(ts: int | None) -> int | None:
    if ts is None:
        return None
    return int((int(ts) % 86400) // 3600)


def discover_patterns(db: Database) -> dict[str, Any]:
    metrics = compute_launch_metrics(db)
    perf = compute_performance_windows(db)

    observations: list[str] = []
    consistent: list[str] = []
    unsupported: list[str] = []

    if metrics.empty:
        return {
            "consistent_patterns": [],
            "observations": ["No launch metrics available"],
            "unsupported": [],
            "tables": {},
        }

    # Launch-time features only (no future labels mixed into feature creation)
    metrics = metrics.copy()
    metrics["create_hour_utc"] = metrics["create_time"].map(_hour_utc)
    metrics["open_bucket"] = pd.cut(
        metrics["initial_buy_sol"].fillna(-1),
        bins=[-1, 0.05, 1, 3.5, 4.5, 5.5, 1e9],
        labels=["missing/dust", "small", "~3", "~4", "~5", "other"],
    )

    ix = metrics["create_ix_type"].value_counts(normalize=True)
    if not ix.empty and float(ix.iloc[0]) > 0.95:
        consistent.append(
            f"Create instruction is almost always `{ix.index[0]}` ({float(ix.iloc[0]):.0%} of launches)"
        )

    open_share = metrics["open_bucket"].value_counts(normalize=True)
    if "~3" in open_share.index and float(open_share.loc["~3"]) >= 0.4:
        consistent.append(
            f"Initial open size clusters near ~3 SOL ({float(open_share.loc['~3']):.0%} of launches)"
        )
    if "missing/dust" in open_share.index and float(open_share.loc["missing/dust"]) >= 0.2:
        observations.append(
            f"Dust/open-missing launches are common ({float(open_share.loc['missing/dust']):.0%})"
        )

    # Same-tx first buy delay
    delays = metrics["first_buy_delay_s"].dropna()
    if len(delays) > 20:
        zeroish = float((delays <= 2).mean())
        if zeroish >= 0.7:
            consistent.append(
                f"First observed buy is usually immediate (delay<=2s in {zeroish:.0%} of launches)"
            )

    # Seller behavior: label defined with future sells, so treat as outcome correlation only
    if not perf.empty:
        w5 = perf[perf["window"] == "5m"].copy()
        if not w5.empty and metrics["initial_buy_sol"].notna().any():
            merged = w5.merge(
                metrics[["mint", "initial_buy_sol", "open_bucket", "create_hour_utc"]],
                on="mint",
                how="left",
            )
            # Outcome proxy without claiming PnL: early unique buyers in 5m
            by_bucket = (
                merged.groupby("open_bucket", observed=False)["unique_buyers"]
                .median()
                .dropna()
            )
            if len(by_bucket) >= 2:
                observations.append(
                    "5m unique-buyer medians by open-size bucket: "
                    + ", ".join(f"{k}={v:.1f}" for k, v in by_bucket.items())
                )
                observations.append(
                    "This is correlation only; open size may select different launch modes"
                )

    hour_counts = Counter(metrics["create_hour_utc"].dropna().astype(int))
    if hour_counts:
        top_h, top_c = hour_counts.most_common(1)[0]
        observations.append(
            f"Most common create hour UTC: {top_h}:00 ({top_c} launches) (schedule observation only)"
        )

    sell_rate = float((metrics["sell_count_observed"] > 0).mean())
    observations.append(f"Observed creator-history sell activity on {sell_rate:.0%} of launches")

    unsupported.extend(
        [
            "Causal claim that bundler count causes better outcomes (insufficient labeled outcomes)",
            "Exact realized PnL per launch (requires complete fill/fee accounting)",
            "Shared custody of repeat early buyers without funding proof",
        ]
    )

    tables = {
        "open_bucket_counts": metrics["open_bucket"].value_counts(dropna=False).rename_axis("bucket").reset_index(name="count"),
        "create_hour_utc": (
            metrics["create_hour_utc"]
            .value_counts()
            .sort_index()
            .rename_axis("hour_utc")
            .reset_index(name="count")
        ),
    }
    return {
        "consistent_patterns": consistent,
        "observations": observations,
        "unsupported": unsupported,
        "tables": tables,
        "metrics": metrics,
        "performance": perf,
    }
