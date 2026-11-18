"""Deep pattern pass: mint probes + funding map + markdown summary."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pumpfun_intel.analyzer.funding import analyze_candidate_funding
from pumpfun_intel.analyzer.launches import analyze_launches
from pumpfun_intel.analyzer.patterns import write_pattern_report
from pumpfun_intel.clients.rpc import SolanaRpcClient
from pumpfun_intel.collector.mint_activity import probe_recent_launches
from pumpfun_intel.config import PROJECT_ROOT, load_settings, setup_logging
from pumpfun_intel.constants import DEFAULT_TARGET_WALLET
from pumpfun_intel.db.connection import Database


def main() -> None:
    settings = load_settings()
    setup_logging("INFO")
    creator = settings.target_wallet or DEFAULT_TARGET_WALLET
    rpc = SolanaRpcClient(settings.rpc_url, rps=18.0)

    print("== re-analyze ==")
    ar = analyze_launches(settings, wallet=creator, enrich_das=False)
    print(ar)

    db = Database(settings.database_path)
    print("== mint probe 40 ==")
    results = probe_recent_launches(
        db, rpc, limit=40, early_window_seconds=45
    )
    probe_payload = [
        {
            "mint": r.mint,
            "bonding_curve": r.bonding_curve,
            "signatures_seen": r.signatures_seen,
            "txs_ok": r.txs_ok,
            "early_buyers": r.early_buyers,
        }
        for r in results
    ]

    non_creator_reuse: Counter[str] = Counter()
    non_creator_hist: Counter[int] = Counter()
    for item in probe_payload:
        non = [b for b in item["early_buyers"] if not b.get("is_creator")]
        non_creator_hist[len(non)] += 1
        for b in non:
            non_creator_reuse[b["wallet"]] += 1

    candidates = [w for w, c in non_creator_reuse.most_common(12) if c >= 2]
    # also include high-frequency buyers from classified events
    event_buyers = db.fetchall(
        """
        SELECT wallet, COUNT(DISTINCT mint) AS mints
        FROM classified_events
        WHERE event_type='buy' AND wallet IS NOT NULL AND wallet != ?
        GROUP BY wallet
        HAVING mints >= 5
        ORDER BY mints DESC
        LIMIT 15
        """,
        (creator,),
    )
    for row in event_buyers:
        if row["wallet"] not in candidates:
            candidates.append(row["wallet"])
    candidates = candidates[:15]

    print("candidates", len(candidates), candidates[:5])
    print("non_creator_hist", dict(sorted(non_creator_hist.items())))

    print("== funding ==")
    funding = analyze_candidate_funding(
        db,
        rpc,
        candidates,
        creator=creator,
        max_signatures=50,
    )

    out_dir = PROJECT_ROOT / "data" / "reports"
    md_path, csv_path = write_pattern_report(
        db, out_dir, mint_probe_results=probe_payload
    )

    # Append deep funding section
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    deep_path = out_dir / f"deep_pattern_{ts}.md"
    lines = [
        "# Deep Pattern Findings",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Confirmed launcher mechanics",
        f"- Creator: `{creator}`",
        f"- Launches analyzed: {ar.launches}",
        "- Always create_v2 + same-tx self-buy style",
        "",
        "## Early non-creator participation (40-launch probe, 45s window)",
        f"- Histogram: `{dict(sorted(non_creator_hist.items()))}`",
        f"- Top reused non-creator wallets: `{non_creator_reuse.most_common(15)}`",
        "",
        "## Funding map (candidates)",
        f"- Candidates checked: `{candidates}`",
        f"- Directly funded by creator: `{funding.get('creator_funded_wallets')}`",
        f"- Common funders (appear for 2+ candidates): `{funding.get('common_funders')}`",
        f"- Top funders overall: `{funding.get('funder_counts')[:15]}`",
        f"- Per-wallet top sources: `{json.dumps(funding.get('by_wallet_top'), indent=2)}`",
        f"- Repeat funding amounts: `{funding.get('repeat_amounts')}`",
        "",
        "## Evidence levels",
        "- Strong: create_v2 frequency, self-buy, ~3 SOL open size",
        "- Moderate: reused early buyers across launches",
        "- Needs more data: shared control via funding (only if creator/common funder links exist)",
        "",
        f"Base report: `{md_path.name}`",
        f"CSV: `{csv_path.name}`",
        "",
    ]
    deep_path.write_text("\n".join(lines), encoding="utf-8")
    summary = {
        "launches": ar.launches,
        "probe_launches": len(probe_payload),
        "non_creator_hist": dict(sorted(non_creator_hist.items())),
        "top_reuse": non_creator_reuse.most_common(10),
        "creator_funded": funding.get("creator_funded_wallets"),
        "common_funders": funding.get("common_funders")[:10],
        "deep_report": str(deep_path),
        "pattern_report": str(md_path),
    }
    print(json.dumps(summary, indent=2))
    db.close()


if __name__ == "__main__":
    main()
