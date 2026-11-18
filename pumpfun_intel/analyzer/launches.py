"""Phase 2: identify Pump.fun token launches and early activity."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pumpfun_intel.analyzer.activity import decode_and_classify_all
from pumpfun_intel.clients.rpc import SolanaRpcClient
from pumpfun_intel.config import Settings
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import set_coverage, utc_now_iso

logger = logging.getLogger(__name__)

EARLY_BUY_WINDOW_SECONDS = 60


@dataclass
class AnalysisResult:
    wallet: str
    txs_decoded: int
    events: int
    launches: int
    participants: int


def _enrich_metadata(rpc: SolanaRpcClient | None, mint: str) -> dict[str, Any]:
    if rpc is None:
        return {}
    asset = rpc.get_asset(mint)
    if not asset:
        return {}
    content = asset.get("content") or {}
    meta = content.get("metadata") or {}
    return {
        "name": meta.get("name"),
        "symbol": meta.get("symbol"),
        "uri": content.get("json_uri") or meta.get("uri"),
        "source": "das_getAsset",
    }


def analyze_launches(
    settings: Settings,
    *,
    wallet: str | None = None,
    early_window_seconds: int = EARLY_BUY_WINDOW_SECONDS,
    enrich_das: bool = True,
) -> AnalysisResult:
    wallet = wallet or settings.target_wallet
    db = Database(settings.database_path)
    rpc = SolanaRpcClient(settings.rpc_url, rps=settings.rpc_rps) if enrich_das else None

    try:
        txs_decoded, events = decode_and_classify_all(db)

        creates = db.fetchall(
            """
            SELECT *
            FROM classified_events
            WHERE event_type = 'create'
            ORDER BY block_time ASC
            """
        )

        # Rebuild launch tables from current events
        db.execute("DELETE FROM launch_participants")
        db.execute("DELETE FROM token_launches")

        launches = 0
        participants = 0
        decode_failures = 0

        for create in creates:
            mint = create["mint"]
            if not mint:
                decode_failures += 1
                continue

            details = create["details_json"]
            args = json.loads(details) if details else {}
            name = args.get("name")
            symbol = args.get("symbol")
            uri = args.get("uri")
            creator = args.get("creator")
            create_user = args.get("user")
            bonding_curve = args.get("bonding_curve")
            create_ix_type = args.get("ix_type") or "create"
            # Prefer stored decoded_instructions type
            ix_row = db.fetchone(
                """
                SELECT ix_type FROM decoded_instructions
                WHERE signature = ? AND ix_type IN ('create', 'create_v2')
                LIMIT 1
                """,
                (create["signature"],),
            )
            if ix_row:
                create_ix_type = ix_row["ix_type"]

            metadata_source = "instruction"
            if (not name or not symbol) and rpc is not None:
                enriched = _enrich_metadata(rpc, mint)
                name = name or enriched.get("name")
                symbol = symbol or enriched.get("symbol")
                uri = uri or enriched.get("uri")
                if enriched:
                    metadata_source = enriched.get("source", "das_getAsset")

            create_time = create["block_time"]
            early_cutoff = (
                int(create_time) + early_window_seconds if create_time is not None else None
            )

            buys = db.fetchall(
                """
                SELECT * FROM classified_events
                WHERE mint = ? AND event_type IN ('buy', 'pumpswap_buy')
                ORDER BY block_time ASC, signature ASC
                """,
                (mint,),
            )
            sells = db.fetchall(
                """
                SELECT * FROM classified_events
                WHERE mint = ? AND event_type IN ('sell', 'pumpswap_sell')
                ORDER BY block_time ASC
                """,
                (mint,),
            )
            migrates = db.fetchall(
                """
                SELECT * FROM classified_events
                WHERE mint = ? AND event_type = 'migrate'
                ORDER BY block_time ASC
                """,
                (mint,),
            )
            pumpswap = db.fetchone(
                """
                SELECT COUNT(*) AS c FROM classified_events
                WHERE mint = ? AND event_type IN ('pumpswap_buy', 'pumpswap_sell', 'pumpswap_touch')
                """,
                (mint,),
            )

            # Initial buy: same signature as create, or first buy after create
            initial_buys = [
                b
                for b in buys
                if b["signature"] == create["signature"]
                or (
                    create_time is not None
                    and b["block_time"] is not None
                    and int(b["block_time"]) >= int(create_time)
                )
            ]
            same_tx_buys = [b for b in buys if b["signature"] == create["signature"]]
            initial_sol = 0.0
            initial_buyers: set[str] = set()
            for b in same_tx_buys or (initial_buys[:1] if initial_buys else []):
                if b["wallet"]:
                    initial_buyers.add(b["wallet"])
                if b["sol_amount"] is not None:
                    initial_sol += float(b["sol_amount"])

            early_buyers: set[str] = set()
            subsequent = 0
            for b in buys:
                if b["wallet"]:
                    if early_cutoff is None or (
                        b["block_time"] is not None and int(b["block_time"]) <= early_cutoff
                    ):
                        early_buyers.add(b["wallet"])
                    elif b["signature"] != create["signature"]:
                        subsequent += 1
                elif b["signature"] != create["signature"]:
                    subsequent += 1

            # Recount subsequent as buys after early window
            subsequent = 0
            for b in buys:
                if b["signature"] == create["signature"]:
                    continue
                if early_cutoff is not None and b["block_time"] is not None:
                    if int(b["block_time"]) <= early_cutoff:
                        continue
                subsequent += 1

            migration_sig = migrates[0]["signature"] if migrates else None
            coverage_notes = []
            if not creator:
                coverage_notes.append("missing_creator")
            if not name:
                coverage_notes.append("missing_name")

            # Only include launches involving target wallet as creator, create user,
            # fee-related participant, or initial buyer — still record all creates seen
            # in the collected set (wallet history may include creates by this wallet).
            involves_target = (
                creator == wallet
                or create_user == wallet
                or wallet in initial_buyers
                or wallet in early_buyers
                or any(b["wallet"] == wallet for b in buys)
                or any(s["wallet"] == wallet for s in sells)
            )
            # Since we collect target wallet history, all creates in this DB that appear
            # in their txs are relevant; keep all creates found in collected txs.
            _ = involves_target

            db.execute(
                """
                INSERT INTO token_launches (
                    mint, name, symbol, uri, creator, create_user, create_ix_type,
                    create_signature, create_slot, create_time, bonding_curve,
                    initial_buy_sol, initial_buyer_count, early_buyer_count,
                    subsequent_buy_count, sell_count, migrated, migration_signature,
                    pumpswap_touched, metadata_source, coverage_notes, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mint) DO UPDATE SET
                    name = excluded.name,
                    symbol = excluded.symbol,
                    uri = excluded.uri,
                    creator = excluded.creator,
                    create_user = excluded.create_user,
                    create_ix_type = excluded.create_ix_type,
                    create_signature = excluded.create_signature,
                    create_slot = excluded.create_slot,
                    create_time = excluded.create_time,
                    bonding_curve = excluded.bonding_curve,
                    initial_buy_sol = excluded.initial_buy_sol,
                    initial_buyer_count = excluded.initial_buyer_count,
                    early_buyer_count = excluded.early_buyer_count,
                    subsequent_buy_count = excluded.subsequent_buy_count,
                    sell_count = excluded.sell_count,
                    migrated = excluded.migrated,
                    migration_signature = excluded.migration_signature,
                    pumpswap_touched = excluded.pumpswap_touched,
                    metadata_source = excluded.metadata_source,
                    coverage_notes = excluded.coverage_notes,
                    analyzed_at = excluded.analyzed_at
                """,
                (
                    mint,
                    name,
                    symbol,
                    uri,
                    creator,
                    create_user,
                    create_ix_type,
                    create["signature"],
                    create["slot"],
                    create_time,
                    bonding_curve,
                    initial_sol if initial_sol > 0 else None,
                    len(initial_buyers),
                    len(early_buyers),
                    subsequent,
                    len(sells),
                    1 if migrates else 0,
                    migration_sig,
                    1 if (pumpswap and pumpswap["c"] > 0) else 0,
                    metadata_source,
                    ",".join(coverage_notes) if coverage_notes else None,
                    utc_now_iso(),
                ),
            )
            launches += 1

            # Participants: creator + early buyers
            if creator:
                db.execute(
                    """
                    INSERT INTO launch_participants (
                        mint, wallet, role, first_buy_signature, first_buy_time,
                        sol_spent, token_received, sell_count, notes
                    ) VALUES (?, ?, 'creator', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(mint, wallet, role) DO UPDATE SET
                        first_buy_signature = excluded.first_buy_signature,
                        first_buy_time = excluded.first_buy_time,
                        sol_spent = excluded.sol_spent,
                        notes = excluded.notes
                    """,
                    (
                        mint,
                        creator,
                        create["signature"],
                        create_time,
                        initial_sol if creator in initial_buyers else None,
                        None,
                        sum(1 for s in sells if s["wallet"] == creator),
                        "declared_creator",
                    ),
                )
                participants += 1

            # Aggregate first buy per wallet
            first_buy_by_wallet: dict[str, Any] = {}
            sol_by_wallet: dict[str, float] = {}
            for b in buys:
                w = b["wallet"]
                if not w:
                    continue
                if w not in first_buy_by_wallet:
                    first_buy_by_wallet[w] = b
                if b["sol_amount"] is not None:
                    sol_by_wallet[w] = sol_by_wallet.get(w, 0.0) + float(b["sol_amount"])

            for w, b in first_buy_by_wallet.items():
                role = "early_buyer"
                if early_cutoff is not None and b["block_time"] is not None:
                    if int(b["block_time"]) > early_cutoff:
                        role = "buyer"
                if b["signature"] == create["signature"]:
                    role = "initial_buyer"
                db.execute(
                    """
                    INSERT INTO launch_participants (
                        mint, wallet, role, first_buy_signature, first_buy_time,
                        sol_spent, token_received, sell_count, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(mint, wallet, role) DO UPDATE SET
                        first_buy_signature = excluded.first_buy_signature,
                        first_buy_time = excluded.first_buy_time,
                        sol_spent = excluded.sol_spent,
                        token_received = excluded.token_received,
                        sell_count = excluded.sell_count
                    """,
                    (
                        mint,
                        w,
                        role,
                        b["signature"],
                        b["block_time"],
                        sol_by_wallet.get(w),
                        float(b["token_amount"]) if b["token_amount"] is not None else None,
                        sum(1 for s in sells if s["wallet"] == w),
                        "instruction_verified_buy",
                    ),
                )
                participants += 1

        set_coverage(db, "wallet", wallet, "launches_found", str(launches))
        set_coverage(db, "wallet", wallet, "events_classified", str(events))
        set_coverage(db, "wallet", wallet, "create_decode_failures", str(decode_failures))
        set_coverage(
            db,
            "wallet",
            wallet,
            "analysis_complete",
            "true",
        )

        logger.info(
            "Analysis complete wallet=%s launches=%d participants=%d",
            wallet,
            launches,
            participants,
        )
        return AnalysisResult(
            wallet=wallet,
            txs_decoded=txs_decoded,
            events=events,
            launches=launches,
            participants=participants,
        )
    finally:
        db.close()
