PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet TEXT NOT NULL,
    lookback_days INTEGER,
    status TEXT NOT NULL DEFAULT 'running',
    checkpoint_before TEXT,
    signatures_collected INTEGER NOT NULL DEFAULT 0,
    txs_fetched INTEGER NOT NULL DEFAULT 0,
    txs_failed INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS signatures (
    signature TEXT PRIMARY KEY,
    wallet TEXT NOT NULL,
    slot INTEGER,
    block_time INTEGER,
    err_json TEXT,
    memo TEXT,
    confirmation_status TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signatures_wallet_time
    ON signatures(wallet, block_time DESC);

CREATE TABLE IF NOT EXISTS raw_transactions (
    signature TEXT PRIMARY KEY,
    slot INTEGER,
    block_time INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    json_blob TEXT,
    fetched_at TEXT,
    FOREIGN KEY (signature) REFERENCES signatures(signature)
);

CREATE TABLE IF NOT EXISTS enhanced_transactions (
    signature TEXT PRIMARY KEY,
    json_blob TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    FOREIGN KEY (signature) REFERENCES signatures(signature)
);

CREATE TABLE IF NOT EXISTS decoded_instructions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signature TEXT NOT NULL,
    ix_index INTEGER NOT NULL,
    inner_index INTEGER,
    is_inner INTEGER NOT NULL DEFAULT 0,
    program_id TEXT NOT NULL,
    discriminator_hex TEXT,
    ix_type TEXT,
    accounts_json TEXT,
    args_json TEXT,
    UNIQUE(signature, ix_index, inner_index),
    FOREIGN KEY (signature) REFERENCES signatures(signature)
);

CREATE INDEX IF NOT EXISTS idx_decoded_ix_type
    ON decoded_instructions(ix_type, program_id);

CREATE TABLE IF NOT EXISTS classified_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signature TEXT NOT NULL,
    slot INTEGER,
    block_time INTEGER,
    event_type TEXT NOT NULL,
    mint TEXT,
    wallet TEXT,
    sol_amount REAL,
    token_amount REAL,
    program_id TEXT,
    details_json TEXT,
    evidence_level TEXT NOT NULL DEFAULT 'instruction',
    UNIQUE(signature, event_type, mint, wallet, program_id),
    FOREIGN KEY (signature) REFERENCES signatures(signature)
);

CREATE INDEX IF NOT EXISTS idx_events_mint_time
    ON classified_events(mint, block_time);

CREATE TABLE IF NOT EXISTS token_launches (
    mint TEXT PRIMARY KEY,
    name TEXT,
    symbol TEXT,
    uri TEXT,
    creator TEXT,
    create_user TEXT,
    create_ix_type TEXT,
    create_signature TEXT NOT NULL,
    create_slot INTEGER,
    create_time INTEGER,
    bonding_curve TEXT,
    initial_buy_sol REAL,
    initial_buyer_count INTEGER,
    early_buyer_count INTEGER,
    subsequent_buy_count INTEGER,
    sell_count INTEGER,
    migrated INTEGER NOT NULL DEFAULT 0,
    migration_signature TEXT,
    pumpswap_touched INTEGER NOT NULL DEFAULT 0,
    metadata_source TEXT,
    coverage_notes TEXT,
    analyzed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS launch_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mint TEXT NOT NULL,
    wallet TEXT NOT NULL,
    role TEXT NOT NULL,
    first_buy_signature TEXT,
    first_buy_time INTEGER,
    sol_spent REAL,
    token_received REAL,
    sell_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    UNIQUE(mint, wallet, role),
    FOREIGN KEY (mint) REFERENCES token_launches(mint)
);

CREATE INDEX IF NOT EXISTS idx_participants_wallet
    ON launch_participants(wallet);

CREATE TABLE IF NOT EXISTS coverage_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    metric TEXT NOT NULL,
    value TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(scope, scope_key, metric)
);
