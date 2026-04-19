"""Claude-powered chat over the live board.

Single private endpoint (``/api/chat``) gated by the existing
owner-only auth.  The endpoint streams Server-Sent Events so the
drawer UI can render tokens as they arrive.

Architecture
------------

Every request bundles three inputs into the ``messages.stream`` call:

1. A static **role + methodology** system block — stable across
   conversations, cached with a 1-hour TTL.
2. A **board snapshot** system block — a deterministic text dump of
   every ranked player on today's board, rebuilt from the live
   contract on every request.  Identical bytes when the underlying
   data hasn't changed, so Anthropic's prompt cache treats it as the
   same prefix and the ~35-50K tokens read at 0.1x price.
3. The caller's full conversation history (``messages[]``).

When the scrape pipeline updates ``latest_data``, the snapshot bytes
change → cache miss → new write at 1.25x — exactly once per refresh
cycle.  Subsequent chat turns within the same cycle hit cache.

Cost shape at Opus 4.7 pricing (April 2026 baseline):
  * first turn after a scrape refresh: ~$0.35-$0.50 (cache write)
  * each follow-up turn: ~$0.03-$0.05 (cache read + output)
  * budget ~$5-15/month for private use
"""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator


# ── Model + client configuration ──────────────────────────────────

# The Anthropic skill mandates ``claude-opus-4-7`` as the default for
# new code.  Q&A over structured data doesn't strictly need Opus
# firepower, but this is a private tool so the per-turn cost
# difference vs Sonnet is trivial.
_MODEL_ID = "claude-opus-4-7"

# High effort is the sweet spot for intelligence-sensitive work on
# Opus 4.7 (per the Anthropic skill); adaptive thinking lets Claude
# dynamically decide how deeply to reason per turn.
_EFFORT = "high"

# Streaming max — 64K keeps responses comfortably inside SDK HTTP
# timeouts without downshifting to Sonnet.
_MAX_TOKENS = 64000

# Per-message content length cap — anti-abuse, not a hard Claude
# limit.  10K chars ≈ 2.5K tokens per user turn is plenty.
_USER_MESSAGE_CHAR_CAP = 10_000


# ── System prompt (stable — cache once per session) ───────────────

_SYSTEM_PROMPT = """\
You are Jason's dynasty fantasy football research assistant for his league "Risk It \
To Get The Brisket" (Sleeper ID 995704) — a TE-premium, IDP-heavy superflex league.

A deterministic snapshot of his current board follows this prompt.  Every row \
includes:
  • rank: overall canonical rank (1 = best)
  • value: blended value on 0-9999 scale
  • conf: confidence bucket (high / medium / low) — agreement across sources
  • src: count of sources ranking this player
  • spread: percentile spread of per-source ranks (0 = tight, 1 = wildly different)
  • flags: anomaly flags (empty = clean)
  • tier: canonical tier id (1 = top tier)
  • sourceRanks: per-source rank in ``src:rank,src:rank`` form

Source key shortforms:
  ktc = KeepTradeCut          idptc = IDPTradeCalc (cross-scope)
  dlf = DLF SuperFlex         dlfIdp = DLF IDP
  nerds = Dynasty Nerds SF    dd = Dynasty Daddy SF
  fp = FantasyPros SF         fpIdp = FantasyPros IDP
  flock = Flock Fantasy       fbg = FootballGuys SF       fbgIdp = FootballGuys IDP
  yb = Yahoo / Justin Boone   ds = DraftSharks SF         dsIdp = DraftSharks IDP
  dlfRookSf / dlfRookIdp = DLF rookie-only boards

Methodology cheat-sheet (use when explaining 'why'):
  • Canonical rank = weighted blend of per-source ranks via Hill curve +
    robust-median (60/40 split), then position-family Hill curve (offense
    midpoint 48.4, IDP midpoint 69.5 for a flatter top).
  • Volatility adjustment rewards high-agreement players with a small boost;
    rank 1 caps at 9999, rank 2 at 9998, etc. so the top is strictly monotonic.
  • Confidence = ''high'' at ≤8% percentile spread, ''medium'' at ≤20%, ''low''
    otherwise.  IDP sources have smaller pools so percentile is the fair signal,
    not absolute ordinal spread.
  • Rookies flagged separately; IDP rookies lack a market price, so single-
    source rookie rows aren't penalized as failures.

Answer concisely.  Cite ranks and values directly when comparing players.
When Jason asks 'why X is ranked Y', trace back to per-source ranks, confidence,
and anomaly flags — don't speculate beyond the data.  When the data doesn't
support the answer, say so.\
"""


# Source-key → shortform used in the snapshot table.  Keep this
# aligned with the registry in ``src/api/data_contract.py`` —
# unknown keys fall through to their raw name.
_SOURCE_SHORT: dict[str, str] = {
    "ktc": "ktc",
    "idpTradeCalc": "idptc",
    "dlfSf": "dlf",
    "dlfIdp": "dlfIdp",
    "dynastyNerdsSfTep": "nerds",
    "dynastyDaddySf": "dd",
    "fantasyProsSf": "fp",
    "fantasyProsIdp": "fpIdp",
    "flockFantasySf": "flock",
    "footballGuysSf": "fbg",
    "footballGuysIdp": "fbgIdp",
    "yahooBoone": "yb",
    "draftSharks": "ds",
    "draftSharksIdp": "dsIdp",
    "dlfRookieSf": "dlfRookSf",
    "dlfRookieIdp": "dlfRookIdp",
}


def build_data_snapshot(contract_or_raw: Any) -> str:
    """Return a deterministic text snapshot of the board for Claude.

    The deterministic guarantee is load-bearing for prompt caching:
    if this string varies between calls while the underlying data
    hasn't changed, the ~50K-token prefix invalidates and every turn
    pays the 1.25x cache-write cost instead of the 0.1x read cost.
    Rows are sorted by ``(rank ASC, name ASC)`` and source keys are
    sorted alphabetically inside each row to keep the bytes stable
    across Python dict iteration.
    """
    if not isinstance(contract_or_raw, dict):
        return "[No board data available — scrape pipeline has not run yet.]\n"

    players = contract_or_raw.get("players")
    if not isinstance(players, dict) or not players:
        return "[Board has no player entries.]\n"

    generated_at = (
        contract_or_raw.get("generatedAt")
        or contract_or_raw.get("scrapeTimestamp")
        or ""
    )

    lines: list[str] = []
    lines.append(f"=== DYNASTY BOARD SNAPSHOT (generated {generated_at}) ===")
    lines.append(f"Total players: {len(players)}")
    lines.append("")
    lines.append("# Format: name|pos|team|yrs|rank|value|conf|src|spread|flags|tier|sourceRanks")

    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for name, row in players.items():
        if not isinstance(row, dict):
            continue
        rank_raw = row.get("_canonicalConsensusRank")
        if rank_raw is None:
            continue
        try:
            rank_int = int(rank_raw)
        except (TypeError, ValueError):
            continue
        ranked.append((rank_int, str(name), row))

    # Rank asc, then name asc — name is the stable tiebreak so bytes
    # don't drift on equal ranks.
    ranked.sort(key=lambda triple: (triple[0], triple[1].lower()))

    for rank, name, row in ranked:
        pos = str(row.get("position") or "?")
        team = str(row.get("team") or "")
        yrs_exp = row.get("_yearsExp")
        yrs_str = str(yrs_exp) if isinstance(yrs_exp, int) else ""
        value = row.get("rankDerivedValue")
        value_str = str(int(value)) if isinstance(value, (int, float)) else ""
        conf = str(row.get("confidenceBucket") or "none")
        src_count = row.get("sourceCount")
        src_count_str = str(int(src_count)) if isinstance(src_count, int) else ""
        pspread = row.get("sourceRankPercentileSpread")
        pspread_str = (
            f"{float(pspread):.3f}" if isinstance(pspread, (int, float)) else ""
        )
        flags_raw = row.get("anomalyFlags") or []
        flags = ",".join(sorted(str(f) for f in flags_raw)) if isinstance(flags_raw, list) else ""
        tier = row.get("canonicalTierId")
        tier_str = str(int(tier)) if isinstance(tier, int) else ""

        src_ranks_raw = row.get("sourceRanks") or {}
        src_pairs: list[str] = []
        if isinstance(src_ranks_raw, dict):
            for key in sorted(src_ranks_raw.keys()):
                short = _SOURCE_SHORT.get(str(key), str(key))
                src_pairs.append(f"{short}:{src_ranks_raw[key]}")
        src_str = ",".join(src_pairs)

        lines.append(
            f"{name}|{pos}|{team}|{yrs_str}|{rank}|{value_str}|{conf}|{src_count_str}"
            f"|{pspread_str}|{flags}|{tier_str}|{src_str}"
        )

    # Trailing newline so concatenation with subsequent blocks is clean.
    return "\n".join(lines) + "\n"


# ── Client factory ────────────────────────────────────────────────


_client_cache: dict[str, Any] = {"client": None, "checked": False}


def _get_client(anthropic_module: Any) -> Any:
    """Return a cached ``AsyncAnthropic`` client, or None if the SDK
    is missing or no API key is set.  Lazy-initialized so a server
    starting without the key still boots — the /api/chat endpoint
    just returns 503 until the key is configured."""
    if _client_cache["checked"]:
        return _client_cache["client"]
    _client_cache["checked"] = True
    if anthropic_module is None:
        return None
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    _client_cache["client"] = anthropic_module.AsyncAnthropic(api_key=api_key)
    return _client_cache["client"]


def reset_client_cache() -> None:
    """Force re-initialization on the next request — useful for
    tests, and for picking up a rotated API key without restarting
    the server."""
    _client_cache["client"] = None
    _client_cache["checked"] = False


# ── Input validation ──────────────────────────────────────────────


_VALID_ROLES = frozenset({"user", "assistant"})


def validate_messages(raw: Any) -> tuple[list[dict[str, str]] | None, str | None]:
    """Return (sanitized_messages, error) — exactly one is non-None.

    The canonical shape is a list of ``{role, content}`` dicts with
    ``role in {"user", "assistant"}`` and ``content`` a non-empty
    string.  The last message must be from the user (Claude needs
    something to respond to).  Assistant messages without content
    and user messages longer than ``_USER_MESSAGE_CHAR_CAP`` are
    dropped / truncated respectively.
    """
    if not isinstance(raw, list) or not raw:
        return None, "messages[] required and must be a non-empty list"

    sanitized: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role not in _VALID_ROLES:
            continue
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        sanitized.append(
            {
                "role": role,
                "content": text[:_USER_MESSAGE_CHAR_CAP],
            }
        )

    if not sanitized:
        return None, "no valid messages after sanitization"
    if sanitized[-1]["role"] != "user":
        return None, "last message must be from role=user"

    return sanitized, None


# ── Streaming glue ────────────────────────────────────────────────


def _sse_event(payload: dict[str, Any]) -> str:
    """Format a Server-Sent Event line.  Separator is two newlines
    per the SSE spec; the leading ``data: `` prefix is mandatory."""
    return f"data: {json.dumps(payload)}\n\n"


async def stream_chat_response(
    *,
    client: Any,
    messages: list[dict[str, str]],
    data_snapshot: str,
) -> AsyncIterator[str]:
    """Async generator that yields SSE payload strings.

    Emits:
      * ``{"type": "text", "text": <delta>}`` for each text chunk
      * ``{"type": "usage", ...}`` once the stream finishes — useful
        for the UI to show cache-hit vs cache-write so we can tell
        whether the board is caching properly
      * ``{"type": "done"}`` as the terminator
      * ``{"type": "error", "error": <msg>}`` on any failure,
        immediately followed by ``{"type": "done"}`` so the client
        can tear down cleanly.
    """
    # The board snapshot carries the ``cache_control`` marker: its
    # breakpoint caches the preceding system-prompt block as well,
    # so both the stable role prompt and the deterministic data dump
    # read from cache on warm turns.
    system_blocks = [
        {"type": "text", "text": _SYSTEM_PROMPT},
        {
            "type": "text",
            "text": data_snapshot,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        },
    ]

    try:
        async with client.messages.stream(
            model=_MODEL_ID,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": _EFFORT},
            system=system_blocks,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield _sse_event({"type": "text", "text": text})

            final = await stream.get_final_message()
            usage = final.usage
            yield _sse_event(
                {
                    "type": "usage",
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
                    "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0,
                }
            )
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        yield _sse_event({"type": "error", "error": f"{type(exc).__name__}: {exc}"})

    yield _sse_event({"type": "done"})
