"""Unit tests for relationship + launch metrics helpers."""

from __future__ import annotations

from pathlib import Path

from pumpfun_intel.analyzer.launch_metrics import compute_launch_metrics
from pumpfun_intel.analyzer.relationships import build_relationships
from pumpfun_intel.db.connection import Database
from pumpfun_intel.db.models import utc_now_iso


def test_relationships_and_metrics_on_synthetic_db(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.db")
    db.execute(
        """
        INSERT INTO token_launches (
            mint, name, symbol, creator, create_ix_type, create_signature,
            create_slot, create_time, initial_buy_sol, initial_buyer_count,
            early_buyer_count, subsequent_buy_count, sell_count, migrated,
            pumpswap_touched, analyzed_at
        ) VALUES
        ('mintA','A','A','CREATOR','create_v2','sigA',1,1000,3.0,1,2,0,0,0,0,?),
        ('mintB','B','B','CREATOR','create_v2','sigB',2,2000,3.0,1,2,0,0,0,0,?)
        """,
        (utc_now_iso(), utc_now_iso()),
    )
    db.execute(
        """
        INSERT INTO launch_participants (mint, wallet, role, first_buy_time, sol_spent)
        VALUES
        ('mintA','W1','early_buyer',1001,1.0),
        ('mintA','W2','early_buyer',1002,1.0),
        ('mintB','W1','early_buyer',2001,1.0),
        ('mintB','W2','early_buyer',2002,1.0)
        """
    )
    for sig, slot, bt in [
        ("sigA", 1, 1000),
        ("sigA2", 1, 1001),
        ("sigB", 2, 2000),
        ("sigB2", 2, 2001),
    ]:
        db.execute(
            """
            INSERT INTO signatures (signature, wallet, slot, block_time, fetched_at)
            VALUES (?, 'CREATOR', ?, ?, ?)
            """,
            (sig, slot, bt, utc_now_iso()),
        )
    db.execute(
        """
        INSERT INTO classified_events (
            signature, slot, block_time, event_type, mint, wallet, sol_amount,
            token_amount, program_id, details_json, evidence_level
        ) VALUES
        ('sigA',1,1000,'create','mintA','CREATOR',NULL,NULL,'pump','{}','instruction'),
        ('sigA2',1,1001,'buy','mintA','W1',1.0,100,'pump','{}','instruction'),
        ('sigB',2,2000,'create','mintB','CREATOR',NULL,NULL,'pump','{}','instruction'),
        ('sigB2',2,2001,'buy','mintB','W1',1.0,100,'pump','{}','instruction')
        """
    )
    rels = build_relationships(db, creator="CREATOR", min_shared_launches=2)
    assert any(r.wallet_b == "W1" for r in rels)
    metrics = compute_launch_metrics(db)
    assert len(metrics) == 2
    assert "first_buy_delay_s" in metrics.columns
    db.close()
