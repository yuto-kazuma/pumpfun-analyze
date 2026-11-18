"""Helius Enhanced Transactions client (enrichment only)."""

from __future__ import annotations

import json
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


class HeliusClient:
    def __init__(
        self,
        api_key: str,
        *,
        rps: float = 5.0,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.bucket = TokenBucket(rps)
        self.session = requests.Session()
        self.enhanced_url = f"https://api.helius.xyz/v0/transactions?api-key={api_key}"

    def get_transactions_batch(self, signatures: list[str]) -> list[dict[str, Any]]:
        if not signatures:
            return []

        def _do() -> list[dict[str, Any]]:
            self.bucket.acquire()
            try:
                resp = self.session.post(
                    self.enhanced_url,
                    data=json.dumps({"transactions": signatures}),
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise TransientAPIError(str(exc)) from exc

            if resp.status_code == 429:
                raise RateLimitError("Helius enhanced 429")
            if resp.status_code >= 500:
                raise TransientAPIError(f"Helius enhanced {resp.status_code}")
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Helius enhanced HTTP {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()
            if not isinstance(data, list):
                logger.warning("Unexpected Helius enhanced response type: %s", type(data))
                return []
            return data

        return with_retries(_do)
