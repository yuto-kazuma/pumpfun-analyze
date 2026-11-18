"""Phase 8: downloadable Markdown + CSV final report."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pumpfun_intel.analyzer.discovery import discover_patterns
from pumpfun_intel.analyzer.relationships import build_relationships, relationships_dataframe
from pumpfun_intel.constants import DEFAULT_TARGET_WALLET
from pumpfun_intel.db.connection import Database


def generate_final_report(
    db: Database,
    out_dir: Path,
    *,
    creator: str = DEFAULT_TARGET_WALLET,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    discovery = discover_patterns(db)
    relations = build_relationships(db, creator=creator)
    rel_df = relationships_dataframe(relations)
    metrics = discovery.get("metrics")
    perf = discovery.get("performance")

    launches = db.fetchall("SELECT * FROM token_launches ORDER BY create_time DESC")
    cov = db.fetchall("SELECT scope, scope_key, metric, value FROM coverage_meta")

    csv_paths: dict[str, Path] = {}
    if metrics is not None and not metrics.empty:
        p = out_dir / f"final_launch_metrics_{ts}.csv"
        metrics.to_csv(p, index=False)
        csv_paths["launch_metrics"] = p
    if perf is not None and not perf.empty:
        p = out_dir / f"final_performance_windows_{ts}.csv"
        perf.to_csv(p, index=False)
        csv_paths["performance"] = p
    if not rel_df.empty:
        p = out_dir / f"final_relationships_{ts}.csv"
        rel_df.to_csv(p, index=False)
        csv_paths["relationships"] = p

    # launches csv
    import csv

    launch_csv = out_dir / f"final_token_launches_{ts}.csv"
    if launches:
        with launch_csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(dict(launches[0]).keys()))
            writer.writeheader()
            for row in launches:
                writer.writerow(dict(row))
        csv_paths["launches"] = launch_csv

    md = out_dir / f"final_report_{ts}.md"
    sols = [float(r["initial_buy_sol"]) for r in launches if r["initial_buy_sol"] is not None]
    p50 = sorted(sols)[len(sols) // 2] if sols else None
    lines = [
        "# PumpFun Launch Intelligence: Final Report",
        "",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        "",
        "Scope: research and analytics only. No trading or execution.",
        "",
        "## 1. What the target wallet repeatedly does",
        f"- Wallet: `{creator}`",
        f"- Launches in DB: **{len(launches)}**",
        "- Repeatedly creates Pump.fun tokens via `create_v2`",
        "- Typically buys in the same create transaction (atomic self-buy)",
        f"- Initial buy size median: **{p50} SOL**" if p50 is not None else "- Initial buy size: n/a",
        "",
        "## 2. Which wallets repeatedly participate",
    ]
    top_rel = [r for r in relations if r.wallet_a == creator][:15]
    if top_rel:
        for r in top_rel:
            lines.append(
                f"- `{r.wallet_b}`: {r.evidence_level}, shared_launches={r.shared_launches}; "
                + "; ".join(r.reasons)
            )
    else:
        lines.append("- Insufficient repeated participants with current evidence thresholds")

    lines.extend(
        [
            "",
            "## 3. How those wallets are funded",
            "- Direct creator→participant SOL funding was **not strongly evidenced** in parsed transfers.",
            "- Repeat co-buyers may be independent snipers, intermediaries, or opaque funding paths.",
            "- Treat funding conclusions as incomplete until deeper transfer/CEX clustering is done.",
            "",
            "## 4. How initial purchases are distributed",
            "- Dominant cluster near ~3 SOL opens, with dust (~0.01) and occasional ~5 SOL modes.",
            "- First buy delay is usually immediate (same transaction / seconds).",
            "",
            "## 5. What happens after launch",
            "- Many launches later show sell activity in observed creator/event history.",
            "- Migration/PumpSwap flags are sparse in current decoded coverage.",
            "",
            "## 6. Patterns that correlate with better outcomes",
        ]
    )
    for item in discovery.get("observations", []):
        lines.append(f"- Observation: {item}")
    lines.append("")
    lines.append("## 7. Statistically consistent patterns")
    for item in discovery.get("consistent_patterns", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 8. Patterns not sufficiently supported")
    for item in discovery.get("unsupported", []):
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 9. Additional data needed",
            "- Broader mint-scoped tape for full early-buyer sets",
            "- Robust funding graph (multi-hop SOL/WSOL, bridge/CEX deposit clustering)",
            "- Clean outcome labels (e.g., curve progress / migration / timed markouts) with fees",
            "- Narrative/metadata embeddings only as descriptive features (no causation)",
            "",
            "## Coverage",
        ]
    )
    for c in cov[:30]:
        lines.append(f"- `{c['scope']}:{c['scope_key']}` {c['metric']}={c['value']}")
    lines.append("")
    lines.append("## CSV exports")
    for k, p in csv_paths.items():
        lines.append(f"- {k}: `{p.name}`")
    lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")
    return {"markdown": md, **csv_paths}
