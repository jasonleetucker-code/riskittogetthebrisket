"""DFS contests: the contract, payout ladders, exact tie payouts, rake/overlay, entry caps.

ONE owner for "what does this contest pay, and under what economics".  It does
not evaluate lineups — that needs an outcome model and a field model
(roadmap P4/P5) — but everything a contest-aware evaluator will need to be
EXACT about lives here and is tested now.

Rules this module holds (owner directive 2026-09-30, docs/dfs/TRACEABILITY.md
DFS-§5-05, §7-03, §17-02):

* **Dimensions stay separate.**  Roster format, entry restriction, guarantee
  status and the payout shape are independent fields; "single-entry GPP" is
  two facts, not one enum member.
* **Money is integer cents.**  No float ever touches a prize; a tie split that
  does not divide evenly is returned exactly (as a fraction of a cent) and
  flagged, because the platform's rounding rule is not verified here.
* **Nothing is invented.**  A ladder the owner did not supply is never filled
  in; a ``hypothetical`` ladder is labelled so and exact-EV stays suppressed.
  An unknown tie rule makes tied payouts unavailable rather than assumed.
* **Rake, overlay and underfill are different states.**  An underfilled
  contest is an overlay only when it is guaranteed AND its prizes exceed the
  fees actually collected.  Otherwise it is either still raked or unknown.
* **An entry cap is a constraint, not a recommendation.**  The hard upper bound
  is ``min(remaining allowance, open capacity, affordable within the owner's
  explicit spend limit)``.  No spend limit → no bound (never inferred).  The
  recommended COUNT is a separate question that needs contest EV and is
  reported unavailable.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

PRIZE_KINDS = ("cash", "ticket", "noncash")
LADDER_SOURCES = ("entered", "imported", "hypothetical")
TIE_RULES = ("split_positions", "unknown")
ENTRY_METHODS = ("cash", "ticket", "free")
MAX_BANDS = 2000
MAX_RANK = 10_000_000


class ContestError(ValueError):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass(frozen=True)
class PayoutBand:
    min_rank: int
    max_rank: int
    prize_cents: int
    kind: str = "cash"
    # Owner-stated cash value of a ticket / noncash prize; None = unknown.
    value_cents: int | None = None

    @property
    def places(self) -> int:
        return self.max_rank - self.min_rank + 1

    def cash_value(self) -> int | None:
        """Cash-equivalent value per place; None when a non-cash prize has no stated value."""
        if self.kind == "cash":
            return self.prize_cents
        return self.value_cents


@dataclass
class Contest:
    name: str
    platform: str
    sport: str
    format: str
    entry_fee_cents: int
    entry_method: str = "cash"
    currency: str = "USD"
    capacity: int | None = None
    current_entries: int | None = None
    guaranteed: bool | None = None
    max_entries_per_user: int | None = None
    existing_user_entries: int | None = None
    tie_rule: str = "unknown"
    ladder_source: str = "entered"
    ladder: list[PayoutBand] = field(default_factory=list)
    platform_contest_id: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ladder"] = [asdict(b) for b in self.ladder]
        return d


# ── parsing ───────────────────────────────────────────────────────────


def dollars_to_cents(raw: Any, name: str) -> int:
    """``"1,000.50"`` / ``1000.5`` / ``"$25"`` → integer cents.  Sub-cent input is refused."""
    if isinstance(raw, bool) or raw is None or raw == "":
        raise ContestError("INVALID_CONTEST", f"{name} is required.")
    try:
        d = Decimal(str(raw).replace("$", "").replace(",", "").strip())
    except InvalidOperation as exc:
        raise ContestError(
            "INVALID_CONTEST", f"{name} must be an amount like 25 or 1,000.50."
        ) from exc
    if not d.is_finite() or d < 0:
        raise ContestError("INVALID_CONTEST", f"{name} must be a non-negative amount.")
    cents = d * 100
    if cents != cents.to_integral_value():
        raise ContestError("INVALID_CONTEST", f"{name} has a fraction of a cent.")
    if cents > Decimal(10) ** 12:
        raise ContestError("INVALID_CONTEST", f"{name} is implausibly large.")
    return int(cents)


def _opt_int(raw: Any, name: str, lo: int = 0, hi: int = MAX_RANK) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise ContestError("INVALID_CONTEST", f"{name} must be a whole number.")
    if isinstance(raw, str):
        s = raw.replace(",", "").strip()
        if not re.fullmatch(r"\d{1,9}", s):
            raise ContestError("INVALID_CONTEST", f"{name} must be a whole number.")
        raw = int(s)
    if isinstance(raw, float):
        if not raw.is_integer():
            raise ContestError("INVALID_CONTEST", f"{name} must be a whole number.")
        raw = int(raw)
    if not isinstance(raw, int) or not lo <= raw <= hi:
        raise ContestError("INVALID_CONTEST", f"{name} must be between {lo} and {hi}.")
    return raw


_RANK_RE = re.compile(
    r"^\s*(?P<a>\d{1,9})(?:st|nd|rd|th)?\s*(?:(?:-|–|—|to)\s*(?P<b>\d{1,9})(?:st|nd|rd|th)?)?\s*[:=,\t ]\s*"
    r"(?P<amt>\$?\s*[\d,]+(?:\.\d{1,2})?)\s*$",
    re.IGNORECASE,
)


def parse_payout_text(text: str) -> list[PayoutBand]:
    """Parse a pasted payout table: one band per line, ``1 $1,000`` / ``2-5: 100`` / ``6th–10th 50``.

    Every line must parse; an unreadable line is an error naming the line, never skipped.
    """
    if not isinstance(text, str) or not text.strip():
        raise ContestError(
            "PAYOUT_INCOMPLETE", "Paste the payout table (one rank or rank range per line)."
        )
    bands: list[PayoutBand] = []
    bad: list[dict[str, Any]] = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        m = _RANK_RE.match(line)
        if not m:
            bad.append({"line": n, "text": line.strip()[:80]})
            continue
        a = int(m["a"])
        b = int(m["b"]) if m["b"] else a
        try:
            cents = dollars_to_cents(m["amt"], f"line {n} prize")
        except ContestError:
            bad.append({"line": n, "text": line.strip()[:80]})
            continue
        bands.append(PayoutBand(a, b, cents))
        if len(bands) > MAX_BANDS:
            raise ContestError("INVALID_CONTEST", f"More than {MAX_BANDS} payout lines.")
    if bad:
        raise ContestError(
            "PAYOUT_UNREADABLE", "Some payout lines could not be read.", {"lines": bad[:20]}
        )
    return bands


def _bands_from_json(raw: Any) -> list[PayoutBand]:
    if not isinstance(raw, list):
        raise ContestError("INVALID_CONTEST", "ladder must be a list of bands.")
    if len(raw) > MAX_BANDS:
        raise ContestError("INVALID_CONTEST", f"More than {MAX_BANDS} payout bands.")
    out = []
    for i, b in enumerate(raw):
        if not isinstance(b, dict):
            raise ContestError("INVALID_CONTEST", f"band {i + 1} must be an object.")
        kind = b.get("kind", "cash")
        if kind not in PRIZE_KINDS:
            raise ContestError(
                "INVALID_CONTEST", f"band {i + 1} kind must be one of {PRIZE_KINDS}."
            )
        lo = _opt_int(b.get("minRank"), f"band {i + 1} minRank", 1)
        hi = _opt_int(b.get("maxRank", b.get("minRank")), f"band {i + 1} maxRank", 1)
        if lo is None or hi is None:
            raise ContestError("INVALID_CONTEST", f"band {i + 1} needs minRank.")
        value = b.get("value")
        out.append(
            PayoutBand(
                lo,
                hi,
                dollars_to_cents(b.get("prize"), f"band {i + 1} prize"),
                kind,
                None if value in (None, "") else dollars_to_cents(value, f"band {i + 1} value"),
            )
        )
    return out


def parse_contest(raw: dict[str, Any]) -> Contest:
    """Owner payload → :class:`Contest`.  Structural errors raise; review findings go to the report."""
    if not isinstance(raw, dict):
        raise ContestError("INVALID_CONTEST", "contest must be an object.")
    name = str(raw.get("name") or "").strip()[:120]
    if not name:
        raise ContestError("INVALID_CONTEST", "Give the contest a name.")
    entry_method = raw.get("entryMethod", "cash")
    if entry_method not in ENTRY_METHODS:
        raise ContestError("INVALID_CONTEST", f"entryMethod must be one of {ENTRY_METHODS}.")
    fee = 0 if entry_method == "free" else dollars_to_cents(raw.get("entryFee"), "Entry fee")
    if entry_method == "free" and raw.get("entryFee") not in (None, "", 0, "0"):
        raise ContestError("INVALID_CONTEST", "A free contest cannot have an entry fee.")
    guaranteed = raw.get("guaranteed")
    if guaranteed not in (True, False, None):
        raise ContestError("INVALID_CONTEST", "guaranteed must be true, false or unknown (null).")
    tie_rule = raw.get("tieRule", "unknown")
    if tie_rule not in TIE_RULES:
        raise ContestError("INVALID_CONTEST", f"tieRule must be one of {TIE_RULES}.")
    source = raw.get("ladderSource", "entered")
    if source not in LADDER_SOURCES:
        raise ContestError("INVALID_CONTEST", f"ladderSource must be one of {LADDER_SOURCES}.")
    if raw.get("payoutText"):
        ladder = parse_payout_text(str(raw["payoutText"]))
    else:
        ladder = _bands_from_json(raw.get("ladder") or [])
    pcid = raw.get("platformContestId")
    if pcid is not None and not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z\-_]{0,63}", str(pcid)):
        raise ContestError("INVALID_CONTEST", "platformContestId has unexpected characters.")
    return Contest(
        name=name,
        platform=str(raw.get("platform") or ""),
        sport=str(raw.get("sport") or ""),
        format=str(raw.get("format") or ""),
        entry_fee_cents=fee,
        entry_method=entry_method,
        capacity=_opt_int(raw.get("capacity"), "Capacity", 1),
        current_entries=_opt_int(raw.get("currentEntries"), "Current entries", 0),
        guaranteed=guaranteed,
        max_entries_per_user=_opt_int(raw.get("maxEntriesPerUser"), "Max entries per user", 1),
        existing_user_entries=_opt_int(raw.get("existingUserEntries"), "Your existing entries", 0),
        tie_rule=tie_rule,
        ladder_source=source,
        ladder=ladder,
        platform_contest_id=str(pcid) if pcid is not None else None,
        notes=(str(raw.get("notes"))[:500] if raw.get("notes") else None),
    )


# ── validation + derived economics ────────────────────────────────────


def _classify_shape(c: Contest, paid: int, first_share: Fraction | None) -> dict[str, Any]:
    """Describe the payout SHAPE from the ladder alone.  Descriptive, never a strategy."""
    cash = [b for b in c.ladder if b.kind == "cash"]
    if not cash or c.capacity is None or not paid:
        return {"shape": "unknown", "basis": "needs a cash ladder and a capacity"}
    flat = len({b.prize_cents for b in cash}) == 1
    paid_share = Fraction(paid, c.capacity)
    if c.capacity == 2 and paid == 1:
        return {"shape": "head_to_head", "basis": "2 entries, 1 paid"}
    if flat and c.entry_fee_cents:
        mult = Fraction(cash[0].prize_cents, c.entry_fee_cents)
        if Fraction(2, 5) <= paid_share <= Fraction(1, 2) and Fraction(9, 5) <= mult <= 2:
            label = "fifty_fifty" if paid_share == Fraction(1, 2) else "double_up"
            return {
                "shape": label,
                "basis": f"flat prizes, {float(paid_share):.0%} paid at {float(mult):.2f}x",
            }
        return {"shape": "multiplier", "basis": f"flat prizes at {float(mult):.2f}x the fee"}
    return {
        "shape": "tournament",
        "basis": f"{float(paid_share):.1%} paid; first place {float(first_share or 0):.1%} of cash prizes",
    }


def validate_contest(c: Contest) -> dict[str, Any]:
    """Errors block use; warnings flag a schedule for owner review and are NEVER auto-corrected."""
    errors: list[str] = []
    warnings: list[str] = []
    bands = sorted(c.ladder, key=lambda b: (b.min_rank, b.max_rank))
    if not bands:
        errors.append("No payout ladder: contest value cannot be evaluated (PAYOUT_INCOMPLETE).")
    for b in bands:
        if b.max_rank < b.min_rank:
            errors.append(f"Band {b.min_rank}-{b.max_rank} ends before it starts.")
        if b.kind != "cash" and b.value_cents is None:
            warnings.append(
                f"Ranks {b.min_rank}-{b.max_rank} pay a {b.kind} with no stated cash value; excluded from cash totals."
            )
    for prev, cur in zip(bands, bands[1:]):
        if cur.min_rank <= prev.max_rank:
            errors.append(
                f"Ranks {cur.min_rank}-{cur.max_rank} overlap ranks {prev.min_rank}-{prev.max_rank}."
            )
        elif cur.min_rank > prev.max_rank + 1:
            warnings.append(
                f"No prize listed for ranks {prev.max_rank + 1}-{cur.min_rank - 1}; check the table."
            )
        pv, cv = prev.cash_value(), cur.cash_value()
        if pv is not None and cv is not None and cv > pv:
            warnings.append(
                f"Rank {cur.min_rank} pays more than rank {prev.max_rank}; unusual, not rewritten."
            )
    if bands and bands[0].min_rank != 1:
        warnings.append(f"The ladder starts at rank {bands[0].min_rank}, not 1.")
    paid = sum(b.places for b in bands if b.max_rank >= b.min_rank)
    if c.capacity is not None and bands and bands[-1].max_rank > c.capacity:
        errors.append(f"The ladder pays rank {bands[-1].max_rank} but capacity is {c.capacity}.")
    if c.current_entries is not None and c.capacity is not None and c.current_entries > c.capacity:
        errors.append("Current entries exceed capacity.")
    if (
        c.existing_user_entries is not None
        and c.max_entries_per_user is not None
        and c.existing_user_entries > c.max_entries_per_user
    ):
        errors.append("Your existing entries exceed the per-user limit.")
    if c.ladder_source == "hypothetical":
        warnings.append(
            "Hypothetical ladder: exact contest value is suppressed until the real ladder is entered."
        )

    cash_total = sum(b.places * b.prize_cents for b in bands if b.kind == "cash")
    valued = [b for b in bands if b.cash_value() is not None]
    unvalued = [b for b in bands if b.cash_value() is None]
    value_total = sum(b.places * (b.cash_value() or 0) for b in valued)
    first = next((b for b in bands if b.min_rank == 1 and b.kind == "cash"), None)
    first_share = Fraction(first.prize_cents, cash_total) if first and cash_total else None
    min_cash = min((b.prize_cents for b in bands if b.kind == "cash"), default=None)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "derived": {
            "paidPlaces": paid,
            "paidShare": (paid / c.capacity) if c.capacity else None,
            "cashPrizeCents": cash_total,
            "prizeValueCents": None if unvalued else value_total,
            "firstPlaceCents": first.prize_cents if first else None,
            "firstPlaceShareOfCash": float(first_share) if first_share is not None else None,
            "minCashCents": min_cash,
            "payoutShape": _classify_shape(c, paid, first_share),
            "economics": economics(c, cash_total, None if unvalued else value_total),
            "exactEvAllowed": not errors and c.ladder_source != "hypothetical" and not unvalued,
        },
    }


def economics(c: Contest, cash_total: int, value_total: int | None) -> dict[str, Any]:
    """Rake / overlay / underfill, each only where its inputs apply."""
    pool = value_total if value_total is not None else None
    out: dict[str, Any] = {"state": "unknown", "effectiveRake": None, "nominalRakeAtCapacity": None}
    if c.entry_method == "free" or c.entry_fee_cents == 0:
        out.update(state="free_contest", note="No entry fee: rake does not apply.")
        return out
    if c.entry_method == "ticket":
        out.update(state="ticket_entry", note="Entered with a ticket: cash rake is not computed.")
        return out
    if pool is None:
        out.update(state="prize_value_unknown", note="A non-cash prize has no stated value.")
        return out
    if c.capacity:
        out["nominalRakeAtCapacity"] = 1 - pool / (c.capacity * c.entry_fee_cents)
    if not c.current_entries:
        out.update(
            state="field_unknown" if c.current_entries is None else "empty_contest",
            note="Effective rake needs the actual number of entries.",
        )
        return out
    collected = c.current_entries * c.entry_fee_cents
    effective = 1 - pool / collected
    full = c.capacity is not None and c.current_entries >= c.capacity
    if full or effective >= 0:
        out.update(state="raked", effectiveRake=effective)
        if not full:
            out["note"] = (
                "Underfilled, but prizes are still below fees collected: this is NOT an overlay."
            )
        return out
    # Prizes exceed fees collected.
    if c.guaranteed is True:
        out.update(state="overlay", effectiveRake=effective, overlayCents=pool - collected)
    elif c.guaranteed is False:
        out.update(
            state="underfilled_not_guaranteed",
            note="Not guaranteed: prizes may shrink or the contest may cancel.",
        )
    else:
        out.update(
            state="underfilled_guarantee_unknown",
            note="Whether prizes are guaranteed is unknown, so no overlay is claimed.",
        )
    return out


# ── exact payouts ─────────────────────────────────────────────────────


def prize_at(ladder: list[PayoutBand], rank: int) -> int:
    """Cash cents paid at one rank (0 outside the ladder — a real zero, the rank is unpaid)."""
    for b in ladder:
        if b.kind == "cash" and b.min_rank <= rank <= b.max_rank:
            return b.prize_cents
    return 0


def tied_payout(
    ladder: list[PayoutBand], first_rank: int, tied: int, tie_rule: str
) -> dict[str, Any]:
    """Each of ``tied`` entries occupying ranks first_rank..first_rank+tied-1.

    ``split_positions``: each receives the SUM of those ranks' prizes divided by
    ``tied`` — two entries tied across $1,000 and $100 each get $550.  Exact:
    a non-integral cent share is reported as a fraction, never silently rounded.
    """
    if tied < 1 or first_rank < 1:
        raise ContestError("INVALID_CONTEST", "tied and first_rank must be at least 1.")
    if tied == 1:
        return {
            "state": "exact",
            "eachCents": prize_at(ladder, first_rank),
            "exact": str(prize_at(ladder, first_rank)),
        }
    if tie_rule != "split_positions":
        return {
            "state": "unavailable",
            "reason": "The contest's tie rule is unknown; tied payouts are not assumed.",
        }
    total = sum(prize_at(ladder, r) for r in range(first_rank, first_rank + tied))
    share = Fraction(total, tied)
    if share.denominator == 1:
        return {
            "state": "exact",
            "eachCents": int(share),
            "exact": str(share),
            "pooledCents": total,
        }
    return {
        "state": "exact_fraction",
        "eachCents": None,
        "exact": f"{share.numerator}/{share.denominator}",
        "floorCents": share.numerator // share.denominator,
        "pooledCents": total,
        "note": "The share is not a whole cent; the platform's rounding rule is not verified.",
    }


# ── entry cap ─────────────────────────────────────────────────────────


def entry_upper_bound(c: Contest, spend_limit_cents: int | None) -> dict[str, Any]:
    """Hard ceiling on NEW entries — a constraint, never a recommendation."""
    terms: dict[str, int | None] = {}
    missing: list[str] = []
    if c.max_entries_per_user is None:
        missing.append("maxEntriesPerUser")
    elif c.existing_user_entries is None:
        missing.append("existingUserEntries")
    else:
        terms["remainingAllowance"] = max(0, c.max_entries_per_user - c.existing_user_entries)
    if c.capacity is not None and c.current_entries is not None:
        terms["openCapacity"] = max(0, c.capacity - c.current_entries)
    else:
        missing.append("capacity/currentEntries")
    if c.entry_method == "cash" and c.entry_fee_cents > 0:
        if spend_limit_cents is None:
            missing.append("spendLimit")
        else:
            terms["affordable"] = spend_limit_cents // c.entry_fee_cents
    known = [v for v in terms.values() if v is not None]
    bound = min(known) if known and not missing else None
    binding = [k for k, v in terms.items() if bound is not None and v == bound]
    return {
        "upperBound": bound,
        "terms": terms,
        "binding": binding,
        "missing": missing,
        "totalFeeCentsAtBound": (bound * c.entry_fee_cents) if bound is not None else None,
        "note": (
            "This is the most you are allowed/able to enter, not how many you should. "
            + (
                "Enter a spend limit to compute it — it is never inferred. "
                if "spendLimit" in missing
                else ""
            )
        ).strip(),
        "recommendation": {
            "state": "unavailable",
            "reason": "Recommending a count needs contest EV (outcome distributions, a field model and "
            "this ladder). Not built yet; zero is always an allowed answer.",
        },
    }
