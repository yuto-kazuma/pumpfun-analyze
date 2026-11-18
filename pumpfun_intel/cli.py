"""CLI entrypoint for collect / analyze / status."""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from pumpfun_intel.analyzer.launches import analyze_launches
from pumpfun_intel.analyzer.patterns import write_pattern_report
from pumpfun_intel.clients.rpc import SolanaRpcClient
from pumpfun_intel.collector.mint_activity import probe_recent_launches
from pumpfun_intel.collector.pipeline import collect_wallet_history
from pumpfun_intel.config import PROJECT_ROOT, load_settings, setup_logging
from pumpfun_intel.constants import DEFAULT_TARGET_WALLET
from pumpfun_intel.db.connection import Database
from pumpfun_intel.reporting.final_report import generate_final_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pumpfun-intel",
        description="PumpFun Launch Intelligence: research/analytics only (no trading).",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override LOG_LEVEL (DEBUG, INFO, WARNING, ERROR)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="Collect historical wallet transactions")
    collect.add_argument("--wallet", default=None, help="Target wallet address")
    collect.add_argument(
        "--days",
        type=int,
        default=30,
        help="Lookback days (0 = full history). Default: 30",
    )
    collect.add_argument(
        "--max-signatures",
        type=int,
        default=None,
        help="Optional cap on signatures to collect",
    )
    collect.add_argument(
        "--no-enhanced",
        action="store_true",
        help="Skip Helius Enhanced Transactions enrichment",
    )
    collect.add_argument(
        "--resume-run",
        type=int,
        default=None,
        help="Resume an existing collection_runs id",
    )

    analyze = sub.add_parser("analyze", help="Decode txs and build launch tables")
    analyze.add_argument("--wallet", default=None, help="Target wallet address")
    analyze.add_argument(
        "--early-window",
        type=int,
        default=60,
        help="Early buyer window in seconds (default 60)",
    )
    analyze.add_argument(
        "--no-das",
        action="store_true",
        help="Skip DAS getAsset metadata enrichment",
    )

    status = sub.add_parser("status", help="Show collection and launch coverage")
    status.add_argument("--wallet", default=None, help="Target wallet address")
    status.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    report = sub.add_parser(
        "report",
        help="Mint-probe recent launches and write Markdown/CSV pattern report",
    )
    report.add_argument(
        "--probe-limit",
        type=int,
        default=40,
        help="How many recent launches to mint-probe (default 40)",
    )
    report.add_argument(
        "--early-window",
        type=int,
        default=30,
        help="Early buyer window seconds for mint probe (default 30)",
    )
    report.add_argument(
        "--skip-probe",
        action="store_true",
        help="Only write report from existing DB (no mint RPC probes)",
    )
    report.add_argument(
        "--out-dir",
        default="data/reports",
        help="Report output directory",
    )
    report.add_argument(
        "--final",
        action="store_true",
        help="Also generate Phase-8 final Markdown/CSV report pack",
    )

    return parser


def cmd_collect(args: argparse.Namespace) -> int:
    settings = load_settings()
    setup_logging(args.log_level or settings.log_level)
    lookback = None if args.days == 0 else args.days
    result = collect_wallet_history(
        settings,
        wallet=args.wallet,
        lookback_days=lookback,
        max_signatures=args.max_signatures,
        fetch_enhanced=not args.no_enhanced,
        resume_run_id=args.resume_run,
    )
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "wallet": result.wallet,
                "signatures_collected": result.signatures_collected,
                "txs_ok": result.txs_ok,
                "txs_failed": result.txs_failed,
                "enhanced_stored": result.enhanced_stored,
            },
            indent=2,
        )
    )
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    settings = load_settings()
    setup_logging(args.log_level or settings.log_level)
    result = analyze_launches(
        settings,
        wallet=args.wallet,
        early_window_seconds=args.early_window,
        enrich_das=not args.no_das,
    )
    print(
        json.dumps(
            {
                "wallet": result.wallet,
                "txs_decoded": result.txs_decoded,
                "events": result.events,
                "launches": result.launches,
                "participants": result.participants,
            },
            indent=2,
        )
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = load_settings()
    setup_logging(args.log_level or settings.log_level)
    wallet = args.wallet or settings.target_wallet or DEFAULT_TARGET_WALLET
    db = Database(settings.database_path)
    try:
        sigs = db.fetchone(
            "SELECT COUNT(*) AS c FROM signatures WHERE wallet = ?",
            (wallet,),
        )
        raw_ok = db.fetchone(
            """
            SELECT COUNT(*) AS c FROM raw_transactions r
            JOIN signatures s ON s.signature = r.signature
            WHERE s.wallet = ? AND r.status = 'ok'
            """,
            (wallet,),
        )
        raw_fail = db.fetchone(
            """
            SELECT COUNT(*) AS c FROM raw_transactions r
            JOIN signatures s ON s.signature = r.signature
            WHERE s.wallet = ? AND r.status IN ('failed', 'missing')
            """,
            (wallet,),
        )
        launches = db.fetchone("SELECT COUNT(*) AS c FROM token_launches")
        events = db.fetchone("SELECT COUNT(*) AS c FROM classified_events")
        coverage = db.fetchall(
            "SELECT metric, value FROM coverage_meta WHERE scope = 'wallet' AND scope_key = ?",
            (wallet,),
        )
        recent = db.fetchall(
            """
            SELECT mint, symbol, create_time, create_signature, initial_buy_sol, migrated
            FROM token_launches
            ORDER BY create_time DESC
            LIMIT 10
            """
        )
        runs = db.fetchall(
            """
            SELECT id, status, lookback_days, signatures_collected, txs_fetched,
                   txs_failed, started_at, finished_at
            FROM collection_runs
            WHERE wallet = ?
            ORDER BY id DESC
            LIMIT 5
            """,
            (wallet,),
        )
        payload = {
            "wallet": wallet,
            "signatures": sigs["c"] if sigs else 0,
            "raw_ok": raw_ok["c"] if raw_ok else 0,
            "raw_failed_or_missing": raw_fail["c"] if raw_fail else 0,
            "classified_events": events["c"] if events else 0,
            "token_launches": launches["c"] if launches else 0,
            "coverage": {r["metric"]: r["value"] for r in coverage},
            "recent_launches": [dict(r) for r in recent],
            "recent_runs": [dict(r) for r in runs],
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Wallet: {wallet}")
            print(f"Signatures: {payload['signatures']}")
            print(f"Raw txs OK: {payload['raw_ok']}")
            print(f"Raw txs failed/missing: {payload['raw_failed_or_missing']}")
            print(f"Classified events: {payload['classified_events']}")
            print(f"Token launches: {payload['token_launches']}")
            if payload["coverage"]:
                print("Coverage:")
                for k, v in payload["coverage"].items():
                    print(f"  {k}: {v}")
            if payload["recent_launches"]:
                print("Recent launches:")
                for row in payload["recent_launches"]:
                    print(
                        f"  {row.get('symbol') or '?'} {row['mint'][:8]}… "
                        f"sig={row['create_signature'][:8]}… "
                        f"sol={row.get('initial_buy_sol')} migrated={row.get('migrated')}"
                    )
        return 0
    finally:
        db.close()


def cmd_report(args: argparse.Namespace) -> int:
    settings = load_settings()
    setup_logging(args.log_level or settings.log_level)
    db = Database(settings.database_path)
    probe_payload: list[dict] = []
    try:
        if not args.skip_probe:
            rpc = SolanaRpcClient(settings.rpc_url, rps=max(settings.rpc_rps, 15.0))
            results = probe_recent_launches(
                db,
                rpc,
                limit=args.probe_limit,
                early_window_seconds=args.early_window,
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
            print(
                json.dumps(
                    {
                        "probed": len(probe_payload),
                        "avg_early_buyers": (
                            sum(len(p["early_buyers"]) for p in probe_payload)
                            / max(len(probe_payload), 1)
                        ),
                    },
                    indent=2,
                )
            )

        out_dir = Path(args.out_dir)
        if not out_dir.is_absolute():
            out_dir = PROJECT_ROOT / out_dir
        md_path, csv_path = write_pattern_report(
            db,
            out_dir,
            mint_probe_results=probe_payload or None,
        )
        payload = {"markdown": str(md_path), "csv": str(csv_path)}
        if args.final:
            finals = generate_final_report(db, out_dir)
            payload["final"] = {k: str(v) for k, v in finals.items()}
        print(json.dumps(payload, indent=2))
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "collect":
        return cmd_collect(args)
    if args.command == "analyze":
        return cmd_analyze(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "report":
        return cmd_report(args)
    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
