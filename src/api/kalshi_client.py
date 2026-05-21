"""Kalshi trading API client — RSA-PSS signed REST transport.

Kalshi is a CFTC-regulated event-contracts exchange whose official API
*explicitly permits* automated trading (unlike traditional sportsbooks,
whose terms ban bots).  This module is pure transport: it signs and
issues authenticated REST requests and returns parsed JSON.  All betting
business logic (recommendation blending, market mapping, guardrails)
lives in ``src/betting/`` and ``server.py`` — never here.

Authentication
──────────────
Every request is signed with an RSA private key.  Three headers:

* ``KALSHI-ACCESS-KEY``        — the API key id
* ``KALSHI-ACCESS-TIMESTAMP``  — request time in epoch milliseconds
* ``KALSHI-ACCESS-SIGNATURE``  — base64 RSA-PSS signature of the string
  ``f"{timestamp}{METHOD}{path}"`` where ``path`` is the request path
  WITHOUT the query string (e.g. ``/trade-api/v2/portfolio/orders``).

The signature uses PSS padding, MGF1(SHA-256), salt length == digest
length — the scheme documented at https://docs.kalshi.com.

Environment
───────────
* ``KALSHI_ENV``         — ``"demo"`` (default) or ``"prod"``; selects host
* ``KALSHI_API_KEY_ID``  — the key id
* ``KALSHI_PRIVATE_KEY`` — RSA private key, PEM format.  Literal ``\\n``
  escape sequences are tolerated so the key can live on one ``.env`` line.

Demo and production are DIFFERENT accounts with DIFFERENT keys.  Default
is demo so a missing/typo env can never accidentally trade real money.

Prices
──────
Kalshi's March-2026 fixed-point migration made *response* prices dollar
strings with up to 4 decimals (e.g. ``"0.6500"`` == 65¢).  Order
placement still accepts integer-cent prices (1–99).  Use
``dollars_to_cents`` / ``cents_to_dollars`` to convert at the boundary.
"""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover - optional at import time
    requests = None  # type: ignore[assignment]

# ``cryptography`` can fail to import with a pyo3 PanicException when the
# native backend (_cffi_backend) is unavailable.  pyo3's PanicException
# subclasses BaseException, not Exception, so we must guard with
# BaseException here: a missing/broken crypto backend must never crash
# server startup — it only disables live Kalshi calls until the
# dependency is healthy.
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except BaseException:  # pragma: no cover
    hashes = serialization = padding = rsa = None  # type: ignore[assignment]


DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"
# Kalshi serves sports + most markets from the elections host post-merge.
# Confirm against live docs at integration time if a call 404s.
PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"

_UA = "riskittogetthebrisket-betting/1.0"


class KalshiConfigError(RuntimeError):
    """Raised when credentials/config are missing or malformed."""


class KalshiApiError(RuntimeError):
    """Raised when Kalshi returns a non-2xx response."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Kalshi API {status}: {body[:300]}")


# ── price helpers ────────────────────────────────────────────────────────
def dollars_to_cents(value: Any) -> int | None:
    """Parse a Kalshi dollar-string/number price into integer cents.

    ``"0.6500"`` → 65, ``0.65`` → 65, ``65`` → 65 (already cents).
    Returns ``None`` for unparseable input.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Values in (0, 1] are dollar-fractions; > 1 are already cents.
    cents = round(f * 100) if 0 < f <= 1 else round(f)
    if cents < 0:
        return None
    return int(cents)


def cents_to_dollars(cents: int) -> str:
    """Format integer cents as a Kalshi dollar string (``65`` → ``"0.6500"``)."""
    return f"{int(cents) / 100:.4f}"


def is_demo() -> bool:
    return (os.getenv("KALSHI_ENV") or "demo").strip().lower() != "prod"


# ── client ───────────────────────────────────────────────────────────────
@dataclass
class KalshiClient:
    """Thin signed REST wrapper around the Kalshi v2 trading API."""

    key_id: str
    private_key: Any  # cryptography RSAPrivateKey
    base_url: str
    timeout: int = 20

    # ── construction ──
    @classmethod
    def from_env(cls) -> "KalshiClient":
        if requests is None or rsa is None:
            raise KalshiConfigError(
                "kalshi_client requires 'requests' and 'cryptography' installed"
            )
        key_id = (os.getenv("KALSHI_API_KEY_ID") or "").strip()
        pem = os.getenv("KALSHI_PRIVATE_KEY") or ""
        if not key_id or not pem.strip():
            raise KalshiConfigError("KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY must be set")
        # Allow the PEM to be stored with literal \n on a single .env line.
        pem_bytes = pem.replace("\\n", "\n").encode("utf-8")
        try:
            private_key = serialization.load_pem_private_key(pem_bytes, password=None)
        except Exception as exc:  # noqa: BLE001
            raise KalshiConfigError(f"could not parse KALSHI_PRIVATE_KEY: {exc}") from exc
        base = DEMO_BASE if is_demo() else PROD_BASE
        return cls(key_id=key_id, private_key=private_key, base_url=base)

    # ── signing ──
    def _sign(self, timestamp_ms: str, method: str, path: str) -> str:
        """RSA-PSS sign ``timestamp+METHOD+path`` (path has no query string)."""
        message = f"{timestamp_ms}{method.upper()}{path}".encode("utf-8")
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _headers(self, method: str, path: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": self._sign(ts, method, path),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _UA,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a signed request.  ``path`` is the full v2 path used for signing."""
        # Sign the path WITHOUT query params (Kalshi requirement).
        headers = self._headers(method, path)
        # base_url already ends with /trade-api/v2; path begins with the
        # same prefix for signing, so strip the prefix when building the URL.
        suffix = path
        if path.startswith("/trade-api/v2"):
            suffix = path[len("/trade-api/v2") :]
        url = f"{self.base_url}{suffix}"
        resp = requests.request(
            method.upper(),
            url,
            headers=headers,
            params=params or None,
            json=json_body,
            timeout=self.timeout,
        )
        if resp.status_code >= 300:
            raise KalshiApiError(resp.status_code, resp.text)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    # ── market data ──
    def get_markets(self, **params: Any) -> dict[str, Any]:
        """List markets.  Common filters: ``series_ticker``, ``status='open'``,
        ``limit``, ``cursor``."""
        return self._request("GET", "/trade-api/v2/markets", params=params)

    def get_market(self, ticker: str) -> dict[str, Any]:
        return self._request("GET", f"/trade-api/v2/markets/{ticker}")

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict[str, Any]:
        return self._request(
            "GET", f"/trade-api/v2/markets/{ticker}/orderbook", params={"depth": depth}
        )

    # ── portfolio ──
    def get_balance(self) -> dict[str, Any]:
        return self._request("GET", "/trade-api/v2/portfolio/balance")

    def get_positions(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/trade-api/v2/portfolio/positions", params=params)

    def get_fills(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/trade-api/v2/portfolio/fills", params=params)

    def get_orders(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/trade-api/v2/portfolio/orders", params=params)

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/trade-api/v2/portfolio/orders/{order_id}")

    # ── trading ──
    def place_limit_order(
        self,
        *,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Place a resting limit order.

        ``side``   — ``"yes"`` or ``"no"``
        ``action`` — ``"buy"`` or ``"sell"``
        ``count``  — number of contracts (each settles at $1)
        ``price_cents`` — limit price in integer cents (1–99)

        A resting limit order sits on the book and fills when the market
        reaches the price — which is exactly the "bet when it hits my
        price" behaviour we want.
        """
        side = side.strip().lower()
        action = action.strip().lower()
        if side not in ("yes", "no"):
            raise ValueError("side must be 'yes' or 'no'")
        if action not in ("buy", "sell"):
            raise ValueError("action must be 'buy' or 'sell'")
        body: dict[str, Any] = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": int(count),
            "type": "limit",
        }
        # Kalshi takes the price on the side-specific field, integer cents.
        body["yes_price" if side == "yes" else "no_price"] = int(price_cents)
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._request("POST", "/trade-api/v2/portfolio/orders", json_body=body)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/trade-api/v2/portfolio/orders/{order_id}")
