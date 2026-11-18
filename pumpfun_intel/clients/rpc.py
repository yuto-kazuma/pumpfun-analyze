"""Solana JSON-RPC client (typically Helius-backed)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from pumpfun_intel.clients.rate_limit import (
    RateLimitError,
    TokenBucket,
    TransientAPIError,
    with_retries,
)

logger = logging.getLogger(__name__)


class SolanaRpcClient:
    def __init__(self, rpc_url: str, rps: float = 8.0, timeout: float = 60.0) -> None:
        self.rpc_url = rpc_url
        self.timeout = timeout
        self.bucket = TokenBucket(rps)
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=32,
            pool_maxsize=32,
            max_retries=0,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }

        def _do() -> Any:
            self.bucket.acquire()
            try:
                resp = self.session.post(self.rpc_url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                raise TransientAPIError(str(exc)) from exc

            if resp.status_code == 429:
                raise RateLimitError(f"RPC 429 for {method}")
            if resp.status_code >= 500:
                raise TransientAPIError(f"RPC {resp.status_code} for {method}")
            if resp.status_code >= 400:
                raise RuntimeError(f"RPC HTTP {resp.status_code}: {resp.text[:300]}")

            body = resp.json()
            if "error" in body and body["error"]:
                err = body["error"]
                code = err.get("code")
                # Treat overloaded / rate-ish codes as retryable when present
                if code in (-32005, -32007, -32429):
                    raise RateLimitError(str(err))
                raise RuntimeError(f"RPC error for {method}: {err}")
            return body.get("result")

        return with_retries(_do)

    def get_signatures_for_address(
        self,
        address: str,
        *,
        before: str | None = None,
        until: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        opts: dict[str, Any] = {"limit": min(max(limit, 1), 1000)}
        if before:
            opts["before"] = before
        if until:
            opts["until"] = until
        result = self.call("getSignaturesForAddress", [address, opts])
        return list(result or [])

    def get_transaction(self, signature: str) -> dict[str, Any] | None:
        return self.call(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "commitment": "confirmed",
                    # Support legacy + versioned txs (v0 ALTs and newer).
                    "maxSupportedTransactionVersion": 1,
                },
            ],
        )

    def get_account_info(self, pubkey: str, encoding: str = "base64") -> dict[str, Any] | None:
        return self.call(
            "getAccountInfo",
            [pubkey, {"encoding": encoding, "commitment": "confirmed"}],
        )

    def get_asset(self, mint: str) -> dict[str, Any] | None:
        """DAS getAsset via the same RPC endpoint when Helius-backed."""
        try:
            return self.call("getAsset", [{"id": mint}])
        except Exception as exc:  # noqa: BLE001 — enrichment path
            logger.warning("getAsset failed for %s: %s", mint, exc)
            return None
