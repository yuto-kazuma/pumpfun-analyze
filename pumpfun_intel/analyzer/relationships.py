"""Phase 3: wallet relationship analysis with evidence levels."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import pandas as pd

from pumpfun_intel.constants import DEFAULT_TARGET_WALLET
from pumpfun_intel.db.connection import Database


@dataclass
class WalletRelation:
    wallet_a: str
    wallet_b: str
    evidence_level: str  # strong | moderate | weak
    reasons: list[str]
    shared_launches: int
    details: dict[str, Any]


def _early_buyers_by_mint(db: Database, creator: str) -> dict[str, set[str]]:
    rows = db.fetchall(
        """
        SELECT mint, wallet, role
        FROM launch_participants
        WHERE wallet IS NOT NULL AND wallet != ?
        """,
        (creator,),
    )
    out: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        out[str(r["mint"])].add(str(r["wallet"]))

    # Also include classified early buys
    buys = db.fetchall(
        """
        SELECT e.mint, e.wallet, e.block_time, l.create_time, l.creator
        FROM classified_events e
        JOIN token_launches l ON l.mint = e.mint
        WHERE e.event_type = 'buy'
          AND e.wallet IS NOT NULL
          AND e.wallet != l.creator
        """
    )
    for b in buys:
        if b["block_time"] is None or b["create_time"] is None:
            continue
        if 0 <= int(b["block_time"]) - int(b["create_time"]) <= 60:
            out[str(b["mint"])].add(str(b["wallet"]))
    return out


def _sol_transfer_edges(db: Database, creator: str) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT signature, block_time, wallet, sol_amount, details_json
        FROM classified_events
        WHERE event_type = 'sol_transfer'
        """
    )
    edges: list[dict[str, Any]] = []
    import json

    for r in rows:
        details = json.loads(r["details_json"] or "{}")
        src = details.get("source")
        dst = details.get("destination")
        sol = r["sol_amount"]
        if not src or not dst:
            continue
        edges.append(
            {
                "signature": r["signature"],
                "block_time": r["block_time"],
                "source": src,
                "destination": dst,
                "sol": float(sol) if sol is not None else details.get("sol"),
                "involves_creator": creator in (src, dst),
            }
        )
    return edges


def build_relationships(
    db: Database,
    *,
    creator: str = DEFAULT_TARGET_WALLET,
    min_shared_launches: int = 2,
) -> list[WalletRelation]:
    by_mint = _early_buyers_by_mint(db, creator)
    pair_mints: dict[tuple[str, str], set[str]] = defaultdict(set)
    wallet_launch_count: Counter[str] = Counter()

    for mint, wallets in by_mint.items():
        for w in wallets:
            wallet_launch_count[w] += 1
        ws = sorted(wallets)
        for i, a in enumerate(ws):
            for b in ws[i + 1 :]:
                pair_mints[(a, b)].add(mint)

    transfers = _sol_transfer_edges(db, creator)
    transfer_pairs: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in transfers:
        a, b = sorted([e["source"], e["destination"]])
        transfer_pairs[(a, b)].append(e)

    # Creator <-> participant funding
    creator_fund_targets = Counter(
        e["destination"] for e in transfers if e["source"] == creator and e["destination"]
    )

    relations: list[WalletRelation] = []

    # Creator to frequent co-buyers
    for wallet, n in wallet_launch_count.most_common(100):
        if n < min_shared_launches:
            continue
        reasons: list[str] = [
            f"Participated in {n} launches involving creator early-buy window"
        ]
        level = "weak"
        details: dict[str, Any] = {"shared_launches": n}
        if creator_fund_targets.get(wallet, 0) > 0:
            reasons.append(
                f"Observed direct SOL transfer(s) from creator ({creator_fund_targets[wallet]})"
            )
            level = "strong"
            details["creator_funding_transfers"] = creator_fund_targets[wallet]
        elif n >= 5:
            level = "moderate"
            reasons.append("Repeated co-participation across many launches (no direct funding proven)")
        relations.append(
            WalletRelation(
                wallet_a=creator,
                wallet_b=wallet,
                evidence_level=level,
                reasons=reasons,
                shared_launches=n,
                details=details,
            )
        )

    # Pairwise co-buyers
    for (a, b), mints in pair_mints.items():
        shared = len(mints)
        if shared < min_shared_launches:
            continue
        reasons = [f"Co-bought {shared} of the same launches within early window"]
        level = "weak"
        details = {"shared_mints_sample": list(mints)[:5]}
        tkey = tuple(sorted([a, b]))
        tlist = transfer_pairs.get(tkey, [])
        if tlist:
            amounts = [t["sol"] for t in tlist if t.get("sol") is not None]
            reasons.append(f"Direct SOL transfer relationship observed ({len(tlist)} txs)")
            if amounts:
                reasons.append(
                    f"Transfer amounts seen: n={len(amounts)}, median={sorted(amounts)[len(amounts)//2]:.4f}"
                )
            level = "strong" if len(tlist) >= 2 else "moderate"
            details["transfers"] = len(tlist)
        elif shared >= 4:
            level = "moderate"
        relations.append(
            WalletRelation(
                wallet_a=a,
                wallet_b=b,
                evidence_level=level,
                reasons=reasons,
                shared_launches=shared,
                details=details,
            )
        )

    # Rank: strong first, then shared launches
    rank = {"strong": 0, "moderate": 1, "weak": 2}
    relations.sort(key=lambda r: (rank.get(r.evidence_level, 9), -r.shared_launches))
    return relations


def relationships_dataframe(relations: list[WalletRelation]) -> pd.DataFrame:
    rows = []
    for r in relations:
        rows.append(
            {
                "wallet_a": r.wallet_a,
                "wallet_b": r.wallet_b,
                "evidence_level": r.evidence_level,
                "shared_launches": r.shared_launches,
                "reasons": " | ".join(r.reasons),
            }
        )
    return pd.DataFrame(rows)


def graph_edges(relations: list[WalletRelation], max_edges: int = 80) -> pd.DataFrame:
    """Edge list for Plotly/network visualization."""
    df = relationships_dataframe(relations)
    if df.empty:
        return df
    return df.head(max_edges)
