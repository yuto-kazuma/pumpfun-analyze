"""Environment-driven configuration. No hardcoded credentials."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from pumpfun_intel.constants import DEFAULT_TARGET_WALLET

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    helius_api_key: str
    rpc_url: str
    target_wallet: str
    database_path: Path
    cache_dir: Path
    rpc_rps: float
    helius_rps: float
    log_level: str

    @property
    def helius_enhanced_url(self) -> str:
        return f"https://api.helius.xyz/v0/transactions?api-key={self.helius_api_key}"

    @property
    def helius_address_txs_url(self) -> str:
        return (
            "https://api.helius.xyz/v0/addresses/{address}/transactions"
            f"?api-key={self.helius_api_key}"
        )


def _require_helius_key() -> str:
    key = os.getenv("HELIUS_API_KEY", "").strip()
    if not key or key == "your_helius_api_key_here":
        raise RuntimeError(
            "HELIUS_API_KEY is required. Copy .env.example to .env and set your key."
        )
    return key


def load_settings(env_file: Path | None = None) -> Settings:
    """Load settings from environment / optional .env file."""
    dotenv_path = env_file or (PROJECT_ROOT / ".env")
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
    else:
        load_dotenv()

    api_key = _require_helius_key()
    rpc_url = os.getenv("RPC_URL", "").strip()
    if not rpc_url:
        rpc_url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"

    db_raw = os.getenv("DATABASE_PATH", "data/pumpfun_intel.db")
    cache_raw = os.getenv("CACHE_DIR", "data/cache")
    database_path = Path(db_raw)
    cache_dir = Path(cache_raw)
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    if not cache_dir.is_absolute():
        cache_dir = PROJECT_ROOT / cache_dir

    return Settings(
        helius_api_key=api_key,
        rpc_url=rpc_url,
        target_wallet=os.getenv("TARGET_WALLET", DEFAULT_TARGET_WALLET).strip(),
        database_path=database_path,
        cache_dir=cache_dir,
        rpc_rps=float(os.getenv("RPC_RPS", "8")),
        helius_rps=float(os.getenv("HELIUS_RPS", "5")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
