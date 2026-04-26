"""Weekly IDP scoring-fit digest email.

Walks the live contract for IDP rows with ``idpScoringFitDelta`` set
and produces a digest email of:

* Top fit-positive players (league overvalues consensus → buy-low)
* Top fit-negative players (league undervalues vs market → sell-high)
* Roster-specific summary when a Sleeper team is provided

The aim is to give the user a weekly "what does my league's scoring
say about the market right now?" pulse without them having to open
the app.  Distinct from the daily ``signal_alerts`` flow — that one
fires on per-player signal transitions; this one is a recurring
overview.

Delivery contract matches ``signal_alerts``: a ``delivery(to,
subject, body)`` callable so tests can stub it.  Default delivery
is the existing ``_deliver_email_smtp`` from server.py.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

# Threshold below which a delta is "noise" — players with smaller
# deltas don't make the digest.  Matches the BUY/SELL signal-engine
# threshold so the digest is consistent with the in-app chips.
_DELTA_THRESHOLD = 1500.0

# Limits — we cap each section so the email stays readable.
_TOP_BUY_LIMIT = 6
_TOP_SELL_LIMIT = 6


def _format_delta(d: float) -> str:
    """``+6,492`` / ``-1,234`` / ``0``."""
    if d == 0:
        return "0"
    sign = "+" if d > 0 else ""
    return f"{sign}{int(round(d)):,}"


def _is_idp_row(row: dict[str, Any]) -> bool:
    pos = str(row.get("position") or row.get("pos") or "").upper()
    return pos in {
        "DL", "DT", "DE", "EDGE", "NT",
        "LB", "ILB", "OLB", "MLB",
        "DB", "CB", "S", "FS", "SS",
    }


def build_digest(
    contract: dict[str, Any],
    *,
    user_team_players: list[str] | None = None,
    league_name: str | None = None,
) -> dict[str, Any] | None:
    """Build the digest payload from a canonical contract.

    Returns ``None`` when there's nothing actionable to send (no IDP
    rows have a delta, or all deltas are below the noise threshold).
    Returns a dict with ``{subject, body, html, summary}`` otherwise.

    ``user_team_players`` (optional) is the list of canonical player
    names on the user's roster.  When provided, the digest also
    surfaces a roster-specific summary: how many fit-positive players
    they own, sample of biggest movers, etc.
    """
    arr = contract.get("playersArray") or []
    if not isinstance(arr, list):
        return None

    # Build buy + sell candidate lists.
    #
    # Buys = league-wide IDPs (potential acquisition targets — you
    # want to know about fit-positive players on OTHER rosters or
    # in the FA pool that you might trade for or pick up).
    #
    # Sells = ONLY players on the user's roster (your players to
    # consider dropping or trading).  Surfacing league-wide sells
    # was noise — the user can't act on someone else's roster
    # member, and the rail/lens already shows them on /rankings.
    # The digest's value is "what should I do this week", and
    # selling is something only your-roster players can answer.
    buys: list[dict[str, Any]] = []
    sells: list[dict[str, Any]] = []
    roster_set = {str(n).strip() for n in (user_team_players or [])}
    roster_summary: list[dict[str, Any]] = []

    for row in arr:
        if not isinstance(row, dict) or not _is_idp_row(row):
            continue
        delta = row.get("idpScoringFitDelta")
        if not isinstance(delta, (int, float)):
            continue
        name = str(row.get("displayName") or row.get("canonicalName") or "")
        confidence = row.get("idpScoringFitConfidence")
        is_owned = name in roster_set
        # Filter out synthetic + low-confidence rows from buy/sell
        # lists — those rows are noisy, the user doesn't want
        # weekly spam about a rookie cohort estimate.
        if confidence not in ("high", "medium"):
            # Roster summary still includes the player even at low
            # confidence so the user sees what they actually own.
            if is_owned:
                roster_summary.append({
                    "name": name,
                    "position": row.get("position"),
                    "delta": float(delta),
                    "confidence": confidence,
                    "synthetic": bool(row.get("idpScoringFitSynthetic")),
                })
            continue
        entry = {
            "name": name or "?",
            "position": row.get("position") or "?",
            "delta": float(delta),
            "consensus": int(row.get("rankDerivedValue") or 0),
            "tier": row.get("idpScoringFitTier") or "—",
            "confidence": confidence,
        }
        if is_owned:
            roster_summary.append({**entry, "synthetic": False})
        if delta >= _DELTA_THRESHOLD:
            # Buys are league-wide — but exclude players you already
            # own (no point recommending you "buy-low" on someone
            # already on your roster).
            if not is_owned:
                buys.append(entry)
        elif delta <= -_DELTA_THRESHOLD:
            # Sells are MY-ROSTER ONLY — surfacing other teams'
            # sells is noise (you can't act on them).
            if is_owned:
                sells.append(entry)

    buys.sort(key=lambda e: -e["delta"])
    sells.sort(key=lambda e: e["delta"])

    if not buys and not sells and not roster_summary:
        return None

    # Compose the email.  Plain text + HTML for readable rendering
    # in iCloud + Gmail; recipient address is the caller's choice.
    league_label = f" ({league_name})" if league_name else ""
    subject = (
        f"[Brisket] Weekly Scoring Fit{league_label}: "
        f"{len(buys)} buy{'' if len(buys) == 1 else 's'}, "
        f"{len(sells)} sell{'' if len(sells) == 1 else 's'}"
    )

    text_lines: list[str] = []
    text_lines.append(f"Risk It · Weekly Scoring Fit{league_label}")
    text_lines.append("")
    text_lines.append(
        "Players whose value under YOUR league's stacked scoring rules "
        "diverges most from the consensus market.  Positive delta = "
        "your league pays more for them than market does (buy-low "
        "candidates).  Negative = market overpays vs your league "
        "(sell-high)."
    )
    text_lines.append("")

    if buys:
        text_lines.append(f"BUY-LOW · top {min(_TOP_BUY_LIMIT, len(buys))}")
        text_lines.append("-" * 48)
        for b in buys[:_TOP_BUY_LIMIT]:
            text_lines.append(
                f"  {b['name']:<28} {b['position']:<5}"
                f"  {_format_delta(b['delta'])}"
                f"  ({b['tier']}, {b['confidence']} confidence)"
            )
        text_lines.append("")

    if sells:
        text_lines.append(f"SELL-HIGH FROM YOUR ROSTER · {min(_TOP_SELL_LIMIT, len(sells))}")
        text_lines.append("-" * 48)
        for s in sells[:_TOP_SELL_LIMIT]:
            text_lines.append(
                f"  {s['name']:<28} {s['position']:<5}"
                f"  {_format_delta(s['delta'])}"
                f"  ({s['tier']}, {s['confidence']} confidence)"
            )
        text_lines.append("")

    if roster_summary:
        owned_buys = [r for r in roster_summary if r.get("delta", 0) >= _DELTA_THRESHOLD]
        owned_sells = [r for r in roster_summary if r.get("delta", 0) <= -_DELTA_THRESHOLD]
        net_delta = sum(r.get("delta", 0) for r in roster_summary)
        text_lines.append("YOUR ROSTER")
        text_lines.append("-" * 48)
        text_lines.append(
            f"  IDPs on your roster with deltas: {len(roster_summary)}"
        )
        text_lines.append(
            f"  Net fit-delta: {_format_delta(net_delta)} "
            f"({len(owned_buys)} buy-side, {len(owned_sells)} sell-side)"
        )
        if owned_buys:
            text_lines.append("")
            text_lines.append("  You OWN these fit-positive players (consider keeping):")
            for r in sorted(owned_buys, key=lambda x: -x["delta"])[:5]:
                text_lines.append(
                    f"    • {r['name']} ({r['position']}) {_format_delta(r['delta'])}"
                )
        if owned_sells:
            text_lines.append("")
            text_lines.append("  You OWN these fit-negative players (consider trading):")
            for r in sorted(owned_sells, key=lambda x: x["delta"])[:5]:
                text_lines.append(
                    f"    • {r['name']} ({r['position']}) {_format_delta(r['delta'])}"
                )
        text_lines.append("")

    text_lines.append("")
    text_lines.append("Open the rankings:  https://riskittogetthebrisket.org/rankings")
    text_lines.append("Toggle Apply Scoring Fit on /settings to use these values everywhere.")
    text_lines.append("")
    text_lines.append("— Risk It")

    body = "\n".join(text_lines)

    # Lightweight HTML version for iCloud / Gmail rendering.  Same
    # content; nicer layout.  Inline styles only — no external CSS.
    html_parts: list[str] = []
    html_parts.append("<div style='font-family:system-ui,Helvetica,Arial,sans-serif;color:#1a1d2e;max-width:640px;margin:0 auto;padding:18px;'>")
    html_parts.append(f"<h2 style='color:#22d3ee;margin:0 0 6px;'>Weekly Scoring Fit{league_label}</h2>")
    html_parts.append("<p style='color:#666;font-size:13px;margin:0 0 16px;'>Players whose value under YOUR league's stacked scoring rules diverges most from the consensus market.</p>")

    def _section(title: str, color: str, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        html_parts.append(f"<h3 style='color:{color};margin:18px 0 6px;font-size:14px;'>{title}</h3>")
        html_parts.append("<table style='width:100%;border-collapse:collapse;font-size:13px;'>")
        for it in items:
            d = it["delta"]
            sign_color = "#16a34a" if d > 0 else "#dc2626"
            html_parts.append(
                "<tr>"
                f"<td style='padding:3px 6px;'><strong>{it['name']}</strong></td>"
                f"<td style='padding:3px 6px;color:#666;font-size:12px;'>{it['position']}</td>"
                f"<td style='padding:3px 6px;color:{sign_color};font-family:monospace;font-weight:600;text-align:right;'>{_format_delta(d)}</td>"
                f"<td style='padding:3px 6px;color:#888;font-size:12px;'>{it['tier']}</td>"
                "</tr>"
            )
        html_parts.append("</table>")

    _section("Buy-low candidates (league-wide)", "#16a34a", buys[:_TOP_BUY_LIMIT])
    _section("Sell-high from your roster", "#dc2626", sells[:_TOP_SELL_LIMIT])

    if roster_summary:
        owned_buys = [r for r in roster_summary if r.get("delta", 0) >= _DELTA_THRESHOLD]
        owned_sells = [r for r in roster_summary if r.get("delta", 0) <= -_DELTA_THRESHOLD]
        net_delta = sum(r.get("delta", 0) for r in roster_summary)
        net_color = "#16a34a" if net_delta > 0 else ("#dc2626" if net_delta < 0 else "#666")
        html_parts.append("<div style='margin-top:18px;padding:12px;background:#f8fafc;border-radius:6px;'>")
        html_parts.append("<h3 style='margin:0 0 6px;font-size:14px;'>Your roster</h3>")
        html_parts.append(f"<p style='margin:0;font-size:13px;'>Net fit-delta: <strong style='color:{net_color};font-family:monospace;'>{_format_delta(net_delta)}</strong> across {len(roster_summary)} IDPs ({len(owned_buys)} buy-side, {len(owned_sells)} sell-side)</p>")
        html_parts.append("</div>")

    html_parts.append("<p style='margin-top:20px;font-size:13px;'><a href='https://riskittogetthebrisket.org/rankings' style='color:#22d3ee;'>Open the rankings →</a></p>")
    html_parts.append("<p style='font-size:11px;color:#999;margin-top:14px;'>Toggle Apply Scoring Fit on /settings to use these values across the trade calculator + suggestions.</p>")
    html_parts.append("</div>")

    return {
        "subject": subject,
        "body": body,
        "html": "".join(html_parts),
        "summary": {
            "buy_count": len(buys),
            "sell_count": len(sells),
            "roster_count": len(roster_summary),
        },
    }


def deliver_digest(
    contract: dict[str, Any],
    *,
    to_email: str,
    user_team_players: list[str] | None = None,
    league_name: str | None = None,
    delivery: Callable[[str, str, str], bool] | None = None,
) -> dict[str, Any]:
    """End-to-end: build digest + deliver via ``delivery``.

    ``delivery(to, subject, body) -> bool`` matches the
    ``signal_alerts._deliver_email_smtp`` signature so callers can
    pass either function (or a test stub).

    Returns a summary dict suitable for logging:

        {
          "delivered":    bool,
          "reason":       "ok" | "no_content" | "no_email" | "delivery_error" | "no_delivery",
          "summary":      {buy_count, sell_count, roster_count},
        }
    """
    if not to_email:
        return {"delivered": False, "reason": "no_email"}
    digest = build_digest(
        contract,
        user_team_players=user_team_players,
        league_name=league_name,
    )
    if digest is None:
        return {"delivered": False, "reason": "no_content"}
    if delivery is None:
        return {
            "delivered": False,
            "reason": "no_delivery",
            "summary": digest.get("summary"),
        }
    try:
        ok = delivery(to_email, digest["subject"], digest["body"])
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "scoring_fit_digest delivery failed for %s: %s", to_email, exc,
        )
        return {
            "delivered": False,
            "reason": f"delivery_error:{type(exc).__name__}",
            "summary": digest.get("summary"),
        }
    return {
        "delivered": bool(ok),
        "reason": "ok" if ok else "delivery_error",
        "summary": digest.get("summary"),
    }
