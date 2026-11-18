"""Load analysis tables for the dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

from pumpfun_intel.analyzer.discovery import discover_patterns
from pumpfun_intel.analyzer.launch_metrics import compute_launch_metrics
from pumpfun_intel.analyzer.performance import compute_performance_windows
from pumpfun_intel.analyzer.relationships import build_relationships, relationships_dataframe
from pumpfun_intel.config import PROJECT_ROOT, load_settings
from pumpfun_intel.constants import DEFAULT_TARGET_WALLET
from pumpfun_intel.db.connection import Database


def db_path() -> Path:
    """Prefer full local DB; fall back to committed cloud analytics DB."""
    candidates: list[Path] = []
    try:
        candidates.append(load_settings().database_path)
    except Exception:
        pass
    candidates.extend(
        [
            PROJECT_ROOT / "data" / "pumpfun_intel.db",
            PROJECT_ROOT / "data" / "cloud_analytics.db",
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return candidates[0] if candidates else PROJECT_ROOT / "data" / "cloud_analytics.db"


def get_db() -> Database:
    return Database(db_path())


def load_launches() -> pd.DataFrame:
    db = get_db()
    try:
        rows = db.fetchall("SELECT * FROM token_launches ORDER BY create_time DESC")
        df = pd.DataFrame([dict(r) for r in rows])
        if not df.empty and "create_time" in df.columns:
            df["create_dt"] = pd.to_datetime(df["create_time"], unit="s", utc=True)
        return df
    finally:
        db.close()


def load_participants() -> pd.DataFrame:
    db = get_db()
    try:
        rows = db.fetchall("SELECT * FROM launch_participants")
        return pd.DataFrame([dict(r) for r in rows])
    finally:
        db.close()


def load_events(mint: str | None = None) -> pd.DataFrame:
    db = get_db()
    try:
        if mint:
            rows = db.fetchall(
                """
                SELECT * FROM classified_events
                WHERE mint = ?
                ORDER BY block_time ASC
                """,
                (mint,),
            )
        else:
            rows = db.fetchall(
                """
                SELECT * FROM classified_events
                ORDER BY block_time DESC
                LIMIT 5000
                """
            )
        df = pd.DataFrame([dict(r) for r in rows])
        if not df.empty and "block_time" in df.columns:
            df["block_dt"] = pd.to_datetime(df["block_time"], unit="s", utc=True)
        return df
    finally:
        db.close()


def load_coverage() -> pd.DataFrame:
    db = get_db()
    try:
        rows = db.fetchall("SELECT * FROM coverage_meta")
        return pd.DataFrame([dict(r) for r in rows])
    finally:
        db.close()


@lru_cache(maxsize=1)
def cached_analysis_bundle() -> dict:
    db = get_db()
    try:
        creator = DEFAULT_TARGET_WALLET
        try:
            creator = load_settings().target_wallet
        except Exception:
            pass
        metrics = compute_launch_metrics(db)
        perf = compute_performance_windows(db)
        relations = build_relationships(db, creator=creator)
        discovery = discover_patterns(db)
        return {
            "creator": creator,
            "metrics": metrics,
            "performance": perf,
            "relations": relations,
            "relations_df": relationships_dataframe(relations),
            "discovery": discovery,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        db.close()


def clear_analysis_cache() -> None:
    cached_analysis_bundle.cache_clear()
