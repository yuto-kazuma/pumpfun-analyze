# PumpFun Launch Intelligence

Research and analytics toolkit for studying historical on-chain Pump.fun launch behavior of a target Solana wallet.

**This project does not trade, sign transactions, or execute buys/sells.**

Target wallet (default): `DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri`

## Status

Phases 1-8 implemented (research/analytics only):

1. Resumable historical collector
2. Instruction-verified launch analyzer
3. Wallet relationship analysis (evidence levels)
4. Launch pattern metrics
5. Coverage-aware performance windows
6. Pattern discovery (no causation claims)
7. Streamlit dashboard
8. Downloadable final Markdown/CSV report pack

## Requirements

- Python 3.11+
- Helius API key

## Setup

```bash
# Prefer Python 3.11+ (on Windows: py -3.13)
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .

copy .env.example .env
# Edit .env and set HELIUS_API_KEY
```

## Usage

```bash
# Collect last 30 days of wallet history (default)
python -m pumpfun_intel.cli collect --days 30

# Collect for a specific wallet / longer window
python -m pumpfun_intel.cli collect --wallet DWHEZ8JnfGtud25Gjhn3MndpTMshNEd12WMu2ciCa7ri --days 90

# Full available history (no time cutoff)
python -m pumpfun_intel.cli collect --days 0

# Small smoke collect (first N signatures only)
python -m pumpfun_intel.cli collect --days 30 --max-signatures 50

# Decode stored txs and build launch tables
python -m pumpfun_intel.cli analyze

# Show collection / launch coverage
python -m pumpfun_intel.cli status
# or: python -m pumpfun_intel.cli status --json

# Pattern report + mint-scoped early-buyer probe
python -m pumpfun_intel.cli report --probe-limit 12 --early-window 45

# Final report pack (Markdown + CSVs)
python -m pumpfun_intel.cli report --skip-probe --final
```

## Dashboard

```bash
.\.venv\Scripts\activate
streamlit run pumpfun_intel/dashboard/app.py
```

Views: overview, launch history, launch detail, relationships graph, funding, initial buys, timelines, performance windows, pattern discovery, coverage, export.


Collection is **resumable**: re-running `collect` skips signatures already stored with `status=ok`.

### First live run checklist

1. Copy `.env.example` → `.env` and set `HELIUS_API_KEY`
2. `python -m pumpfun_intel.cli collect --days 30`
3. `python -m pumpfun_intel.cli analyze`
4. `python -m pumpfun_intel.cli status` (expect `token_launches` > 0 if the wallet created tokens in-window)

## Classification rules

Transactions are classified by:

1. Program ID (`Pump.fun` / `PumpSwap`)
2. Anchor instruction discriminators (`create`, `create_v2`, `buy`, `sell`, `migrate`, …)

Log text is never used as the sole classifier. Missing transactions are recorded in coverage metadata, never fabricated.

## Tests

```bash
pytest -q
```

## Data layout

- `data/pumpfun_intel.db`: SQLite (raw txs + derived launch tables)
- `data/cache/`: optional on-disk API batch cache

## Disclaimer

Analytics only. Relationship and pattern modules (later phases) assign evidence levels and do not assert shared control of wallets.
