"""Launch pattern summaries for the analysis milestone (research only)."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pumpfun_intel.db.connection import Database


@dataclass
class PatternSummary:
    launches: int
    launches_per_day: float | None
    create_ix_types: dict[str, int]
    initial_buy_sol_stats: dict[str, float]
    same_tx_buyer_counts: Counter
    early_buyer_reuse: list[tuple[str, int]]
    helper_accounts: list[tuple[str, int]]
    sell_rate: float
    notes: list[str]


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    ordered = sorted(vals)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return ordered[idx]


def build_pattern_summary(db: Database, early_window_seconds: int = 60) -> PatternSummary:
    launches = db.fetchall("SELECT * FROM token_launches ORDER BY create_time DESC")
    notes: list[str] = []
    times = [int(r["create_time"]) for r in launches if r["create_time"] is not None]
    lpd = None
    if len(times) >= 2:
        span_days = (max(times) - min(times)) / 86400
        lpd = len(times) / span_days if span_days > 0 else None

    ix_types = Counter(r["create_ix_type"] or "?" for r in launches)
    sols = [float(r["initial_buy_sol"]) for r in launches if r["initial_buy_sol"] is not None]
    sol_stats = {
        "n": float(len(sols)),
        "min": min(sols) if sols else 0.0,
        "p50": _pct(sols, 0.5),
        "p90": _pct(sols, 0.9),
        "max": max(sols) if sols else 0.0,
        "mean": (sum(sols) / len(sols)) if sols else 0.0,
    }
    if sols:
        notes.append(
            "initial_buy_sol mixes exact quote-in amounts and buy_v3 max_sol ceilings; "
            "treat large outliers as ceilings unless corroborated."
        )

    # Same-tx / early buyers from events
    buys = db.fetchall(
        """
        SELECT e.mint, e.wallet, e.signature, e.sol_amount, e.block_time,
               l.create_signature, l.create_time, l.creator
        FROM classified_events e
        JOIN token_launches l ON l.mint = e.mint
        WHERE e.event_type = 'buy' AND e.wallet IS NOT NULL
        """
    )
    same_tx_counts: Counter[str] = Counter()
    early_counts: Counter[str] = Counter()
    buyers_per_mint: dict[str, set[str]] = defaultdict(set)
    for b in buys:
        w = b["wallet"]
        if not w or w == b["creator"]:
            continue
        buyers_per_mint[b["mint"]].add(w)
        if b["signature"] == b["create_signature"]:
            same_tx_counts[w] += 1
        if (
            b["block_time"] is not None
            and b["create_time"] is not None
            and 0 <= int(b["block_time"]) - int(b["create_time"]) <= early_window_seconds
        ):
            early_counts[w] += 1

    sizes = [len(v) for v in buyers_per_mint.values()]
    if sizes:
        notes.append(
            f"Observed unique early/buy wallets per mint (from available events): "
            f"min={min(sizes)} median={sorted(sizes)[len(sizes)//2]} max={max(sizes)}."
        )
        notes.append(
            "Creator-wallet history alone usually shows 1 same-tx buyer; "
            "additional bundlers require mint/curve probes."
        )

    # Helper accounts repeatedly present as non-fee-payer signers on create txs
    helper_counter: Counter[str] = Counter()
    creates = db.fetchall(
        """
        SELECT l.create_signature, r.json_blob
        FROM token_launches l
        JOIN raw_transactions r ON r.signature = l.create_signature
        WHERE r.status = 'ok' AND r.json_blob IS NOT NULL
        """
    )
    for row in creates:
        tx = json.loads(row["json_blob"])
        keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
        for i, k in enumerate(keys[:6]):
            pk = k["pubkey"] if isinstance(k, dict) else k
            signer = bool(k.get("signer")) if isinstance(k, dict) else (i == 0)
            if signer and i > 0:
                helper_counter[str(pk)] += 1

    sold = sum(1 for r in launches if (r["sell_count"] or 0) > 0)
    sell_rate = sold / len(launches) if launches else 0.0

    return PatternSummary(
        launches=len(launches),
        launches_per_day=lpd,
        create_ix_types=dict(ix_types),
        initial_buy_sol_stats=sol_stats,
        same_tx_buyer_counts=same_tx_counts,
        early_buyer_reuse=early_counts.most_common(25),
        helper_accounts=helper_counter.most_common(10),
        sell_rate=sell_rate,
        notes=notes,
    )


def write_pattern_report(
    db: Database,
    out_dir: Path,
    *,
    mint_probe_results: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = build_pattern_summary(db)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    md_path = out_dir / f"pattern_report_{ts}.md"
    csv_path = out_dir / f"token_launches_{ts}.csv"

    # CSV export of launches
    launches = db.fetchall(
        """
        SELECT mint, name, symbol, creator, create_ix_type, create_signature,
               create_time, initial_buy_sol, initial_buyer_count, early_buyer_count,
               subsequent_buy_count, sell_count, migrated, pumpswap_touched, coverage_notes
        FROM token_launches
        ORDER BY create_time DESC
        """
    )
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        if launches:
            writer = csv.DictWriter(fh, fieldnames=list(dict(launches[0]).keys()))
            writer.writeheader()
            for row in launches:
                writer.writerow(dict(row))

    # Mint probe aggregation
    probe_section = ""
    if mint_probe_results:
        buyer_reuse: Counter[str] = Counter()
        non_creator_reuse: Counter[str] = Counter()
        buyer_count_hist: Counter[int] = Counter()
        non_creator_hist: Counter[int] = Counter()
        for item in mint_probe_results:
            buyers = item.get("early_buyers") or []
            non_creators = [b for b in buyers if not b.get("is_creator")]
            buyer_count_hist[len(buyers)] += 1
            non_creator_hist[len(non_creators)] += 1
            for b in buyers:
                buyer_reuse[b["wallet"]] += 1
                if not b.get("is_creator"):
                    non_creator_reuse[b["wallet"]] += 1
        probe_section = "\n".join(
            [
                "## Mint-scoped early buyer probe",
                "",
                f"- Launches probed: **{len(mint_probe_results)}**",
                f"- All early-buyer count histogram: `{dict(sorted(buyer_count_hist.items()))}`",
                f"- Non-creator early-buyer histogram: `{dict(sorted(non_creator_hist.items()))}`",
                f"- Most reused non-creator early buyers: `{non_creator_reuse.most_common(15)}`",
                "",
                "Evidence note: wallets appearing in multiple probed launches are "
                "**candidates** for bundler/tooling wallets. Shared control is **not** "
                "assumed from co-buying alone.",
                "",
            ]
        )

    lines = [
        "# PumpFun Launch Intelligence — Pattern Report",
        "",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        "",
        "Scope: **research / analytics only**. No trading or execution.",
        "",
        "## Target wallet behavior",
        "",
        f"- Target: `DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri`",
        f"- Launches analyzed: **{summary.launches}**",
        f"- Approx launches/day: **{summary.launches_per_day:.2f}**"
        if summary.launches_per_day
        else "- Approx launches/day: n/a",
        f"- Create instruction types: `{summary.create_ix_types}`",
        f"- Share of launches with ≥1 observed sell in creator history: "
        f"**{summary.sell_rate:.1%}**",
        "",
        "## Initial buy distribution",
        "",
        f"- Stats (SOL): `{summary.initial_buy_sol_stats}`",
        "",
        "## Repeated participants (from available buy events)",
        "",
        f"- Top early buyers by launch count: `{summary.early_buyer_reuse[:15]}`",
        f"- Same-tx buyer reuse: `{summary.same_tx_buyer_counts.most_common(15)}`",
        "",
        "## Helper / tooling accounts on create txs",
        "",
        f"- Repeated extra signers: `{summary.helper_accounts}`",
        "",
        probe_section,
        "## Caveats",
        "",
    ]
    for note in summary.notes:
        lines.append(f"- {note}")
    lines.extend(
        [
            "- Coverage is incomplete until wallet backfill finishes and more mint probes run.",
            "- Do not treat correlation as causation.",
            "",
            f"CSV export: `{csv_path.name}`",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, csv_path
