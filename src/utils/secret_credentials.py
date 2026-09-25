"""Keyed-provider credentials and redaction — ONE owner.

Every keyed commercial feed (SportsDataIO, Fantasy Nerds, FantasyPros …)
needs the same three things, and they are defined once here:

* :func:`read_credential` reads one canonical environment variable into a
  :class:`SecretCredential` whose ``repr`` / ``str`` never show the value
  and which refuses to pickle.  A missing or blank variable is ``None`` —
  the source is UNAVAILABLE, which every caller must report as an explicit
  ``credential_missing`` refusal, never as an empty success or zero data.
* :func:`redact` scrubs both the literal secret value and any
  credential-shaped query parameter or header value out of text before it
  leaves a module (log lines, error strings, stored URLs).
* The value itself is reachable only through
  :meth:`SecretCredential.reveal`, at the single place a caller puts it on
  the wire.  Agents never enter or handle credentials; the owner configures
  them through the environment (see ``.env.example``).

Integration note (2026-09-25): ``src/ros/keyed_weekly_projections.py`` on
``claude/weekly-projection-keyed-sources`` carries the identical
``SecretCredential`` / ``read_credential`` / ``redact`` trio.  That branch
and ``claude/game-day-sdio-live-state`` were not yet merged together when
this module was factored out, so on integration the keyed-projections
module must import (and may re-export) these three names from here rather
than keep its own copy — one owner, not two.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["REDACTED", "SecretCredential", "read_credential", "redact"]

REDACTED = "<redacted>"

#: Query-parameter names that carry a credential on any provider we know
#: of (Fantasy Nerds ``apikey``, SportsDataIO ``key``).  Redacted by NAME as
#: well as by value, so a key we were never handed still cannot leak.
_SECRET_PARAM = re.compile(
    r"(?i)([?&](?:apikey|api_key|key|subscription-key|token|access_token)=)[^&#\s'\"]*"
)
_SECRET_HEADER = re.compile(r"(?i)(ocp-apim-subscription-key\s*[:=]\s*)[^\s,'\"}]+")


class SecretCredential:
    """A credential read from the environment.  The value is reachable only
    through :meth:`reveal`; every textual rendering is redacted."""

    __slots__ = ("_value", "env_var")

    def __init__(self, env_var: str, value: str) -> None:
        self.env_var = env_var
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"SecretCredential(env_var={self.env_var!r}, value={REDACTED!r})"

    __str__ = __repr__

    def __reduce__(self):  # never pickle a secret into a cache or a queue
        raise TypeError("SecretCredential is not serializable")


def read_credential(env_var: str, env: Mapping[str, str] | None = None) -> SecretCredential | None:
    """The credential in ``env_var``, or ``None`` when unset/blank.

    ``None`` means the source is UNAVAILABLE — not that it has no data."""
    source = os.environ if env is None else env
    value = str(source.get(env_var) or "").strip()
    return SecretCredential(env_var, value) if value else None


def redact(text: Any, secrets: Iterable[SecretCredential | str | None] = ()) -> str:
    """``text`` with every literal secret value and every credential-shaped
    query parameter / header value replaced by ``<redacted>``."""
    out = str(text)
    for secret in secrets:
        value = secret.reveal() if isinstance(secret, SecretCredential) else secret
        if value:
            out = out.replace(value, REDACTED)
    out = _SECRET_PARAM.sub(lambda m: m.group(1) + REDACTED, out)
    return _SECRET_HEADER.sub(lambda m: m.group(1) + REDACTED, out)
