# """
# Dynasty Trade Value Scraper v8 (improved)
#
# Sources:
# ✓ KeepTradeCut (KTC)       — browser, Superflex + TE+
# ✓ FantasyCalc              — JSON API, Superflex + TEP
# ✓ DynastyDaddy             — browser + API intercept, dynasty-daddy.com
# ✓ FantasyPros              — browser, current month article
# ✓ DraftSharks              — browser, TEP url (full infinite-scroll load)
# ✓ Yahoo (Justin Boone)     — browser, auto-discovers current month articles
# ✓ DynastyNerds             — browser, SF+TEP consensus rankings
# ✓ DLF (DynastyLeagueFootball) — local CSV imports, SF + IDP + rookie overlays (Avg rank → canonical value)
# ✓ IDPTradeCalc             — browser, idptradecalculator.com (SF+TEP default)
# ✓ Flock                    — browser, saved login session, reads OVR rank per player
#
# CHANGES FROM v7 (review-driven improvements):
#
# [P0] compute_max() now returns 1 instead of 0 when no valid values exist,
#      preventing NaN/Infinity in dashboard normalization (division by zero)
# [P0] IDPTradeCalc bulk JS extract uses .update() instead of overwriting
#      FULL_DATA["IDPTradeCalc"], preventing data loss from partial extracts
# [P1] Added retry decorator with exponential backoff for all browser scrapers
#      and the FantasyCalc API call — handles transient network errors
# [P1] Hyphen normalization in _tokenize() — "Amon-Ra" now matches "Amon Ra"
# [P1] Length-aware similarity penalty — short names (≤5 chars) get a penalty
#      to prevent "DJ" matching "D.J. Moore" with inflated scores
# [P1] Scrape health report at end — shows per-site player counts, coverage
#      distribution, and flags players found on only 1 site
# [P2] Development response caching — set USE_CACHE=True to cache site
#      responses for 4 hours, dramatically speeding up iteration
# [P2] Parallel scraping — KTC, DynastyDaddy, and DraftSharks now run
#      concurrently in separate browser pages (saves ~30-50% total time)
# """

import asyncio
import ast
import functools
import inspect
import re
import csv
import json
import os
import time
import datetime
import math
import hashlib
import shutil
import zipfile
import bisect
from difflib import SequenceMatcher
from urllib.parse import urlparse

import requests
from playwright.async_api import async_playwright
import sys

try:
    from src.scoring import (
        build_default_baseline_config,
        build_league_scoring_config,
        bucket_rule_contributions,
        compare_to_baseline,
        persist_scoring_delta_map,
        compute_profile_features,
        infer_archetype,
        build_scoring_tags,
        build_player_scoring_adjustment,
        choose_final_multiplier,
        compute_sample_size_score,
        run_scoring_backtest,
        persist_scoring_config,
    )
except Exception:
    # Keep scraper runnable even if optional scoring package is unavailable.
    build_default_baseline_config = None
    build_league_scoring_config = None
    bucket_rule_contributions = None
    compare_to_baseline = None
    persist_scoring_delta_map = None
    compute_profile_features = None
    infer_archetype = None
    build_scoring_tags = None
    build_player_scoring_adjustment = None
    choose_final_multiplier = None
    compute_sample_size_score = None
    run_scoring_backtest = None
    persist_scoring_config = None

# Prevent Windows console encoding crashes on status symbols (e.g., ✓, →).
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# Directory where this script lives — all output files save here
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_SCRIPT_DIR = SCRIPT_DIR  # immutable repo/script anchor for local source inputs

def _env_int(name, default):
    """Read positive int env var with safe fallback."""
    try:
        v = int(str(os.environ.get(name, default)).strip())
        if v > 0:
            return v
    except Exception:
        pass
    return int(default)

def _env_str(name, default=""):
    """Read string env var with safe fallback."""
    raw = os.environ.get(name)
    if raw is None:
        return str(default)
    v = str(raw).strip()
    return v if v else str(default)

# Deep coverage targets and caps (tunable via env vars).
TARGET_OFFENSIVE_POOL = _env_int("TARGET_OFFENSIVE_POOL", 350)
TARGET_IDP_POOL = _env_int("TARGET_IDP_POOL", 275)
MIN_IDP_POOL_FLOOR = _env_int("MIN_IDP_POOL_FLOOR", 250)
SITE_CAP_OFFENSE = _env_int("SITE_CAP_OFFENSE", 550)
SITE_CAP_DEFENSE = _env_int("SITE_CAP_DEFENSE", 425)
SITE_CAP_COMBINED = _env_int("SITE_CAP_COMBINED", 900)
SITE_CAP_DRAFTSHARKS = _env_int("SITE_CAP_DRAFTSHARKS", 900)
# IDPTradeCalc autocomplete: search for players the API intercept misses.
# The site's API only returns IDP players, but the search box finds offense too.
# Enable by default so KTC offense players get looked up on IDPTradeCalc.
IDP_AUTOCOMPLETE_MAX = _env_int("IDP_AUTOCOMPLETE_MAX", 500)
IDP_AUTOCOMPLETE_ENABLE = _env_str("IDP_AUTOCOMPLETE_ENABLE", "true").strip().lower() in {"1", "true", "yes", "on"}
TOP_OFF_COVERAGE_AUDIT_N = _env_int("TOP_OFF_COVERAGE_AUDIT_N", 300)
TOP_IDP_COVERAGE_AUDIT_N = _env_int("TOP_IDP_COVERAGE_AUDIT_N", 250)
TOP_OFF_MIN_SOURCES = _env_int("TOP_OFF_MIN_SOURCES", 1)
TOP_IDP_MIN_SOURCES = _env_int("TOP_IDP_MIN_SOURCES", 1)
TOP_OFF_EXPECTED_SITE_KEYS = ("ktc",)
TOP_IDP_EXPECTED_SITE_KEYS = ("idpTradeCalc",)

# ─────────────────────────────────────────
# [NEW] DEVELOPMENT CACHING
# Set USE_CACHE = True to cache scraped data for faster iteration.
# Cached responses expire after CACHE_TTL_HOURS.
# ─────────────────────────────────────────
USE_CACHE = False
CACHE_TTL_HOURS = 4
CACHE_DIR = os.path.join(SCRIPT_DIR, ".scrape_cache")

def get_cached(site_key):
    """Return cached name_map dict if fresh enough, else None."""
    if not USE_CACHE:
        return None
    cache_file = os.path.join(CACHE_DIR, f"{site_key}.json")
    if not os.path.exists(cache_file):
        return None
    age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
    if age_hours > CACHE_TTL_HOURS:
        return None
    try:
        with open(cache_file, "r") as f:
            data = json.load(f)
        print(f"  [{site_key}] Using cached data ({age_hours:.1f}h old, {len(data)} players)")
        return data
    except Exception:
        return None

def set_cache(site_key, name_map):
    """Save name_map to cache."""
    if not USE_CACHE or not name_map:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, f"{site_key}.json")
    try:
        with open(cache_file, "w") as f:
            json.dump(name_map, f)
    except Exception:
        pass


# ─────────────────────────────────────────
# [NEW] RETRY DECORATOR
# Wraps async functions with exponential backoff.
# ─────────────────────────────────────────
def retry(max_attempts=3, delay=2, backoff=2, exceptions=(Exception,)):
    """Retry decorator with exponential backoff for async functions."""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        wait = delay * (backoff ** attempt)
                        print(f"  [Retry] {func.__name__} attempt {attempt+1} failed: {e}. "
                              f"Retrying in {wait}s...")
                        await asyncio.sleep(wait)
            raise last_exc
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        wait = delay * (backoff ** attempt)
                        print(f"  [Retry] {func.__name__} attempt {attempt+1} failed: {e}. "
                              f"Retrying in {wait}s...")
                        time.sleep(wait)
            raise last_exc
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


# ─────────────────────────────────────────
# SLEEPER LEAGUE — pulls rostered players automatically
# ─────────────────────────────────────────
DEFAULT_SLEEPER_LEAGUE_ID = "1312006700437352448"
SLEEPER_LEAGUE_ID = _env_str("SLEEPER_LEAGUE_ID", DEFAULT_SLEEPER_LEAGUE_ID)

# ─────────────────────────────────────────
# TRADE MOVEMENT ALERTS — email when your roster players move 5%+
# ─────────────────────────────────────────
ALERT_EMAIL = _env_str("ALERT_EMAIL", "jasonleetucker@icloud.com")
try:
    ALERT_THRESHOLD = float(_env_str("ALERT_THRESHOLD", "5.0"))  # percent change to trigger alert
except Exception:
    ALERT_THRESHOLD = 5.0
ALERT_ENABLED = _env_str("ALERT_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


# ─────────────────────────────────────────
# PLAYERS — priority: Sleeper rosters → players.txt → defaults
# ─────────────────────────────────────────
_DEFAULT_PLAYERS = []

SLEEPER_PLAYERS = []  # populated at runtime from Sleeper API
ROOKIE_MUST_HAVE_FILE = os.path.join(SCRIPT_DIR, "rookie_must_have.txt")
ROOKIE_MUST_HAVE_NAMES = []
ROOKIE_MUST_HAVE_POS_HINTS = {}

_IDP_POS_TOKENS = {
    "DL": "DL", "DE": "DL", "DT": "DL", "EDGE": "DL", "EDGE/LB": "DL",
    "LB": "LB", "ILB": "LB", "OLB": "LB",
    "DB": "DB", "S": "DB", "SAFETY": "DB", "FS": "DB", "SS": "DB",
    "CB": "DB", "NB": "DB",
}
_OFF_POS_TOKENS = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "FB": "RB"
}

def _extract_rookie_pos_hint(raw_line):
    line = str(raw_line or "").strip()
    if not line:
        return ""
    line = re.sub(r"^\s*\d+[\.)-]\s*", "", line)
    parts = [p.strip() for p in line.split(",") if p.strip()]
    candidates = []
    if len(parts) >= 2:
        candidates.extend(parts[1:3])
    candidates.append(line)
    for cand in candidates:
        tokens = re.findall(r"[A-Za-z/]+", cand.upper())
        for token in tokens:
            if token in _IDP_POS_TOKENS:
                return _IDP_POS_TOKENS[token]
            if token in _OFF_POS_TOKENS:
                return _OFF_POS_TOKENS[token]
    return ""

def _must_have_rookie_bucket(name):
    norm = normalize_lookup_name(name) if name else ""
    hint = ROOKIE_MUST_HAVE_POS_HINTS.get(norm, "")
    if hint in {"QB", "RB", "WR", "TE", "DL", "LB", "DB"}:
        return hint
    return ""

def load_rookie_must_have(path):
    """Load newline-delimited rookie names, deduped after cleaning."""
    global ROOKIE_MUST_HAVE_POS_HINTS
    names = []
    seen = set()
    ROOKIE_MUST_HAVE_POS_HINTS = {}
    if not path or not os.path.exists(path):
        return names
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = str(raw or "").strip()
                if not line or line.startswith("#"):
                    continue
                pos_hint = _extract_rookie_pos_hint(line)
                cleaned = clean_name(re.sub(r"^\s*\d+[\.)-]\s*", "", line))
                if not cleaned:
                    continue
                key = cleaned.lower()
                if key in seen:
                    if pos_hint and key and key not in ROOKIE_MUST_HAVE_POS_HINTS:
                        ROOKIE_MUST_HAVE_POS_HINTS[key] = pos_hint
                    continue
                seen.add(key)
                names.append(cleaned)
                if pos_hint and key:
                    ROOKIE_MUST_HAVE_POS_HINTS[key] = pos_hint
    except Exception as e:
        print(f"  [Rookies] Failed loading must-have rookies: {e}")
    return names


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

# Common team abbreviations appended directly to names on some sites
_TEAM_CODES = {
    "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN",
    "DET","GB","HOU","IND","JAC","JAX","KC","LAC","LAR","LV",
    "MIA","MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF",
    "TB","TEN","WAS","FA","LVR","GBP","SFO","TBB","KCC","NEP",
}

def clean_name(raw):
    """Strip position/team suffixes, generational suffixes, and inline team codes.
    Also normalizes unicode escapes and apostrophe variants."""
    if not raw:
        return ""
    name = str(raw).strip()
    # Decode literal unicode escapes like \u0027 → '
    if '\\u' in name:
        try:
            name = name.encode('utf-8').decode('unicode_escape')
        except Exception:
            name = re.sub(r'\\u([0-9a-fA-F]{4})',
                          lambda m: chr(int(m.group(1), 16)), name)
    # Trim ranking prefixes and misc scrape markers.
    name = re.sub(r"^\s*#?\d+\s*[\).:-]\s*", "", name)
    name = re.sub(r"\s*[\*\u2020\u2021]+\s*$", "", name)
    # Strip trailing parenthetical notes: "X Player (IR)".
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    # Normalize various apostrophe/quote chars to standard apostrophe
    name = re.sub(r'[\u2018\u2019\u0060\u00B4\u0027\u2032]', "'", name)
    # Convert "Last, First" to "First Last" where applicable.
    if "," in name:
        m = re.match(r"^\s*([A-Za-z.'\- ]+),\s*([A-Za-z.'\- ]+)\s*$", name)
        if m:
            name = f"{m.group(2).strip()} {m.group(1).strip()}".strip()
    # Strip position/team tag after name (e.g. "Caleb Williams QB CHI")
    name = re.split(r'\s+(QB|RB|WR|TE|K|DEF|DST|OL|LB|DB|DL|DE|DT|CB|S|PK)\b', name)[0].strip()
    # Strip team code glued to end (e.g. "Caleb WilliamsCHI")
    m = re.match(r'^(.+?)([A-Z]{2,3})$', name)
    if m and m.group(2) in _TEAM_CODES and len(m.group(1).strip()) > 3:
        name = m.group(1).strip()
    # Strip generational suffixes: Jr., Sr., II, III, IV, V (with or without period/comma)
    name = re.sub(r'[,\s]+(Jr.?|Sr.?|I{2,3}|IV|V|VI)\s*$', '', name, flags=re.IGNORECASE).strip()
    # Normalize periods in initials: "T.J." → "T.J.", but also allow matching "TJ"
    # Don't strip periods here — handle in matching instead
    # Collapse any double spaces
    name = re.sub(r'\s{2,}', ' ', name)
    return name


@functools.lru_cache(maxsize=8192)
def normalize_lookup_name(raw):
    """Name key for resilient matching across sources."""
    s = clean_name(raw or "").lower()
    # Treat punctuation variants as the same player identity:
    # "T.J. Parker", "TJ Parker", and "T J Parker" -> "tj parker".
    s = s.replace("-", " ")
    s = s.replace(".", "")
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return s
    parts = s.split()
    # Collapse leading initial tokens: "t j parker" -> "tj parker".
    initial_run = []
    idx = 0
    while idx < len(parts) and len(parts[idx]) == 1:
        initial_run.append(parts[idx])
        idx += 1
    if len(initial_run) >= 2:
        merged = ''.join(initial_run)
        s = ' '.join([merged] + parts[idx:])
    return s


def _tokenize(name):
    """Lowercase, normalize hyphens, split, sort tokens for order-independent comparison."""
    # Normalize hyphens to spaces, remove periods for matching: "T.J." → "tj", "Amon-Ra" → "amon ra"
    normalized = name.lower().replace('-', ' ').replace('.', '')
    return sorted(normalized.split())


def similarity(a, b):
    """
    Compute similarity with a token-sorted approach.
    Handles cases like "Travis Etienne" vs "Etienne, Travis" and
    partial matches like "C. Williams" vs "Caleb Williams".

    When last names match but first names are clearly different,
    we apply a penalty to prevent "Caleb Williams" matching "James Williams".

    [NEW] Length-aware penalty: very short names (≤5 chars) get penalized
    to prevent "DJ" from matching "D.J. Moore" with inflated scores.
    """
    a_low, b_low = a.lower().strip(), b.lower().strip()
    # Direct ratio
    direct = SequenceMatcher(None, a_low, b_low).ratio()
    # Token-sorted ratio (handles reordered tokens)
    # [FIX] Use hyphen-normalized tokens
    a_sorted = " ".join(_tokenize(a_low))
    b_sorted = " ".join(_tokenize(b_low))
    token_sorted = SequenceMatcher(None, a_sorted, b_sorted).ratio()
    base = max(direct, token_sorted)

    # Adjust based on first/last name analysis
    a_parts, b_parts = a_low.split(), b_low.split()
    adjustment = 0.0
    if len(a_parts) >= 2 and len(b_parts) >= 2:
        last_a, last_b = a_parts[-1], b_parts[-1]
        first_a, first_b = a_parts[0].rstrip('.'), b_parts[0].rstrip('.')

        if last_a == last_b and len(last_a) > 2:
            # Same last name — check first names carefully
            if first_a == first_b:
                adjustment = 0.02
            elif first_a[0] == first_b[0] and (len(first_a) <= 2 or len(first_b) <= 2):
                adjustment = 0.10
            else:
                # Prefix-subset penalty: one first name is a strict prefix
                # of the other with 2+ extra chars → distinct people.
                # e.g. "james"/"jameson", "chris"/"christian"
                shorter_f, longer_f = (first_a, first_b) if len(first_a) <= len(first_b) else (first_b, first_a)
                if longer_f.startswith(shorter_f) and (len(longer_f) - len(shorter_f)) >= 2:
                    adjustment = -0.20
                else:
                    first_sim = SequenceMatcher(None, first_a, first_b).ratio()
                    if first_sim < 0.5:
                        adjustment = -0.15
                    else:
                        adjustment = -0.05
        elif last_a != last_b:
            if first_a == first_b and len(first_a) > 2:
                pass  # Same first name, different last — no special adjustment

    # [NEW] Length penalty — prevent very short names from inflating similarity
    min_len = min(len(a_low), len(b_low))
    if min_len <= 5:
        adjustment -= 0.08  # short names are unreliable matches

    return base + adjustment


# ── Position-family normalization for cross-source matching ──────────────
_POS_FAMILY_MAP = {
    "DE": "DL", "DT": "DL", "EDGE": "DL", "NT": "DL", "DL": "DL",
    "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "DB": "DB",
    "OLB": "LB", "ILB": "LB", "MLB": "LB", "LB": "LB",
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K",
}

def _pos_family(pos_raw):
    """Normalize a position to its family (DL, DB, LB, QB, RB, WR, TE)."""
    if not pos_raw:
        return ""
    return _POS_FAMILY_MAP.get(pos_raw.strip().upper(), pos_raw.strip().upper())

def _get_sleeper_pos(name):
    """Look up a player's position from SLEEPER_ROSTER_DATA (if available)."""
    pos_map = SLEEPER_ROSTER_DATA.get("positions", {})
    if not pos_map:
        return ""
    # Exact match
    pos = pos_map.get(name, "")
    if pos:
        return _pos_family(pos)
    # Case-insensitive fallback
    nl = name.lower()
    for k, v in pos_map.items():
        if k.lower() == nl:
            return _pos_family(v)
    return ""

def _positions_compatible(name_a, name_b):
    """Check whether two player names have compatible positions.

    Returns True if:
    - either player has no known position (can't reject)
    - both have the same position family
    Returns False if both have known but different position families.
    """
    pos_a = _get_sleeper_pos(name_a)
    pos_b = _get_sleeper_pos(name_b)
    if not pos_a or not pos_b:
        return True  # Can't reject without position data
    return pos_a == pos_b


def best_match(target, candidates, threshold=0.78, match_guard=None):
    """Find the best fuzzy match for target among candidates.

    match_guard: optional callable (target, candidate) -> bool
    used to reject structurally unsafe matches.
    """
    best, best_score = None, 0
    for c in candidates:
        if match_guard and not match_guard(target, c):
            continue
        s = similarity(target, c)
        if s > best_score:
            best, best_score = c, s
    if DEBUG and best and best_score >= threshold:
        print(f"    ✓ '{target}' → '{best}' ({best_score:.2f})")
    return best if best_score >= threshold else None

def _name_tokens(name):
    """Normalize a name into ordered alpha tokens for conservative merge checks."""
    cleaned = clean_name(name).lower().replace(".", "").replace("-", " ").replace("'", " ")
    return [t for t in cleaned.split() if t]


def _first_name_compatible(a_first, b_first):
    """Allow exact, initial, and near-typo first-name matches.

    Rejects prefix-subset names where one is a strict prefix of the other
    with 2+ extra characters (e.g. "james" vs "jameson", "chris" vs
    "christian").  These are almost always distinct people even though
    SequenceMatcher rates them highly similar.
    """
    if not a_first or not b_first:
        return False
    if a_first == b_first:
        return True
    if len(a_first) == 1 and a_first == b_first[:1]:
        return True
    if len(b_first) == 1 and b_first == a_first[:1]:
        return True
    # Reject when one name is a strict prefix of the other with 2+ extra
    # chars — these are distinct names, not typos.
    # e.g. "james"/"jameson", "chris"/"christian", "mark"/"marquez"
    shorter, longer = (a_first, b_first) if len(a_first) <= len(b_first) else (b_first, a_first)
    if longer.startswith(shorter) and (len(longer) - len(shorter)) >= 2:
        return False
    return SequenceMatcher(None, a_first, b_first).ratio() >= 0.72


def _is_safe_name_merge(src_name, dst_name):
    """Guard fuzzy canonicalization so unrelated players are not merged.

    Checks both name structure AND position compatibility. Two players
    with known but different position families (e.g. WR vs DB) are never
    merged, even if their names are similar.
    """
    # Position gate: reject if both players have known incompatible positions
    if not _positions_compatible(src_name, dst_name):
        return False

    src = _name_tokens(src_name)
    dst = _name_tokens(dst_name)
    if len(src) < 2 or len(dst) < 2:
        return False

    src_first, dst_first = src[0], dst[0]
    src_last, dst_last = src[-1], dst[-1]
    src_mid = src[1:-1]
    dst_mid = dst[1:-1]

    # Do not merge names that share first+last but differ on non-trivial middle tokens.
    # Example: "Josh Allen" vs "Josh Hines-Allen" must remain distinct.
    if src_first == dst_first and src_last == dst_last and src_mid != dst_mid:
        return False

    # Exact or near-exact last names must still have compatible first names.
    if src_last == dst_last:
        return _first_name_compatible(src_first, dst_first)
    if SequenceMatcher(None, src_last, dst_last).ratio() >= 0.92:
        return _first_name_compatible(src_first, dst_first)

    # Allow one trailing short token artifact (e.g., "Gervon Dexter Dr" -> "Gervon Dexter").
    if len(src) == len(dst) + 1 and len(src[-1]) <= 3 and src[:-1] == dst:
        return True
    if len(dst) == len(src) + 1 and len(dst[-1]) <= 3 and dst[:-1] == src:
        return True

    return False
def match_all(players, name_map, results, site_key=None):
    """Match a list of player names against a scraped name->value dict.
    If site_key is given, stores the full name_map in FULL_DATA for JSON export.
    """
    if site_key and name_map:
        FULL_DATA[site_key] = dict(name_map)

    # Build a period-normalized index for matching "TJ Watt" ↔ "T.J. Watt"
    norm_index = {}
    lookup_index = {}
    initial_index = {}       # (first_initial, remaining_name_tokens)
    initial_last_index = {}  # (first_initial, last_name)
    for k in name_map:
        norm_key = k.lower().replace('.', '').replace('-', ' ').strip()
        if norm_key not in norm_index:
            norm_index[norm_key] = k
        lookup_key = normalize_lookup_name(k)
        if lookup_key and lookup_key not in lookup_index:
            lookup_index[lookup_key] = k
        parts = normalize_lookup_name(k).split()
        if len(parts) >= 2:
            initial = parts[0][0].lower()
            remain = ' '.join(parts[1:])
            initial_index.setdefault((initial, remain), k)
            initial_last_index.setdefault((initial, parts[-1]), k)

    for player in players:
        # Try exact match first (fast path)
        if player in name_map:
            results[player] = name_map[player]
            if DEBUG:
                print(f"    ✓ '{player}' → exact match ({name_map[player]})")
            continue
        # Try period-normalized match (T.J. ↔ TJ)
        player_norm = player.lower().replace('.', '').replace('-', ' ').strip()
        if player_norm in norm_index:
            orig_key = norm_index[player_norm]
            results[player] = name_map[orig_key]
            if DEBUG:
                print(f"    ✓ '{player}' → normalized match '{orig_key}' ({name_map[orig_key]})")
            continue
        # Try fully normalized lookup match (apostrophes/suffixes/punctuation).
        player_lookup = normalize_lookup_name(player)
        if player_lookup in lookup_index:
            orig_key = lookup_index[player_lookup]
            results[player] = name_map[orig_key]
            if DEBUG:
                print(f"    ✓ '{player}' → lookup match '{orig_key}' ({name_map[orig_key]})")
            continue
        # Try initial-expansion match ("Jaxon Smith-Njigba" → matches "J. Smith-Njigba")
        p_parts = player_lookup.split() if player_lookup else []
        if len(p_parts) >= 2:
            p_initial = p_parts[0][0].lower()
            p_remaining = ' '.join(p_parts[1:])
            ikey = (p_initial, p_remaining)
            if ikey in initial_index:
                orig_key = initial_index[ikey]
                if _positions_compatible(player, orig_key):
                    results[player] = name_map[orig_key]
                    if DEBUG:
                        print(f"    ✓ '{player}' → initial match '{orig_key}' ({name_map[orig_key]})")
                    continue
            # Looser initial+last fallback for names with middle tokens.
            ikey_last = (p_initial, p_parts[-1])
            if ikey_last in initial_last_index:
                orig_key = initial_last_index[ikey_last]
                # Guard against collisions like "Josh Allen" vs "Josh Hines-Allen".
                if _is_safe_name_merge(player, orig_key):
                    results[player] = name_map[orig_key]
                    if DEBUG:
                        print(f"    ✓ '{player}' → initial+last match '{orig_key}' ({name_map[orig_key]})")
                    continue
        # Fuzzy match
        m = best_match(player, name_map.keys(), match_guard=_is_safe_name_merge)
        if m:
            results[player] = name_map[m]


# Global dict collecting full name_map for every site (for JSON export)
FULL_DATA = {}
DLF_IMPORT_DEBUG = {}

# KTC playerID → name mapping (populated during KTC rankings scrape)
KTC_ID_TO_NAME = {}

# KTC crowdsourced trade + waiver data
KTC_CROWD_DATA = {"trades": [], "waivers": []}

# KTC blocker diagnosis — set by scrape_ktc on failure for source reporting
_KTC_BLOCKER: str | None = None

# KTC crowd DB league constraints (user-specific)
KTC_CROWD_ALLOWED_TEAMS = {10, 12, 14}
KTC_CROWD_ALLOWED_TEP_LEVELS = {1, 2}  # TE+ or TE++


def compute_max(name_map):
    """Return the maximum value across all players in a name_map.

    [FIX P0] Returns 1 instead of 0 when no valid values exist.
    This prevents division-by-zero in the dashboard's normalization
    step (raw_value / max_value), which would produce Infinity/NaN
    and poison MetaValue calculations.
    """
    vals = [v for v in name_map.values()
            if v is not None and isinstance(v, (int, float)) and v > 0]
    return max(vals) if vals else 1  # ← was 0, now 1


def fetch_sleeper_rosters(league_id):
    """Fetch all rostered player names from a Sleeper league.
    Returns (player_names_list, roster_data_for_json)."""
    _req = requests

    VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF",
                       "LB", "DL", "DE", "DT", "CB", "S", "DB"}

    print(f"Fetching Sleeper player database...")
    try:
        players_resp = _req.get("https://api.sleeper.app/v1/players/nfl", timeout=30)
        players_resp.raise_for_status()
        all_nfl = players_resp.json()
        global SLEEPER_ALL_NFL
        SLEEPER_ALL_NFL = all_nfl
    except Exception as e:
        print(f"  [Sleeper] Failed to fetch player database: {e}")
        return [], {}

    print(f"Fetching rosters for league {league_id}...")
    try:
        rosters_resp = _req.get(
            f"https://api.sleeper.app/v1/league/{league_id}/rosters", timeout=15)
        rosters_resp.raise_for_status()
        rosters = rosters_resp.json()
    except Exception as e:
        print(f"  [Sleeper] Failed to fetch rosters: {e}")
        return [], {}

    user_map = {}
    try:
        users_resp = _req.get(
            f"https://api.sleeper.app/v1/league/{league_id}/users", timeout=15)
        users_resp.raise_for_status()
        for u in users_resp.json():
            uid = u.get("user_id")
            name = (u.get("metadata", {}).get("team_name")
                    or u.get("display_name")
                    or f"Team {uid}")
            user_map[uid] = name
    except Exception:
        pass

    league_name = ""
    scoring_settings = {}
    roster_positions = []
    league_settings = {}
    try:
        league_resp = _req.get(
            f"https://api.sleeper.app/v1/league/{league_id}", timeout=10)
        league_resp.raise_for_status()
        league_info = league_resp.json()
        league_name = league_info.get("name", "")
        total_rosters = league_info.get("total_rosters", "?")
        scoring_settings = league_info.get("scoring_settings", {})
        roster_positions = league_info.get("roster_positions", [])
        league_settings = league_info.get("settings", {})
        print(f"  [Sleeper] League: {league_name} ({total_rosters} teams)")
        if scoring_settings:
            print(f"  [Sleeper] Scoring categories: {len(scoring_settings)}")
    except Exception:
        pass

    all_names = []
    position_map = {}
    player_id_map = {}
    id_to_player = {}
    teams = []
    team_pick_assets = {}
    team_pick_details = {}

    def _safe_int(v):
        try:
            return int(v)
        except Exception:
            return None

    def _round_suffix(round_num):
        if round_num == 1:
            return "st"
        if round_num == 2:
            return "nd"
        if round_num == 3:
            return "rd"
        return "th"

    def _pick_sort_key(label):
        s = str(label or "")
        m_slot = re.match(r"^(20\d{2})\s+([1-6])\.(\d{1,2})", s)
        if m_slot:
            return (int(m_slot.group(1)), int(m_slot.group(2)), int(m_slot.group(3)), s)
        m = re.match(r"^(20\d{2})\s+([1-6])", s)
        if m:
            return (int(m.group(1)), int(m.group(2)), 99, s)
        return (9999, 9, 99, s)

    # Build per-team future pick ownership for roster dashboards.
    # Start with default ownership, then apply Sleeper traded-picks ownership.
    roster_ids = []
    roster_name_by_id = {}
    owner_to_roster_id = {}
    for r in rosters:
        rid = _safe_int(r.get("roster_id"))
        if rid is not None:
            roster_ids.append(rid)
            oid = r.get("owner_id", "")
            if oid:
                owner_to_roster_id[str(oid)] = rid
            roster_name_by_id[rid] = user_map.get(oid, f"Team {rid}")
    roster_id_set = set(roster_ids)
    league_size_for_tiers = _safe_int((league_settings or {}).get("num_teams")) or len(roster_ids) or 12
    league_size_for_tiers = max(3, int(league_size_for_tiers))

    def _slot_to_tier_label(slot):
        slot_num = _safe_int(slot)
        if not isinstance(slot_num, int) or slot_num <= 0:
            return "Mid"
        per_tier = max(1, league_size_for_tiers // 3)
        early_end = per_tier
        mid_end = min(league_size_for_tiers, per_tier * 2)
        if slot_num <= early_end:
            return "Early"
        if slot_num <= mid_end:
            return "Mid"
        return "Late"

    draft_rounds = _safe_int((league_settings or {}).get("draft_rounds")) or 4
    draft_rounds = max(1, min(6, draft_rounds))
    current_year = datetime.date.today().year
    pick_years = [current_year, current_year + 1, current_year + 2]

    pick_owner = {}  # (season, round, original_roster_id) -> owner_roster_id
    # Canonical pick identity map so trade-history can reference the exact pick label
    # (slot/tier + source team), not only generic "YYYY Round N".
    pick_identity = {}  # (season, round, original_roster_id) -> {baseLabel, fromTeam, slot}
    for season in pick_years:
        for round_num in range(1, draft_rounds + 1):
            for origin_rid in roster_ids:
                pick_owner[(season, round_num, origin_rid)] = origin_rid

    # Resolve exact rookie-draft slot (when available) so picks can be
    # represented as 2026 1.03 instead of only Early/Mid/Late style labels.
    draft_slot_by_origin = {}  # (season, original_roster_id) -> slot
    try:
        drafts_resp = _req.get(
            f"https://api.sleeper.app/v1/league/{league_id}/drafts",
            timeout=15
        )
        if drafts_resp.status_code == 200:
            drafts_json = drafts_resp.json()
            if isinstance(drafts_json, list):
                for draft in drafts_json:
                    season = _safe_int(draft.get("season"))
                    draft_id = draft.get("draft_id")
                    if season not in pick_years or not draft_id:
                        continue

                    draft_detail = {}
                    try:
                        detail_resp = _req.get(
                            f"https://api.sleeper.app/v1/draft/{draft_id}",
                            timeout=15
                        )
                        if detail_resp.status_code == 200:
                            dd = detail_resp.json()
                            if isinstance(dd, dict):
                                draft_detail = dd
                    except Exception:
                        draft_detail = {}

                    draft_order = draft_detail.get("draft_order") or draft.get("draft_order") or {}
                    if isinstance(draft_order, dict):
                        for uid, slot in draft_order.items():
                            rid = owner_to_roster_id.get(str(uid))
                            slot_num = _safe_int(slot)
                            if rid in roster_id_set and isinstance(slot_num, int) and slot_num > 0:
                                draft_slot_by_origin[(season, rid)] = slot_num

                    slot_to_roster = draft_detail.get("slot_to_roster_id") or draft.get("slot_to_roster_id") or {}
                    if isinstance(slot_to_roster, dict):
                        for slot, rid_val in slot_to_roster.items():
                            slot_num = _safe_int(slot)
                            rid = _safe_int(rid_val)
                            if rid in roster_id_set and isinstance(slot_num, int) and slot_num > 0:
                                draft_slot_by_origin[(season, rid)] = slot_num
    except Exception:
        draft_slot_by_origin = {}

    traded_picks = []
    try:
        tp_resp = _req.get(
            f"https://api.sleeper.app/v1/league/{league_id}/traded_picks",
            timeout=15
        )
        if tp_resp.status_code == 200:
            tp_json = tp_resp.json()
            if isinstance(tp_json, list):
                traded_picks = tp_json
    except Exception:
        traded_picks = []

    for tp in traded_picks:
        season = _safe_int(tp.get("season"))
        round_num = _safe_int(tp.get("round"))
        origin_rid = _safe_int(tp.get("roster_id"))
        owner_rid = _safe_int(tp.get("owner_id"))
        if (
            season in pick_years
            and isinstance(round_num, int) and 1 <= round_num <= draft_rounds
            and origin_rid in roster_id_set
            and owner_rid in roster_id_set
        ):
            pick_owner[(season, round_num, origin_rid)] = owner_rid

    for (season, round_num, origin_rid), owner_rid in pick_owner.items():
        slot_num = draft_slot_by_origin.get((season, origin_rid))
        # Keep current-year picks as slot-specific when available.
        # For future years (2027/2028), normalize to Early/Mid/Late buckets.
        if season >= current_year + 1:
            tier_label = _slot_to_tier_label(slot_num)
            base_label = f"{season} {tier_label} {round_num}{_round_suffix(round_num)}"
        elif isinstance(slot_num, int) and slot_num > 0:
            base_label = f"{season} {round_num}.{str(slot_num).zfill(2)}"
        else:
            base_label = f"{season} {round_num}{_round_suffix(round_num)}"
        from_team = roster_name_by_id.get(origin_rid, f"Team {origin_rid}")
        pick_identity[(season, round_num, origin_rid)] = {
            "baseLabel": base_label,
            "fromTeam": from_team,
            "slot": slot_num if isinstance(slot_num, int) else None,
        }
        if owner_rid == origin_rid:
            display_label = f"{base_label} (own)"
        else:
            display_label = f"{base_label} (from {from_team})"

        team_pick_assets.setdefault(owner_rid, []).append(display_label)
        team_pick_details.setdefault(owner_rid, []).append({
            "season": season,
            "round": round_num,
            "fromRosterId": origin_rid,
            "fromTeam": from_team,
            "ownerRosterId": owner_rid,
            "slot": slot_num if isinstance(slot_num, int) else None,
            "label": display_label,
            "baseLabel": base_label,
        })

    if team_pick_assets:
        total_pick_assets = sum(len(v) for v in team_pick_assets.values())
        print(f"  [Sleeper] Computed {total_pick_assets} future pick assets ({draft_rounds} rounds, years {pick_years})")

    for roster in rosters:
        owner_id = roster.get("owner_id", "")
        roster_id = roster.get("roster_id")
        roster_id_int = _safe_int(roster_id)
        team_name = user_map.get(owner_id, f"Team {roster.get('roster_id', '?')}")
        player_ids = roster.get("players") or []
        team_players = []
        team_player_ids = []

        for pid in player_ids:
            p = all_nfl.get(pid)
            if not p:
                continue
            full = (p.get("full_name")
                    or f"{p.get('first_name','')} {p.get('last_name','')}".strip())
            pos = p.get("position", "")
            if pos in VALID_POSITIONS and full:
                cn = clean_name(full)
                team_players.append(cn)
                all_names.append(cn)
                sid = str(pid)
                team_player_ids.append(sid)
                if cn and sid:
                    player_id_map[cn] = sid
                    id_to_player[sid] = cn
                if pos and cn:
                    # Multi-positional IDP rule: prefer non-LB for dual-position players
                    # Sleeper stores a single position; we override known edge cases
                    position_map[cn] = pos

        teams.append({
            "name": team_name,
            "roster_id": roster_id,
            "players": sorted(team_players),
            "playerIds": sorted(team_player_ids),
            "picks": sorted(team_pick_assets.get(roster_id_int, []), key=_pick_sort_key),
            "pickDetails": sorted(
                team_pick_details.get(roster_id_int, []),
                key=lambda d: (
                    int(d.get("season", 9999)),
                    int(d.get("round", 9)),
                    int(d.get("slot", 99)) if d.get("slot") is not None else 99,
                    str(d.get("fromTeam", ""))
                )
            ),
        })

    # Position overrides: prefer non-LB for DL/LB hybrids, force Travis Hunter → WR
    POSITION_OVERRIDES = {
        "Travis Hunter": "WR",  # Two-way player, more valuable as WR in dynasty
    }
    for name, override_pos in POSITION_OVERRIDES.items():
        cn = clean_name(name)
        if cn in position_map:
            position_map[cn] = override_pos


    teams.sort(key=lambda t: t["name"])

    roster_data = {
        "leagueId": league_id,
        "leagueName": league_name,
        "teams": teams,
        "positions": position_map,
        "playerIds": player_id_map,
        "idToPlayer": id_to_player,
        "scoringSettings": scoring_settings,
        "rosterPositions": roster_positions,
        "leagueSettings": league_settings,
    }

    # ── Fetch rolling 1-year trades from Sleeper API ──
    trades = []
    trade_window_days = max(30, _env_int("SLEEPER_TRADE_HISTORY_DAYS", 365))
    trade_cutoff_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=trade_window_days)
    trade_cutoff_ms = int(trade_cutoff_dt.timestamp() * 1000)
    try:
        def _normalize_tx_ts(v):
            ts = _safe_int(v)
            if not isinstance(ts, int) or ts <= 0:
                return 0
            # Sleeper timestamps are typically ms; normalize defensive second-based values.
            if ts < 1_000_000_000_000:
                ts *= 1000
            return ts

        def _league_chain_ids(start_league_id, max_depth=4):
            out = []
            seen = set()
            cur = str(start_league_id or "").strip()
            while cur and cur not in seen and len(out) < max_depth:
                seen.add(cur)
                out.append(cur)
                try:
                    li_resp = _req.get(
                        f"https://api.sleeper.app/v1/league/{cur}",
                        timeout=10
                    )
                    if li_resp.status_code != 200:
                        break
                    li_json = li_resp.json()
                    li = li_json if isinstance(li_json, dict) else {}
                except Exception:
                    break
                prev_id = li.get("previous_league_id") or li.get("previous_league")
                if not prev_id:
                    break
                cur = str(prev_id).strip()
            return out

        def _league_rid_to_name(target_league_id):
            rid_to_name = {}
            try:
                l_rosters_resp = _req.get(
                    f"https://api.sleeper.app/v1/league/{target_league_id}/rosters",
                    timeout=12
                )
                l_users_resp = _req.get(
                    f"https://api.sleeper.app/v1/league/{target_league_id}/users",
                    timeout=12
                )
                if l_rosters_resp.status_code != 200:
                    return rid_to_name
                l_rosters_json = l_rosters_resp.json()
                l_rosters = l_rosters_json if isinstance(l_rosters_json, list) else []
                l_user_map = {}
                if l_users_resp.status_code == 200:
                    l_users_json = l_users_resp.json()
                    l_users = l_users_json if isinstance(l_users_json, list) else []
                    for u in l_users:
                        uid = u.get("user_id")
                        name = (u.get("metadata", {}).get("team_name")
                                or u.get("display_name")
                                or f"Team {uid}")
                        l_user_map[uid] = name
                for r in l_rosters:
                    rid = r.get("roster_id")
                    oid = r.get("owner_id", "")
                    tname = l_user_map.get(oid, f"Team {rid}")
                    rid_to_name[rid] = tname
                    rid_int = _safe_int(rid)
                    if isinstance(rid_int, int):
                        rid_to_name[rid_int] = tname
                        rid_to_name[str(rid_int)] = tname
            except Exception:
                return rid_to_name
            return rid_to_name

        def _append_trade_side_item(side_map, rid, label):
            """Append asset label under string/int roster-id keys without duplicating entries."""
            if not label:
                return
            keys = []
            if rid is not None:
                keys.append(rid)
            rid_int = _safe_int(rid)
            if isinstance(rid_int, int):
                keys.extend([rid_int, str(rid_int)])
            for k in keys:
                arr = side_map.setdefault(k, [])
                if label not in arr:
                    arr.append(label)

        def _format_trade_pick_label(pick, rid_to_name):
            """Return canonical pick label (slot/tier + from team) for trade-history valuation."""
            season = _safe_int(pick.get("season"))
            round_num = _safe_int(pick.get("round"))
            origin_rid = _safe_int(pick.get("roster_id") or pick.get("origin_roster_id"))

            from_team = None
            if isinstance(origin_rid, int):
                from_team = (
                    rid_to_name.get(origin_rid)
                    or rid_to_name.get(str(origin_rid))
                    or roster_name_by_id.get(origin_rid)
                    or f"Team {origin_rid}"
                )

            base_label = None
            if isinstance(season, int) and isinstance(round_num, int) and round_num > 0:
                ident = pick_identity.get((season, round_num, origin_rid)) if isinstance(origin_rid, int) else None
                if isinstance(ident, dict):
                    base_label = str(ident.get("baseLabel") or "").strip() or None
                    if not from_team:
                        from_team = str(ident.get("fromTeam") or "").strip() or None

                if not base_label:
                    slot_num = (
                        _safe_int(draft_slot_by_origin.get((season, origin_rid)))
                        if isinstance(origin_rid, int)
                        else None
                    )
                    if season >= current_year + 1:
                        tier_label = _slot_to_tier_label(slot_num)
                        base_label = f"{season} {tier_label} {round_num}{_round_suffix(round_num)}"
                    elif isinstance(slot_num, int) and slot_num > 0:
                        base_label = f"{season} {round_num}.{str(slot_num).zfill(2)}"
                    else:
                        base_label = f"{season} {round_num}{_round_suffix(round_num)}"

            if not base_label:
                season_txt = str(pick.get("season", "")).strip()
                round_txt = str(pick.get("round", "?")).strip()
                base_label = f"{season_txt} Round {round_txt}".strip()

            return f"{base_label} (from {from_team})" if from_team else base_label

        seen_tx_ids = set()
        league_ids = _league_chain_ids(league_id, max_depth=4)
        week_range = range(0, 19)

        for target_league_id in league_ids:
            rid_to_name = _league_rid_to_name(target_league_id)
            for week in week_range:
                try:
                    tx_resp = _req.get(
                        f"https://api.sleeper.app/v1/league/{target_league_id}/transactions/{week}",
                        timeout=10
                    )
                    if tx_resp.status_code != 200:
                        continue
                    txns = tx_resp.json()
                    if not isinstance(txns, list):
                        continue
                    for tx in txns:
                        if tx.get("type") != "trade" or tx.get("status") != "complete":
                            continue

                        created = _normalize_tx_ts(tx.get("created", 0))
                        if created and created < trade_cutoff_ms:
                            continue

                        txid_raw = tx.get("transaction_id") or tx.get("transactionId")
                        if txid_raw is None:
                            txid = f"{target_league_id}:{week}:{created}:{','.join(sorted(str(r) for r in (tx.get('roster_ids') or [])))}"
                        else:
                            txid = str(txid_raw)
                        if txid in seen_tx_ids:
                            continue
                        seen_tx_ids.add(txid)

                        roster_ids = tx.get("roster_ids", [])
                        adds = tx.get("adds") or {}
                        drops = tx.get("drops") or {}
                        draft_picks = tx.get("draft_picks") or []

                        team_got = {}
                        team_gave = {}
                        for pid, rid in adds.items():
                            p = all_nfl.get(pid)
                            pname = p.get("full_name", pid) if p else pid
                            _append_trade_side_item(team_got, rid, clean_name(pname))
                        for pid, rid in drops.items():
                            p = all_nfl.get(pid)
                            pname = p.get("full_name", pid) if p else pid
                            _append_trade_side_item(team_gave, rid, clean_name(pname))

                        for pick in draft_picks:
                            owner_id = pick.get("owner_id")
                            prev_owner = pick.get("previous_owner_id")
                            pick_label = _format_trade_pick_label(pick, rid_to_name)
                            if owner_id:
                                _append_trade_side_item(team_got, owner_id, pick_label)
                            if prev_owner:
                                _append_trade_side_item(team_gave, prev_owner, pick_label)

                        sides = []
                        for rid in roster_ids:
                            rid_key = rid if rid in rid_to_name else _safe_int(rid)
                            team_name = rid_to_name.get(rid_key, rid_to_name.get(str(rid), f"Team {rid}"))
                            got = team_got.get(rid, [])
                            gave = team_gave.get(rid, [])
                            sides.append({
                                "team": team_name,
                                "rosterId": rid,
                                "got": got,
                                "gave": gave,
                            })

                        if sides:
                            trades.append({
                                "leagueId": str(target_league_id),
                                "week": week,
                                "timestamp": created,
                                "sides": sides,
                            })
                except Exception:
                    continue

        trades.sort(key=lambda t: -int(t.get("timestamp", 0) or 0))
        if trades:
            print(
                f"  [Sleeper] Found {len(trades)} completed trades "
                f"in rolling {trade_window_days}-day window "
                f"(cutoff {trade_cutoff_dt.date().isoformat()})"
            )
        else:
            print(
                f"  [Sleeper] No completed trades found in rolling {trade_window_days}-day window "
                f"(cutoff {trade_cutoff_dt.date().isoformat()})"
            )
    except Exception as e:
        if DEBUG:
            print(f"  [Sleeper] Trade fetch error: {e}")

    roster_data["trades"] = trades
    roster_data["tradeWindowDays"] = int(trade_window_days)
    roster_data["tradeWindowStart"] = trade_cutoff_dt.isoformat()
    roster_data["tradeWindowCutoffMs"] = int(trade_cutoff_ms)

    unique_names = sorted(set(all_names))
    print(f"  [Sleeper] {len(unique_names)} unique rostered players across {len(rosters)} teams")
    return unique_names, roster_data


# ── Load Sleeper data ──
SLEEPER_PLAYERS = []
SLEEPER_ROSTER_DATA = {}
SLEEPER_ALL_NFL = {}

if SLEEPER_LEAGUE_ID:
    SLEEPER_PLAYERS, SLEEPER_ROSTER_DATA = fetch_sleeper_rosters(SLEEPER_LEAGUE_ID)
    if SLEEPER_PLAYERS:
        print(f"  Sample: {SLEEPER_PLAYERS[:5]}")
    else:
        print("  [Sleeper] No players found — falling back to players.txt")


# PLAYERS list (for console table only)
_players_file = os.path.join(SCRIPT_DIR, "players.txt")
if os.path.exists(_players_file):
    with open(_players_file, "r", encoding="utf-8") as _f:
        PLAYERS = [
            line.strip() for line in _f
            if line.strip() and not line.strip().startswith("#")
        ]
    if not PLAYERS:
        print("  [Warning] players.txt is empty — using defaults")
        PLAYERS = _DEFAULT_PLAYERS
    else:
        print(f"Loaded {len(PLAYERS)} players from players.txt (console table)")
else:
    PLAYERS = _DEFAULT_PLAYERS
    print(f"No players.txt found — using {len(PLAYERS)} default players for console table")

ROOKIE_MUST_HAVE_NAMES = load_rookie_must_have(ROOKIE_MUST_HAVE_FILE)
if ROOKIE_MUST_HAVE_NAMES:
    print(f"Loaded {len(ROOKIE_MUST_HAVE_NAMES)} must-have rookies from {os.path.basename(ROOKIE_MUST_HAVE_FILE)}")

SITES = {
    "KTC":          True,
    "FantasyCalc":  False,
    "DynastyDaddy": False,
    "FantasyPros":  False,
    "DraftSharks":  False,
    "Yahoo":        False,
    "DynastyNerds": False,
    "DLF":          False,
    "IDPTradeCalc": True,
    "Flock":        False,
    # IDP-specific sites — disabled in scope reduction
    "PFF_IDP":          False,
    "DraftSharks_IDP":  False,
    "FantasyPros_IDP":  False,
}

SUPERFLEX = True
TEP = True
DEBUG     = True

# Normalize PLAYERS list at startup
PLAYERS = [clean_name(p) for p in PLAYERS]


def _detect_proxy() -> dict | None:
    """Detect HTTP(S) proxy from environment for Playwright browser launch.

    Returns a dict suitable for ``playwright.chromium.launch(proxy=...)``
    or ``None`` when no proxy is configured.  Handles the ``user:pass@host:port``
    format that container/CI egress proxies typically use.
    """
    from urllib.parse import urlparse as _urlparse

    raw = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""
    if not raw:
        return None
    parsed = _urlparse(raw)
    if not parsed.hostname:
        return None
    proxy: dict = {"server": f"http://{parsed.hostname}:{parsed.port or 3128}"}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


_PLAYWRIGHT_PROXY: dict | None = _detect_proxy()


async def safe_goto(page, urls, label, wait_ms=3000):
    """Navigate to the first working URL from a list.

    Returns a dict with keys:
      ok       – True if the page loaded with status < 400
      status   – HTTP status code or None
      blocker  – short string describing the failure mode, or None
    Legacy callers that check ``if await safe_goto(...)`` still work
    because the dict is truthy when ok=True.
    """
    if isinstance(urls, str):
        urls = [urls]
    last_blocker = None
    last_status = None
    for url in urls:
        try:
            resp = await page.goto(url, timeout=25000, wait_until="domcontentloaded")
            last_status = resp.status if resp else None
            if resp and resp.status < 400:
                await page.wait_for_timeout(wait_ms)
                if DEBUG:
                    print(f"  [{label}] Loaded {url} (status {resp.status})")
                return {"ok": True, "status": resp.status, "blocker": None}
            # Diagnose specific failure modes
            body_snippet = ""
            try:
                body_snippet = (await page.inner_text("body"))[:300]
            except Exception:
                pass
            if resp and resp.status == 503:
                if "TLS_error" in body_snippet or "TLSV1" in body_snippet:
                    last_blocker = "proxy_tls_incompatible"
                    print(f"  [{label}] 503 — proxy TLS handshake failure (site requires newer TLS)")
                elif "cloudflare" in body_snippet.lower() or "just a moment" in body_snippet.lower():
                    last_blocker = "cloudflare_challenge"
                    print(f"  [{label}] 503 — Cloudflare challenge page")
                else:
                    last_blocker = f"http_{resp.status}"
                    print(f"  [{label}] 503 — {body_snippet[:80]}")
            elif resp and resp.status == 403:
                last_blocker = "http_403_forbidden"
                print(f"  [{label}] 403 Forbidden — {url}")
            elif resp and resp.status >= 400:
                last_blocker = f"http_{resp.status}"
                if DEBUG:
                    print(f"  [{label}] Status {resp.status} — {url}")
            else:
                last_blocker = "no_response"
        except Exception as e:
            err_str = str(e)
            if "Timeout" in err_str:
                last_blocker = "timeout"
            elif "ERR_CERT" in err_str:
                last_blocker = "tls_cert_error"
            elif "ERR_NAME" in err_str or "ERR_FAILED" in err_str:
                last_blocker = "dns_or_network"
            else:
                last_blocker = "navigation_exception"
            if DEBUG:
                print(f"  [{label}] Failed {url}: {e}")
    # Return a falsy-like object that still carries diagnostic info
    return _GotoResult(False, last_status, last_blocker)


class _GotoResult:
    """Result of safe_goto that is falsy when ok=False but carries metadata."""
    __slots__ = ("ok", "status", "blocker")

    def __init__(self, ok, status, blocker):
        self.ok = ok
        self.status = status
        self.blocker = blocker

    def __bool__(self):
        return bool(self.ok)

    def __getitem__(self, key):
        return getattr(self, key)


async def extract_tables(page, label):
    """Scrape all <table> elements, return name->value dict."""
    name_map = {}
    tables = await page.query_selector_all("table")
    if DEBUG:
        print(f"  [{label}] {len(tables)} table(s) on page")

    for table in tables:
        rows = await table.query_selector_all("tr")
        if not rows:
            continue

        header_cells = await rows[0].query_selector_all("th, td")
        headers = [(await c.inner_text()).strip().lower() for c in header_cells]
        if DEBUG:
            print(f"  [{label}] Table headers: {headers}")

        name_col = -1
        for i, h in enumerate(headers):
            if any(k in h for k in ["player", "name"]):
                name_col = i
                break

        val_col = -1
        if SUPERFLEX:
            for i, h in enumerate(headers):
                if any(k in h for k in ["sf value", "sf", "2qb", "superflex"]):
                    val_col = i
                    break
        if val_col == -1:
            for i, h in enumerate(headers):
                if any(k in h for k in ["te prem", "ppr", "value", "val", "1qb"]):
                    if i != name_col:
                        val_col = i
                        break

        for row in rows[1:]:
            cells = await row.query_selector_all("td")
            if not cells:
                continue
            texts = [(await c.inner_text()).strip() for c in cells]

            if name_col != -1 and val_col != -1 and name_col < len(texts) and val_col < len(texts):
                nm = texts[name_col]
                vt = texts[val_col].replace(",", "")
            elif name_col != -1 and val_col == -1:
                # No identified value column — use player name + rightmost number
                # But only if the table has enough columns to have real values (skip rank-only tables)
                if len(headers) <= 3:
                    break  # Skip tables like ['rk', 'player', 'pos.'] — no trade values
                nm = texts[name_col] if name_col < len(texts) else ""
                vt = ""
                for t in reversed(texts):
                    try:
                        float(t.replace(",", ""))
                        vt = t.replace(",", "")
                        break
                    except ValueError:
                        pass
                if not vt:
                    continue
            else:
                nm = next((t for t in texts if re.search(r"[A-Za-z]{3}", t) and len(t) > 4
                           and not re.match(r"^\d+\.?\d*$", t)), "")
                vt = ""
                for t in reversed(texts):
                    try:
                        float(t.replace(",", ""))
                        vt = t.replace(",", "")
                        break
                    except ValueError:
                        pass

            if not nm or len(nm) < 3 or re.match(r"^\d+\.?\d*$", nm):
                continue
            try:
                val = float(vt)
                if val > 0:
                    name_map[clean_name(nm)] = val
            except ValueError:
                pass

    return name_map

async def page_dump(page, label, limit=2500):
    """Dump first N chars of page body text for debugging."""
    try:
        text = await page.inner_text("body")
        print(f"\n  [{label} DUMP]\n{text[:limit]}\n")
    except Exception as e:
        print(f"  [{label}] Dump failed: {e}")


# ─────────────────────────────────────────
# FantasyCalc — JSON API, TEP + SF
# ─────────────────────────────────────────
@retry(max_attempts=3, delay=2, exceptions=(requests.RequestException,))
async def scrape_ktc(page, players):
    results = {p: None for p in players}
    cached = get_cached("KTC")
    if cached:
        match_all(players, cached, results, site_key="KTC")
        return results
    try:
        sf  = "true" if SUPERFLEX else "false"
        url = f"https://keeptradecut.com/dynasty-rankings?sf={sf}&tep=2&filters=QB|WR|RB|TE|RDP"

        # ── Strategy 1: Intercept KTC API responses ──
        api_data = {}
        api_received = asyncio.Event()

        async def handle_response(response):
            try:
                rurl = response.url
                if response.status != 200:
                    return
                hostname = urlparse(rurl).hostname or ""
                if "keeptradecut" not in hostname:
                    return
                ct = response.headers.get("content-type", "")
                if "json" in ct or "javascript" in ct:
                    try:
                        body = await response.json()
                        api_data[rurl] = body
                        api_received.set()
                        if DEBUG:
                            print(f"  [KTC] Intercepted API: {rurl[:80]}")
                    except Exception:
                        pass
            except Exception:
                pass

        page.on("response", handle_response)

        goto_result = await safe_goto(page, url, "KTC", wait_ms=5000)
        if not goto_result:
            blocker = getattr(goto_result, "blocker", None) or "unknown"
            status = getattr(goto_result, "status", None)
            print(f"  [KTC] Page load failed — blocker={blocker}, status={status}")
            # Store blocker for source-level reporting
            global _KTC_BLOCKER
            _KTC_BLOCKER = blocker
            return results

        try:
            await page.wait_for_selector(".one-player, [class*='player']", timeout=10000)
        except Exception:
            pass

        # Wait for API data or timeout
        try:
            await asyncio.wait_for(api_received.wait(), timeout=8.0)
        except asyncio.TimeoutError:
            if DEBUG:
                print("  [KTC] API intercept timed out")

        await page.wait_for_timeout(3000)

        name_map = {}

        # Parse intercepted API data
        if DEBUG and api_data:
            for api_url, body in api_data.items():
                btype = type(body).__name__
                blen = len(body) if isinstance(body, (list, dict)) else 0
                print(f"  [KTC] API data: {api_url[:60]} → type={btype}, len={blen}")
                if isinstance(body, list) and len(body) > 0 and isinstance(body[0], dict):
                    print(f"  [KTC] API item[0] keys: {list(body[0].keys())[:10]}")

        for api_url, body in api_data.items():
            if isinstance(body, list) and len(body) > 10:
                for item in body:
                    if not isinstance(item, dict):
                        continue
                    pname = item.get("playerName") or item.get("player_name") or item.get("name")
                    if not pname:
                        continue
                    # Try SF value fields first (multiple possible structures)
                    val = None
                    if SUPERFLEX:
                        sf_vals = item.get("superflexValues")
                        if isinstance(sf_vals, dict):
                            val = sf_vals.get("value")
                        if val is None:
                            # KTC sometimes nests differently
                            sf_vals2 = item.get("superflexValue")
                            if isinstance(sf_vals2, dict):
                                val = sf_vals2.get("value")
                            elif sf_vals2 is not None:
                                val = sf_vals2
                        if val is None:
                            for k in ["sfValue", "sf_value", "sf_trade_value",
                                       "superflex_value", "tradeValueSuperFlex"]:
                                val = item.get(k)
                                if val is not None:
                                    break
                    if val is None:
                        val = item.get("value")
                    if val is not None:
                        try:
                            name_map[clean_name(pname)] = int(float(val))
                        except (ValueError, TypeError):
                            pass
                if name_map and DEBUG:
                    sf_label = "SF API" if SUPERFLEX else "1QB API"
                    print(f"  [KTC] Parsed {len(name_map)} players from API ({sf_label}): {api_url[:60]}")
                    # Show first item structure for debugging
                    if body and isinstance(body, list) and len(body) > 0:
                        sample = body[0]
                        keys = list(sample.keys()) if isinstance(sample, dict) else []
                        print(f"  [KTC] API item keys: {keys}")
                        sf_val = sample.get("superflexValues") if isinstance(sample, dict) else None
                        plain_val = sample.get("value") if isinstance(sample, dict) else None
                        pn = sample.get("playerName", "?") if isinstance(sample, dict) else "?"
                        print(f"  [KTC] Sample: {pn} → value={plain_val}, superflexValues={sf_val}")

        # ── Strategy 2: DOM scrape (reads rendered values after JS) ──
        if not name_map:
            if DEBUG:
                print("  [KTC] No API data — trying DOM scrape of rendered values")

            # KTC renders values in the DOM after client JS runs
            dom_data = await page.evaluate("""() => {
                const results = {};
                // Try reading from inline playersArray (current KTC format as of 2026-03)
                if (typeof playersArray !== 'undefined' && Array.isArray(playersArray)) {
                    for (const p of playersArray) {
                        const name = p.playerName || p.name;
                        const sfVals = p.superflexValues;
                        const val = (sfVals && sfVals.value) || p.superflexValue || p.value;
                        if (name && val) results[name] = parseInt(val);
                    }
                }
                if (Object.keys(results).length > 10) return results;
                // Try reading from Next.js/React state (legacy format)
                const scripts = document.querySelectorAll('script[type="application/json"], script#__NEXT_DATA__');
                for (const s of scripts) {
                    try {
                        const data = JSON.parse(s.textContent);
                        const players = data?.props?.pageProps?.players || data?.props?.pageProps?.rankings || [];
                        if (Array.isArray(players) && players.length > 10) {
                            for (const p of players) {
                                const name = p.playerName || p.name;
                                const sfVals = p.superflexValues;
                                const val = (sfVals && sfVals.value) || p.superflexValue || p.value;
                                if (name && val) results[name] = parseInt(val);
                            }
                        }
                    } catch(e) {}
                }
                // Fallback: read from visible DOM elements
                if (Object.keys(results).length === 0) {
                    const rows = document.querySelectorAll('.one-player, [class*="rankings-page--item"], [class*="player-row"]');
                    for (const row of rows) {
                        const nameEl = row.querySelector('.player-name, [class*="player-name"], a[href*="/dynasty/player"]');
                        const valEl = row.querySelector('.player-value, [class*="value"]');
                        if (nameEl && valEl) {
                            const name = nameEl.textContent.trim();
                            const val = parseInt(valEl.textContent.trim().replace(/,/g, ''));
                            if (name && !isNaN(val)) results[name] = val;
                        }
                    }
                }
                return results;
            }""")

            if dom_data and len(dom_data) > 10:
                for nm, val in dom_data.items():
                    name_map[clean_name(nm)] = int(val)
                if DEBUG:
                    print(f"  [KTC] DOM scrape found {len(name_map)} players")

        # ── Strategy 3: Full page source parsing ──
        if not name_map:
            content = await page.content()

            # Try inline playersArray (current KTC format as of 2026-03)
            pa_match = re.search(
                r'var\s+playersArray\s*=\s*(\[.*?\]);\s*(?:var\s|\n)',
                content, re.DOTALL,
            )
            if pa_match:
                try:
                    player_list = json.loads(pa_match.group(1))
                    for item in player_list:
                        pname = item.get("playerName")
                        if not pname:
                            continue
                        val = None
                        if SUPERFLEX:
                            sf_vals = item.get("superflexValues")
                            if isinstance(sf_vals, dict):
                                val = sf_vals.get("value")
                            if val is None:
                                sf_vals2 = item.get("superflexValue")
                                if isinstance(sf_vals2, dict):
                                    val = sf_vals2.get("value")
                                elif sf_vals2 is not None:
                                    val = sf_vals2
                        if val is None:
                            val = item.get("value")
                        if val is not None:
                            name_map[clean_name(pname)] = int(float(val))
                    if name_map and DEBUG:
                        print(f"  [KTC] playersArray parsed {len(name_map)} players")
                except Exception as e:
                    if DEBUG:
                        print(f"  [KTC] playersArray parse error: {e}")

            # Try __NEXT_DATA__ script (legacy format)
            next_match = re.search(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', content, re.DOTALL)
            if next_match:
                try:
                    next_data = json.loads(next_match.group(1))
                    player_list = (next_data.get("props", {}).get("pageProps", {}).get("players", []) or
                                   next_data.get("props", {}).get("pageProps", {}).get("rankings", []))
                    for item in player_list:
                        pname = item.get("playerName")
                        if not pname:
                            continue
                        val = None
                        if SUPERFLEX:
                            sf_vals = item.get("superflexValues")
                            if isinstance(sf_vals, dict):
                                val = sf_vals.get("value")
                        if val is None:
                            val = item.get("value")
                        if val is not None:
                            name_map[clean_name(pname)] = int(val)
                    if name_map and DEBUG:
                        print(f"  [KTC] __NEXT_DATA__ parsed {len(name_map)} players")
                except Exception as e:
                    if DEBUG:
                        print(f"  [KTC] __NEXT_DATA__ parse error: {e}")

            # ── Targeted SF extraction from page source ──
            # KTC page embeds player objects with nested superflexValues
            # Use .{0,2000}? to span nested braces between playerName and superflexValues
            if not name_map and SUPERFLEX:
                sf_pairs = re.findall(
                    r'"playerName"\s*:\s*"([^"]+)".{0,2000}?"superflexValues"\s*:\s*\{[^}]*?"value"\s*:\s*(\d+)',
                    content, re.DOTALL
                )
                if sf_pairs:
                    for nm, val in sf_pairs:
                        name_map[clean_name(nm)] = int(val)
                    if DEBUG:
                        ja = name_map.get("Josh Allen")
                        print(f"  [KTC] SF targeted regex found {len(name_map)} players. Josh Allen={ja}")

            # ── Try mapping API histories (playerID → superflex) to page names ──
            if not name_map and api_data:
                # Build playerID → SF value map from histories API
                id_to_sf = {}
                for api_url, body in api_data.items():
                    if isinstance(body, list):
                        for item in body:
                            if not isinstance(item, dict):
                                continue
                            pid = item.get("playerID")
                            sf_val = item.get("superflex")
                            if pid and sf_val is not None:
                                # superflex might be a list (history) or a number
                                if isinstance(sf_val, (int, float)):
                                    id_to_sf[pid] = int(sf_val)
                                elif isinstance(sf_val, list) and sf_val:
                                    # Take most recent value
                                    last = sf_val[-1]
                                    if isinstance(last, dict):
                                        id_to_sf[pid] = int(last.get("v", last.get("value", 0)))
                                    elif isinstance(last, (int, float)):
                                        id_to_sf[pid] = int(last)

                # Now find playerID → playerName mapping from page source
                id_name_pairs = re.findall(
                    r'"playerID"\s*:\s*(\d+).{0,500}?"playerName"\s*:\s*"([^"]+)"',
                    content, re.DOTALL
                )
                if not id_name_pairs:
                    # Try reverse order
                    id_name_pairs = re.findall(
                        r'"playerName"\s*:\s*"([^"]+)".{0,500}?"playerID"\s*:\s*(\d+)',
                        content, re.DOTALL
                    )
                    # Swap to (id, name) order
                    id_name_pairs = [(pid, nm) for nm, pid in id_name_pairs]

                if id_name_pairs and id_to_sf:
                    for pid_str, pname in id_name_pairs:
                        pid = int(pid_str)
                        if pid in id_to_sf:
                            name_map[clean_name(pname)] = id_to_sf[pid]
                    if name_map and DEBUG:
                        ja = name_map.get("Josh Allen")
                        print(f"  [KTC] API history + page ID mapping: {len(name_map)} players. Josh Allen={ja}")

            # ── Fallback: 1QB values if nothing else works ──
            if not name_map:
                pairs = re.findall(
                    r'"playerName"\s*:\s*"([^"]+)"[^}]*?"value"\s*:\s*(\d+)',
                    content
                )
                for nm, val in pairs:
                    name_map[clean_name(nm)] = int(val)
                if pairs and DEBUG:
                    sf_warn = " ⚠ (may be 1QB!)" if SUPERFLEX else ""
                    print(f"  [KTC] Plain regex fallback: {len(pairs)} players{sf_warn}")

        if not name_map and DEBUG:
            await page_dump(page, "KTC")
            # Also dump a snippet of page source to help diagnose
            content_snippet = content[:2000] if 'content' in dir() else ''
            # Check what script tags exist
            script_ids = re.findall(r'<script[^>]*id="([^"]*)"', content if 'content' in dir() else '')
            print(f"  [KTC] Script IDs in page: {script_ids[:10]}")
            # Check for superflexValues anywhere in content
            sf_count = content.count('superflexValues') if 'content' in dir() else 0
            sf_value_count = content.count('superflexValue') if 'content' in dir() else 0
            print(f"  [KTC] 'superflexValues' appears {sf_count}x, 'superflexValue' appears {sf_value_count}x in page")
        if DEBUG:
            # Sanity checks
            ja = name_map.get("Josh Allen", name_map.get("josh allen"))
            jl = name_map.get("Jeremiyah Love", name_map.get("jeremiyah love"))
            fm = name_map.get("Fernando Mendoza", name_map.get("fernando mendoza"))
            ah = name_map.get("Aidan Hutchinson", name_map.get("aidan hutchinson"))
            print(f"  [KTC] {len(name_map)} players. Josh Allen={ja}, Love={jl}, Mendoza={fm}, Hutchinson={ah}")
            print(f"  [KTC] Sample: {list(name_map.items())[:5]}")

        set_cache("KTC", name_map)
        match_all(players, name_map, results, site_key="KTC")

        # ── Always build playerID → name mapping for trade/waiver database ──
        global KTC_ID_TO_NAME
        if 'content' in dir() and content:
            id_name = re.findall(
                r'"playerID"\s*:\s*(\d+).{0,500}?"playerName"\s*:\s*"([^"]+)"',
                content, re.DOTALL
            )
            if not id_name:
                id_name = [(pid, nm) for nm, pid in re.findall(
                    r'"playerName"\s*:\s*"([^"]+)".{0,500}?"playerID"\s*:\s*(\d+)',
                    content, re.DOTALL
                )]
            for pid_str, pname in id_name:
                KTC_ID_TO_NAME[int(pid_str)] = clean_name(pname)
            if KTC_ID_TO_NAME:
                print(f"  [KTC] Stored {len(KTC_ID_TO_NAME)} playerID→name mappings for trade/waiver DB")
    except Exception as e:
        print(f"  [KTC error] {e}")
    return results


# ─────────────────────────────────────────
# KTC TRADE DATABASE — real dynasty trades from 140k+ leagues
# ─────────────────────────────────────────
@retry(max_attempts=2, delay=3)
async def scrape_ktc_trade_database(page):
    """Scrape crowdsourced trade data from KTC's trade database."""
    global KTC_CROWD_DATA
    trades = []
    sf = 1 if SUPERFLEX else 0
    tep = TEP if TEP else 0
    url = f"https://keeptradecut.com/dynasty/trade-database?sf={sf}&tep={tep}"
    print(f"  [KTC Trades] Fetching trade database...")

    try:
        api_data = []
        api_received = asyncio.Event()

        async def handle_response(response):
            try:
                rurl = response.url
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct and "javascript" not in ct:
                    return
                if "trade" in rurl.lower() and "keeptradecut" in rurl.lower():
                    body = await response.json()
                    if isinstance(body, list) and len(body) > 0:
                        api_data.extend(body)
                        print(f"  [KTC Trades] Intercepted API: {len(body)} items from {rurl[:80]}")
                        api_received.set()
            except Exception:
                pass

        page.on("response", handle_response)
        ok = await safe_goto(page, url, "KTC Trades", wait_ms=5000)
        if not ok:
            print("  [KTC Trades] Failed to load page")
            return trades

        try:
            await asyncio.wait_for(api_received.wait(), timeout=10)
        except asyncio.TimeoutError:
            print("  [KTC Trades] API intercept timed out")

        if api_data:
            # Debug: log first item structure
            if api_data and isinstance(api_data[0], dict):
                print(f"  [KTC Trades] Item keys: {list(api_data[0].keys())[:15]}")
                # Log first item sample
                sample = {k: str(v)[:80] for k, v in list(api_data[0].items())[:10]}
                print(f"  [KTC Trades] Sample item: {sample}")

            for item in api_data[:500]:
                trade = _parse_ktc_trade(item)
                if trade:
                    trades.append(trade)

            print(f"  [KTC Trades] Parsed {len(trades)} trades from {len(api_data)} API items")
        else:
            print("  [KTC Trades] No API data intercepted")

    except Exception as e:
        print(f"  [KTC Trades error] {e}")

    KTC_CROWD_DATA["trades"] = trades
    return trades


def _parse_ktc_literal(raw):
    """Parse KTC payload fields that may arrive as Python-literal strings."""
    if isinstance(raw, (dict, list, tuple, int, float, bool)) or raw is None:
        return raw
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return ""
    if text[0] not in "{[":
        return raw
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return raw


def _ktc_to_number(val, default=None):
    """Convert numeric-like strings to numbers."""
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        s = val.strip()
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        try:
            return float(s)
        except Exception:
            return default
    return default


def _ktc_to_int(val, default=""):
    n = _ktc_to_number(val, default=None)
    if n is None:
        return default
    return int(n)


def _ktc_to_flag(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        s = val.strip().lower()
        if s in {"1", "true", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(val)


def _ktc_tep_level(tep_raw, tep_flag=False):
    """Normalize KTC TEP config to a tier number (0, 1, 2, ...)."""
    lvl = _ktc_to_int(tep_raw, default=None)
    if isinstance(lvl, int):
        return lvl
    if isinstance(tep_raw, str):
        s = tep_raw.strip().lower()
        if "++" in s:
            return 2
        if "+" in s:
            return 1
    return 1 if tep_flag else 0


def _ktc_crowd_league_ok(settings):
    """True only for SF leagues with 10/12/14 teams and TE+ / TE++."""
    if not isinstance(settings, dict):
        return False
    if not settings.get("sf"):
        return False
    teams = settings.get("teams")
    if teams not in KTC_CROWD_ALLOWED_TEAMS:
        return False
    tep_level = settings.get("tepLevel")
    if not isinstance(tep_level, int):
        tep_level = _ktc_tep_level(settings.get("tepRaw", ""), settings.get("tep", False))
    return tep_level in KTC_CROWD_ALLOWED_TEP_LEVELS


def _extract_ktc_side_assets(side):
    """Extract player/pick assets from a KTC side payload."""
    side = _parse_ktc_literal(side)
    if isinstance(side, (list, tuple, set)):
        return list(side)
    if not isinstance(side, dict):
        return []

    for key in ["playerIds", "playerIDs", "players", "assets", "items"]:
        raw = _parse_ktc_literal(side.get(key))
        if isinstance(raw, (list, tuple, set)):
            return list(raw)
        if raw is not None and raw != "":
            return [raw]

    for key in ["playerId", "playerID", "id", "name"]:
        if side.get(key) is not None:
            return [side.get(key)]
    return []

def _parse_ktc_settings(raw_settings):
    settings = _parse_ktc_literal(raw_settings) or {}
    if not isinstance(settings, dict):
        return {}

    sf_raw = settings.get("sf", settings.get("superflex"))
    if sf_raw is None:
        qb_slots = settings.get("qBs", settings.get("qbs", settings.get("quarterbacks")))
        qb_slots_int = _ktc_to_int(qb_slots, default="")
        sf_raw = qb_slots_int >= 2 if qb_slots_int != "" else False

    tep_raw = settings.get("tep", settings.get("teBonus", settings.get("tePremium", 0)))
    tep_flag = _ktc_to_flag(tep_raw)
    tep_level = _ktc_tep_level(tep_raw, tep_flag)

    return {
        "sf": _ktc_to_flag(sf_raw),
        "tep": tep_flag,
        "tepLevel": tep_level,
        "tepRaw": tep_raw,
        "teams": _ktc_to_int(settings.get("teams", settings.get("numTeams")), default=""),
        "starters": _ktc_to_int(settings.get("starters", settings.get("numStarters")), default=""),
        "ppr": settings.get("ppr", settings.get("scoringFormat", "")),
    }


def _resolve_ktc_player(val):
    """Resolve a KTC trade item player reference to a readable name."""
    val = _parse_ktc_literal(val)

    if isinstance(val, str):
        raw = val.strip()
        if not raw:
            return None
        if re.fullmatch(r"\d+", raw):
            pid = int(raw)
            return KTC_ID_TO_NAME.get(pid, f"Player#{pid}")
        return clean_name(raw)

    if isinstance(val, (int, float)):
        pid = int(val)
        return KTC_ID_TO_NAME.get(pid, f"Player#{pid}")

    if isinstance(val, dict):
        name = val.get("playerName") or val.get("name") or val.get("player_name")
        if name:
            return clean_name(name)
        pid = val.get("playerID") or val.get("player_id") or val.get("id")
        if isinstance(pid, str) and re.fullmatch(r"\d+", pid.strip()):
            pid = int(pid.strip())
        if pid and isinstance(pid, (int, float)):
            pid = int(pid)
            return KTC_ID_TO_NAME.get(pid, f"Player#{pid}")
    return None


def _parse_ktc_trade(item):
    """Parse a KTC trade API item across known payload formats."""
    item = _parse_ktc_literal(item)
    if not isinstance(item, dict):
        return None

    settings = _parse_ktc_settings(item.get("settings") or item.get("leagueSettings") or {})
    if not _ktc_crowd_league_ok(settings):
        return None

    sides = []

    # Format 1: side arrays or side objects
    for a_key, b_key in [
        ("sideA", "sideB"),
        ("side1", "side2"),
        ("team1Players", "team2Players"),
        ("team1Assets", "team2Assets"),
        ("teamOne", "teamTwo"),
        ("team1", "team2"),
    ]:
        if a_key in item and b_key in item:
            side_a_assets = _extract_ktc_side_assets(item.get(a_key))
            side_b_assets = _extract_ktc_side_assets(item.get(b_key))
            side_a = [_resolve_ktc_player(p) for p in side_a_assets if p is not None]
            side_b = [_resolve_ktc_player(p) for p in side_b_assets if p is not None]
            side_a = [n for n in side_a if n]
            side_b = [n for n in side_b if n]
            if side_a and side_b:
                sides = [{"players": side_a}, {"players": side_b}]
                break

    # Format 2: nested sides list
    raw_sides = _parse_ktc_literal(item.get("sides"))
    if not sides and isinstance(raw_sides, list):
        for s in raw_sides:
            if not isinstance(s, dict):
                continue
            raw = _parse_ktc_literal(s.get("players") or s.get("assets") or s.get("items") or [])
            players = [_resolve_ktc_player(p) for p in raw if p]
            players = [n for n in players if n]
            if players:
                sides.append({"players": players})

    # Format 3: flat list + grouping metadata
    if not sides:
        for players_key in ["players", "assets", "items", "tradeItems"]:
            if players_key in item:
                raw = _parse_ktc_literal(item[players_key])
                if isinstance(raw, list) and len(raw) >= 2:
                    group_key = _parse_ktc_literal(item.get("groups") or item.get("sideGroups"))
                    if isinstance(group_key, list) and len(group_key) == len(raw):
                        by_group = {}
                        for p, g in zip(raw, group_key):
                            by_group.setdefault(g, []).append(p)
                        for g_players in by_group.values():
                            names = [_resolve_ktc_player(p) for p in g_players if p is not None]
                            names = [n for n in names if n]
                            if names:
                                sides.append({"players": names})

    if len(sides) < 2:
        return None

    return {
        "source": "ktc",
        "date": item.get("date", item.get("createdAt", item.get("created_at", ""))),
        "sides": sides,
        "settings": settings,
    }

# ─────────────────────────────────────────
# KTC WAIVER DATABASE — real dynasty waivers from 3000+ leagues
# ─────────────────────────────────────────
@retry(max_attempts=2, delay=3)
async def scrape_ktc_waiver_database(page):
    """Scrape crowdsourced waiver data from KTC's waiver database."""
    global KTC_CROWD_DATA
    waivers = []
    sf = 1 if SUPERFLEX else 0
    tep = TEP if TEP else 0
    url = f"https://keeptradecut.com/dynasty/waiver-database?sf={sf}&tep={tep}"
    print(f"  [KTC Waivers] Fetching waiver database...")

    try:
        api_data = []
        api_received = asyncio.Event()

        async def handle_response(response):
            try:
                rurl = response.url
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct and "javascript" not in ct:
                    return
                if "waiver" in rurl.lower() and "keeptradecut" in rurl.lower():
                    body = await response.json()
                    if isinstance(body, list) and len(body) > 0:
                        api_data.extend(body)
                        print(f"  [KTC Waivers] Intercepted API: {len(body)} items from {rurl[:80]}")
                        api_received.set()
            except Exception:
                pass

        page.on("response", handle_response)
        ok = await safe_goto(page, url, "KTC Waivers", wait_ms=5000)
        if not ok:
            print("  [KTC Waivers] Failed to load page")
            return waivers

        try:
            await asyncio.wait_for(api_received.wait(), timeout=10)
        except asyncio.TimeoutError:
            print("  [KTC Waivers] API intercept timed out")

        if api_data:
            # Debug first item
            if api_data and isinstance(api_data[0], dict):
                print(f"  [KTC Waivers] Item keys: {list(api_data[0].keys())[:15]}")
                sample = {k: str(v)[:80] for k, v in list(api_data[0].items())[:10]}
                print(f"  [KTC Waivers] Sample item: {sample}")

            for item in api_data[:500]:
                w = _parse_ktc_waiver(item)
                if w:
                    waivers.append(w)

            print(f"  [KTC Waivers] Parsed {len(waivers)} waivers from {len(api_data)} API items")
        else:
            print("  [KTC Waivers] No API data intercepted")

    except Exception as e:
        print(f"  [KTC Waivers error] {e}")

    KTC_CROWD_DATA["waivers"] = waivers
    return waivers


def _parse_ktc_waiver(item):
    """Parse a KTC waiver API item."""
    item = _parse_ktc_literal(item)
    if not isinstance(item, dict):
        return None

    settings = _parse_ktc_settings(item.get("settings") or item.get("leagueSettings") or {})
    if not _ktc_crowd_league_ok(settings):
        return None

    # Try various field names for added/dropped player
    added = None
    for k in [
        "addedPlayer", "playerAdded", "player", "added", "addPlayer",
        "addedPlayerId", "playerAddedId", "addPlayerId",
        "pickedUpPlayer", "pickedUpPlayerId", "pickedUp",
    ]:
        val = item.get(k)
        if val is not None:
            added = _resolve_ktc_player(val)
            if added:
                break

    dropped = None
    for k in [
        "droppedPlayer", "playerDropped", "dropped", "dropPlayer",
        "droppedPlayerId", "playerDroppedId", "dropPlayerId",
    ]:
        val = item.get(k)
        if val is not None:
            dropped = _resolve_ktc_player(val)
            if dropped:
                break

    if not added:
        return None

    bid = _ktc_to_number(
        item.get("winningBid", item.get("bid", item.get("faabBid", item.get("blindBid", 0)))),
        default=0,
    )
    if isinstance(bid, float) and bid.is_integer():
        bid = int(bid)

    bid_pct = item.get(
        "bidPct",
        item.get("winningBidPct", item.get("faabPct", item.get("bidPercentage", item.get("percentage", "")))),
    )

    return {
        "source": "ktc",
        "date": item.get("date", item.get("createdAt", item.get("created_at", ""))),
        "added": added,
        "dropped": dropped or "",
        "bid": bid if isinstance(bid, (int, float)) else 0,
        "bidPct": str(bid_pct) if bid_pct else "",
        "settings": settings,
    }

# ─────────────────────────────────────────
# DynastyDaddy — API intercept PRIMARY, DOM fallback
# ─────────────────────────────────────────
@retry(max_attempts=2, delay=3)
async def scrape_idptradecalc(page, players):
    results = {p: None for p in players}
    name_map = {}
    try:
        def _idptc_value_keys():
            if SUPERFLEX and TEP:
                return [
                    "value_sftep", "sfTepValue", "sf_tep_value",
                    "value_sf", "sfValue", "sf_value",
                    "value_tep", "tepValue", "tep_value",
                    "value_1qb", "value", "Value",
                ]
            if SUPERFLEX:
                return [
                    "value_sf", "sfValue", "sf_value",
                    "value_sftep", "sfTepValue", "sf_tep_value",
                    "value_1qb", "value", "Value",
                ]
            if TEP:
                return [
                    "value_tep", "tepValue", "tep_value",
                    "value_sftep", "sfTepValue", "sf_tep_value",
                    "value_1qb", "value", "Value",
                ]
            return [
                "value_1qb", "oneQbValue", "value",
                "value_sf", "sfValue", "sf_value",
                "value_tep", "tepValue", "tep_value",
                "Value",
            ]

        def _extract_idptc_name_map(data_obj):
            extracted = {}
            items = []
            if isinstance(data_obj, dict):
                for key in ["Sheet1", "players", "values", "data", "result"]:
                    if isinstance(data_obj.get(key), list):
                        items.extend(data_obj.get(key) or [])
                if not items:
                    for v in data_obj.values():
                        if isinstance(v, list):
                            items.extend(v)
            elif isinstance(data_obj, list):
                items = list(data_obj)

            if not items:
                return extracted

            key_order = _idptc_value_keys()
            for item in items:
                if not isinstance(item, dict):
                    continue
                nm = ""
                for nk in ["name", "playerName", "player", "Name", "player_name"]:
                    nm = str(item.get(nk, "")).strip()
                    if nm:
                        break
                if not nm or len(nm) < 2:
                    continue

                val = None
                for vk in key_order:
                    raw_val = item.get(vk)
                    if raw_val is None:
                        continue
                    try:
                        cand = float(raw_val)
                    except (ValueError, TypeError):
                        continue
                    if cand > 0:
                        val = cand
                        break
                if val is None:
                    continue

                cn = clean_name(nm)
                prev = extracted.get(cn)
                if prev is None or val > prev:
                    extracted[cn] = val
            return extracted

        api_data = {}
        api_received = asyncio.Event()

        async def handle_response(response):
            try:
                ct = response.headers.get("content-type", "")
                url = response.url
                if response.status != 200:
                    return
                if any(skip in url for skip in [
                    "googletagmanager", "googlesyndication", "doubleclick",
                    "usercentrics", "cmp.", "analytics", "pagead",
                    "adsbygoogle", "gstatic.com",
                ]):
                    return
                is_data = (
                    "googleusercontent.com/macros" in url or
                    "script.google" in url or
                    ("json" in ct and any(k in url for k in [
                        "values", "players", "data", ".json"
                    ]))
                )
                if is_data:
                    body = await response.text()
                    if len(body) > 500:
                        api_data[url] = body
                        api_received.set()
                        if DEBUG:
                            print(f"  [IDPTradeCalc] Intercepted: {url[:80]} ({len(body)} chars)")
            except Exception:
                pass

        page.on("response", handle_response)

        ok = await safe_goto(page, "https://idptradecalculator.com/", "IDPTradeCalc", wait_ms=5000)
        if not ok:
            return results

        try:
            await asyncio.wait_for(api_received.wait(), timeout=12.0)
        except asyncio.TimeoutError:
            if DEBUG:
                print("  [IDPTradeCalc] API intercept timed out")

        # Dismiss cookie consent overlay
        try:
            await page.evaluate("""
                () => {
                    const aside = document.getElementById('usercentrics-cmp-ui');
                    if (aside) aside.remove();
                    document.querySelectorAll('[id*="usercentrics"], [id*="cmp"]').forEach(el => {
                        if (el.tagName === 'ASIDE' || el.style?.zIndex > 100) {
                            el.remove();
                        }
                    });
                    document.querySelectorAll('aside, [role="dialog"]').forEach(el => {
                        const style = window.getComputedStyle(el);
                        if (style.position === 'fixed' || style.position === 'absolute') {
                            if (parseInt(style.zIndex) > 100) el.remove();
                        }
                    });
                }
            """)
            await page.wait_for_timeout(200)
            if DEBUG:
                print(f"  [IDPTradeCalc] Dismissed cookie consent overlay")
        except Exception:
            pass

        # Ensure toggles
        async def ensure_toggles_on():
            sf_checked = await page.evaluate(
                "document.getElementById('toggleButton').checked")
            tep_checked = await page.evaluate(
                "document.getElementById('toggleButtonTEP').checked")
            if DEBUG:
                print(f"  [IDPTradeCalc] Checkbox state: SF={sf_checked}, TEP={tep_checked}")

            changed = False
            if not sf_checked:
                await page.evaluate("document.getElementById('toggleButton').click()")
                await page.wait_for_timeout(400)
                changed = True

            if not tep_checked:
                await page.evaluate("document.getElementById('toggleButtonTEP').click()")
                await page.wait_for_timeout(400)
                changed = True

            if not changed:
                if DEBUG:
                    print(f"  [IDPTradeCalc] Both already checked — cycling OFF→ON to refresh")
                await page.evaluate("document.getElementById('toggleButton').click()")
                await page.wait_for_timeout(250)
                await page.evaluate("document.getElementById('toggleButtonTEP').click()")
                await page.wait_for_timeout(250)
                await page.evaluate("document.getElementById('toggleButtonTEP').click()")
                await page.wait_for_timeout(250)
                await page.evaluate("document.getElementById('toggleButton').click()")
                await page.wait_for_timeout(500)

            sf_final = await page.evaluate(
                "document.getElementById('toggleButton').checked")
            tep_final = await page.evaluate(
                "document.getElementById('toggleButtonTEP').checked")
            if DEBUG:
                print(f"  [IDPTradeCalc] Final state: SF={sf_final}, TEP={tep_final}")

            if not sf_final:
                await page.evaluate("""
                    () => {
                        document.getElementById('toggleButton').checked = true;
                        if (typeof toggleRankings === 'function') toggleRankings();
                    }
                """)
                await page.wait_for_timeout(300)
            if not tep_final:
                await page.evaluate("""
                    () => {
                        document.getElementById('toggleButtonTEP').checked = true;
                        if (typeof toggleTEP === 'function') toggleTEP();
                    }
                """)
                await page.wait_for_timeout(300)
            return True

        await ensure_toggles_on()

        # Wait for new data after toggles
        try:
            new_event = asyncio.Event()

            async def handle_reload(response):
                try:
                    if response.status == 200 and len(await response.text()) > 500:
                        url = response.url
                        if any(k in url for k in [
                            "googleusercontent.com/macros", "script.google",
                            "values", "players"
                        ]):
                            api_data[url] = await response.text()
                            new_event.set()
                except Exception:
                    pass

            page.on("response", handle_reload)
            await asyncio.wait_for(new_event.wait(), timeout=8.0)
            if DEBUG:
                print(f"  [IDPTradeCalc] New data received after toggle cycle")
        except asyncio.TimeoutError:
            if DEBUG:
                print(f"  [IDPTradeCalc] No new API data after toggle cycle")

        await page.wait_for_timeout(1000)

        # ── Parse intercepted API responses ──
        def response_priority(item):
            url, body = item
            if "googleusercontent.com/macros" in url:
                return (0, -len(body))
            if "script.google" in url:
                return (1, -len(body))
            return (2, -len(body))

        sorted_responses = sorted(api_data.items(), key=response_priority)

        for url, body in sorted_responses:
            if name_map:
                break

            if any(skip in url for skip in [
                "googletagmanager", "googlesyndication",
                "usercentrics", "cmp.", "analytics", "doubleclick"
            ]):
                continue

            for candidate in [body, body.strip()]:
                stripped = re.sub(r'^[a-zA-Z_$][\w$]*\s*\(\s*', '', candidate)
                stripped = re.sub(r'\s*\)\s*;?\s*$', '', stripped)
                json_start = stripped.find('{')
                json_start_arr = stripped.find('[')
                if json_start == -1 and json_start_arr == -1:
                    continue
                start = min(
                    json_start if json_start != -1 else float('inf'),
                    json_start_arr if json_start_arr != -1 else float('inf')
                )
                stripped = stripped[int(start):]

                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError:
                    try:
                        data = json.loads(candidate)
                    except json.JSONDecodeError:
                        continue

                items = []
                if isinstance(data, dict) and "Sheet1" in data:
                    items = data["Sheet1"]
                elif isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    for key in ["players", "values", "data", "result"]:
                        if key in data and isinstance(data[key], list):
                            items = data[key]
                            break
                    if not items:
                        for v in data.values():
                            if isinstance(v, list) and len(v) > 10:
                                items = v
                                break

                if not items:
                    continue

                if DEBUG and items:
                    sample = items[0] if isinstance(items[0], dict) else {}
                    print(f"  [IDPTradeCalc] Item keys: {list(sample.keys())[:10]}")
                parsed_map = _extract_idptc_name_map(items)
                if parsed_map:
                    name_map.update(parsed_map)

                if name_map and DEBUG:
                    print(f"  [IDPTradeCalc] Parsed {len(name_map)} players from {url[:60]}")
                if name_map:
                    break

        # Fallback: read script.js apiUrl directly and fetch payload via Playwright request client.
        # This avoids relying only on response interception, which can be flaky on some runs.
        if not name_map:
            try:
                script_url = await page.evaluate("""
                    () => {
                        const scripts = Array.from(document.querySelectorAll('script[src]'));
                        const hit = scripts.find(s => /script\\.js(?:\\?|$)/i.test(s.src || ''));
                        return hit ? hit.src : '';
                    }
                """)
                if script_url:
                    script_resp = await page.context.request.get(script_url, timeout=30000)
                    if script_resp.ok:
                        script_text = await script_resp.text()
                        m = re.search(r'const\\s+apiUrl\\s*=\\s*"([^"]+)"', script_text)
                        if m:
                            api_url = m.group(1).strip()
                            data_resp = await page.context.request.get(api_url, timeout=30000)
                            if data_resp.ok:
                                try:
                                    payload = await data_resp.json()
                                except Exception:
                                    payload = None
                                if payload is not None:
                                    parsed_map = _extract_idptc_name_map(payload)
                                    if parsed_map:
                                        name_map.update(parsed_map)
                                        if DEBUG:
                                            print(
                                                f"  [IDPTradeCalc] Direct API fallback loaded "
                                                f"{len(parsed_map)} players"
                                            )
            except Exception as e:
                if DEBUG:
                    print(f"  [IDPTradeCalc] Direct API fallback error: {e}")

        if not name_map and DEBUG:
            await page_dump(page, "IDPTradeCalc")

        if DEBUG:
            print(f"  [IDPTradeCalc] {len(name_map)} players. Sample: {list(name_map.items())[:3]}")

        match_all(players, name_map, results, site_key="IDPTradeCalc")

        # ── Bulk lookup via page JS ──
        if ok:
            try:
                bulk_data = await page.evaluate("""
                    () => {
                        const results = {};
                        const inputs = document.querySelectorAll('input[type="text"]');
                        for (const input of inputs) {
                            const key = Object.keys(input).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                            if (key) {
                                let fiber = input[key];
                                for (let i = 0; i < 20 && fiber; i++) {
                                    const props = fiber.memoizedProps || fiber.pendingProps || {};
                                    for (const val of Object.values(props)) {
                                        if (Array.isArray(val) && val.length > 50) {
                                            const sample = val[0];
                                            if (sample && typeof sample === 'object' && sample.name) {
                                                for (const item of val) {
                                                    if (item.name && (item.value_sftep || item.value_sf || item.value)) {
                                                        results[item.name] = item.value_sftep || item.value_sf || item.value;
                                                    }
                                                }
                                                if (Object.keys(results).length > 50) return results;
                                            }
                                        }
                                    }
                                    fiber = fiber.return;
                                }
                            }
                        }
                        for (const key of Object.keys(window)) {
                            try {
                                const val = window[key];
                                if (Array.isArray(val) && val.length > 50) {
                                    const sample = val[0];
                                    if (sample && typeof sample === 'object' && sample.name) {
                                        for (const item of val) {
                                            if (item.name && (item.value_sftep || item.value_sf || item.value)) {
                                                results[item.name] = item.value_sftep || item.value_sf || item.value;
                                            }
                                        }
                                        if (Object.keys(results).length > 50) return results;
                                    }
                                }
                            } catch(e) {}
                        }
                        return results;
                    }
                """)
                if bulk_data and len(bulk_data) > 50:
                    added = 0
                    for nm, val in bulk_data.items():
                        try:
                            v = float(val)
                            if v > 0:
                                cn = clean_name(nm.strip())
                                if cn not in name_map:
                                    name_map[cn] = v
                                    added += 1
                        except (ValueError, TypeError):
                            pass
                    if added > 0:
                        if DEBUG:
                            print(f"  [IDPTradeCalc] Bulk JS extract: {added} additional players")
                        # [FIX P0] Use .update() instead of overwriting
                        if "IDPTradeCalc" not in FULL_DATA:
                            FULL_DATA["IDPTradeCalc"] = {}
                        FULL_DATA["IDPTradeCalc"].update(name_map)
                        match_all(players, name_map, results)
                elif DEBUG:
                    print(f"  [IDPTradeCalc] Bulk JS extract: no data found")
            except Exception as e:
                if DEBUG:
                    print(f"  [IDPTradeCalc] Bulk JS extract error: {e}")

        # ── Interactive search box fallback ──
        # Build an adaptive candidate queue:
        # 1) missing rostered players
        # 2) high-signal cross-source players not yet found on IDPTradeCalc
        # This improves deep-tier coverage beyond stars while keeping runtime bounded.
        api_count = len(name_map)
        MAX_AUTOCOMPLETE = IDP_AUTOCOMPLETE_MAX
        if not IDP_AUTOCOMPLETE_ENABLE:
            if DEBUG:
                print(
                    f"  [IDPTradeCalc] Autocomplete fallback disabled "
                    f"(IDP_AUTOCOMPLETE_ENABLE=false). Keeping API-only values: {api_count}"
                )
            return results
        _rank_signal_sites = set()  # No rank-based sites in the two-source model
        _candidates = {}

        def _upsert_missing_candidate(raw_name, rostered=False, site_name="", raw_val=None):
            cn = clean_name(raw_name)
            if not cn or cn in name_map:
                return
            if results.get(cn) is not None:
                return
            slot = _candidates.setdefault(cn, {"rostered": False, "hits": set(), "signal": 0.0})
            if rostered:
                slot["rostered"] = True
            if site_name:
                slot["hits"].add(site_name)
                if isinstance(raw_val, (int, float)) and raw_val > 0:
                    # Rank sites: lower rank means stronger signal.
                    if site_name in _rank_signal_sites:
                        signal = max(0.0, 1200.0 - float(raw_val))
                    else:
                        # Value sites: normalize to a coarse 0..1200 signal bucket.
                        signal = min(1200.0, float(raw_val) / 8.0)
                    if signal > slot["signal"]:
                        slot["signal"] = signal

        for pname in SLEEPER_PLAYERS:
            _upsert_missing_candidate(pname, rostered=True)

        for site_name, site_map in FULL_DATA.items():
            if site_name == "IDPTradeCalc":
                continue
            for pname, val in site_map.items():
                _upsert_missing_candidate(pname, site_name=site_name, raw_val=val)

        # Score candidates by source value (highest-value players first).
        # This ensures the most important offensive players from KTC are
        # searched first, maximizing coverage within the timeout budget.
        scored = []
        for cn, meta in _candidates.items():
            score = float(meta.get("signal", 0.0))
            if meta.get("rostered"):
                score += 500.0  # modest boost for rostered players
            scored.append((cn, score))

        scored.sort(key=lambda x: (-x[1], x[0]))
        missing = [cn for cn, _ in scored[:MAX_AUTOCOMPLETE]]

        if DEBUG:
            rostered_in_queue = sum(1 for cn in missing if _candidates.get(cn, {}).get("rostered"))
            print(
                f"  [IDPTradeCalc] API got {api_count} players. "
                f"Searching {len(missing)} candidates "
                f"({rostered_in_queue} rostered, {len(missing) - rostered_in_queue} external)."
            )
        if missing and ok:
            if DEBUG:
                print(f"  [IDPTradeCalc] {len(missing)} players missing — batch searching via autocomplete")

            await ensure_toggles_on()
            await page.wait_for_timeout(500)

            found_count = 0
            for pi, player in enumerate(missing):
                if pi % 25 == 0 and pi > 0:
                    print(f"  [IDPTradeCalc] Progress: {pi}/{len(missing)} searched, {found_count} found")
                try:
                    input_box = await page.query_selector("#team1Name")
                    if not input_box:
                        for sel in ["input[type='text']", "input"]:
                            inputs = await page.query_selector_all(sel)
                            for inp in inputs:
                                if await inp.is_visible():
                                    input_box = inp
                                    break
                            if input_box:
                                break

                    if not input_box:
                        if DEBUG:
                            print(f"  [IDPTradeCalc] No input box found for search")
                        break

                    await input_box.evaluate("el => { el.focus(); el.click(); }")
                    await input_box.evaluate("el => el.value = ''")
                    await page.wait_for_timeout(100)
                    await page.keyboard.type(player, delay=15)
                    await page.wait_for_timeout(350)

                    body_text = await page.inner_text("body")
                    last_name = player.split()[-1]
                    pattern = re.compile(
                        rf'{re.escape(last_name)}\s*\((\d+)\)\s*-\s*\w+',
                        re.IGNORECASE
                    )
                    match = pattern.search(body_text)
                    if match:
                        val = float(match.group(1))
                        if player in players:
                            results[player] = val
                        name_map[player] = val
                        # [FIX P0] Use .update() pattern instead of overwriting
                        if "IDPTradeCalc" not in FULL_DATA:
                            FULL_DATA["IDPTradeCalc"] = {}
                        FULL_DATA["IDPTradeCalc"][player] = val
                        found_count += 1
                        if DEBUG and player in players:
                            print(f"  [IDPTradeCalc] {player} = {val}")

                    await input_box.evaluate("el => el.value = ''")
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(100)

                except Exception as e:
                    if DEBUG:
                        print(f"  [IDPTradeCalc] Search box error for {player}: {e}")

            print(f"  [IDPTradeCalc] Batch search complete: {found_count}/{len(missing)} found")

            try:
                clear_btn = await page.query_selector("text=Clear")
                if clear_btn and await clear_btn.is_visible():
                    await clear_btn.click()
                    await page.wait_for_timeout(200)
            except Exception:
                pass

    except Exception as e:
        print(f"  [IDPTradeCalc error] {e}")
    return results


# ─────────────────────────────────────────
# PFF IDP — scrape latest IDP dynasty article
# ─────────────────────────────────────────
@retry(max_attempts=2, delay=3)
def print_health_report():
    """Print a summary of data quality across all scraped sites."""
    print("\n" + "=" * 60)
    print("SCRAPE HEALTH REPORT")
    print("=" * 60)

    total_unique = set()
    site_counts = {}
    for site_name, site_map in FULL_DATA.items():
        non_zero = sum(1 for v in site_map.values()
                       if v is not None and isinstance(v, (int, float)) and v > 0)
        site_counts[site_name] = non_zero
        total_unique.update(site_map.keys())
        max_val = compute_max(site_map)
        print(f"  {site_name:20s}  {non_zero:5d} players  (max: {max_val:,.0f})")

    print(f"\n  {'Total unique names':20s}  {len(total_unique):5d}")

    # Coverage distribution
    player_coverage = {}
    for name in total_unique:
        count = sum(1 for site_map in FULL_DATA.values()
                    if name in site_map and site_map[name] is not None
                    and isinstance(site_map[name], (int, float)) and site_map[name] > 0)
        player_coverage[name] = count

    one_site = sum(1 for c in player_coverage.values() if c == 1)
    two_three = sum(1 for c in player_coverage.values() if 2 <= c <= 3)
    four_five = sum(1 for c in player_coverage.values() if 4 <= c <= 5)
    six_plus = sum(1 for c in player_coverage.values() if c >= 6)

    print(f"\n  Coverage distribution:")
    print(f"    1 site only:  {one_site:5d}  {'⚠' if one_site > 50 else '✓'}")
    print(f"    2-3 sites:    {two_three:5d}")
    print(f"    4-5 sites:    {four_five:5d}")
    print(f"    6+ sites:     {six_plus:5d}  ✓")

    # Flag players from PLAYERS list with low coverage
    if PLAYERS:
        print(f"\n  Console players with low coverage:")
        for player in PLAYERS:
            cov = player_coverage.get(player, 0)
            if cov == 0:
                print(f"    ✗ {player} — NOT FOUND on any site")
            elif cov == 1:
                site = next((s for s, m in FULL_DATA.items() if player in m), "?")
                print(f"    ⚠ {player} — found on {site} only")

    print("=" * 60 + "\n")


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────
async def run(progress_callback=None):
    global DLF_IMPORT_DEBUG
    run_started_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    async def _emit_progress(
        step,
        source=None,
        step_index=None,
        step_total=None,
        event=None,
        message=None,
        level="info",
        meta=None,
    ):
        _mark_source_event(
            source=source,
            event=event,
            message=message,
            level=level,
            meta=meta or {},
        )
        if not callable(progress_callback):
            return
        payload = {
            "step": step,
            "source": source,
            "step_index": step_index,
            "step_total": step_total,
            "event": event,
            "message": message,
            "level": level,
            "meta": meta or {},
        }
        try:
            maybe = progress_callback(payload)
            if inspect.isawaitable(maybe):
                await maybe
        except Exception:
            # Progress callbacks should never break scraping.
            pass

    source_timeout_default = _env_int("SCRAPER_SOURCE_TIMEOUT_DEFAULT", 300)
    source_timeouts = {
        "KTC": _env_int("SCRAPER_SOURCE_TIMEOUT_KTC", source_timeout_default),
        "DynastyDaddy": _env_int("SCRAPER_SOURCE_TIMEOUT_DYNASTYDADDY", source_timeout_default),
        "FantasyPros": _env_int("SCRAPER_SOURCE_TIMEOUT_FANTASYPROS", source_timeout_default),
        "DraftSharks": _env_int("SCRAPER_SOURCE_TIMEOUT_DRAFTSHARKS", max(360, source_timeout_default)),
        "Yahoo": _env_int("SCRAPER_SOURCE_TIMEOUT_YAHOO", source_timeout_default),
        "DynastyNerds": _env_int("SCRAPER_SOURCE_TIMEOUT_DYNASTYNERDS", max(360, source_timeout_default)),
        "IDPTradeCalc": _env_int("SCRAPER_SOURCE_TIMEOUT_IDPTRADECALC", max(480, source_timeout_default)),
        "PFF_IDP": _env_int("SCRAPER_SOURCE_TIMEOUT_PFF_IDP", source_timeout_default),
        "DraftSharks_IDP": _env_int("SCRAPER_SOURCE_TIMEOUT_DRAFTSHARKS_IDP", max(360, source_timeout_default)),
        "FantasyPros_IDP": _env_int("SCRAPER_SOURCE_TIMEOUT_FANTASYPROS_IDP", source_timeout_default),
        "Flock": _env_int("SCRAPER_SOURCE_TIMEOUT_FLOCK", max(420, source_timeout_default)),
        "KTC_TradeDB": _env_int("SCRAPER_SOURCE_TIMEOUT_KTC_TRADEDB", max(300, source_timeout_default)),
        "KTC_WaiverDB": _env_int("SCRAPER_SOURCE_TIMEOUT_KTC_WAIVERDB", max(300, source_timeout_default)),
        "FantasyCalc": _env_int("SCRAPER_SOURCE_TIMEOUT_FANTASYCALC", 90),
        "DLF_LocalCSV": _env_int("SCRAPER_SOURCE_TIMEOUT_DLF_LOCALCSV", 60),
    }
    source_enabled_map = {
        "FantasyCalc": bool(SITES.get("FantasyCalc")),
        "DLF_LocalCSV": bool(SITES.get("DLF")),
        "KTC": bool(SITES.get("KTC")),
        "DynastyDaddy": bool(SITES.get("DynastyDaddy")),
        "FantasyPros": bool(SITES.get("FantasyPros")),
        "DraftSharks": bool(SITES.get("DraftSharks")),
        "Yahoo": bool(SITES.get("Yahoo")),
        "DynastyNerds": bool(SITES.get("DynastyNerds")),
        "IDPTradeCalc": bool(SITES.get("IDPTradeCalc")),
        "PFF_IDP": bool(SITES.get("PFF_IDP")),
        "DraftSharks_IDP": bool(SITES.get("DraftSharks_IDP")),
        "FantasyPros_IDP": bool(SITES.get("FantasyPros_IDP")),
        "Flock": bool(SITES.get("Flock")),
        "KTC_TradeDB": bool(SITES.get("KTC")),
        "KTC_WaiverDB": bool(SITES.get("KTC")),
    }
    source_run_state = {}

    def _duration_sec(started_at, finished_at):
        if not started_at or not finished_at:
            return None
        try:
            st = datetime.datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            en = datetime.datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
            return max(0.0, round((en - st).total_seconds(), 2))
        except Exception:
            return None

    def _new_source_state(source_name, enabled_flag):
        timeout_sec = int(source_timeouts.get(source_name, source_timeout_default))
        return {
            "source": source_name,
            "enabled": bool(enabled_flag),
            "timeoutSec": timeout_sec,
            "state": "pending" if enabled_flag else "disabled",
            "startedAt": None,
            "finishedAt": None,
            "durationSec": None,
            "message": "",
            "error": None,
            "valueCount": 0,
            "meta": {},
        }

    for _src_name, _enabled in source_enabled_map.items():
        source_run_state[_src_name] = _new_source_state(_src_name, _enabled)

    def _mark_source_event(source=None, event=None, message=None, level="info", meta=None):
        src = str(source or "").strip()
        ev = str(event or "").strip()
        if not src or not ev.startswith("source_"):
            return
        if src not in source_run_state:
            source_run_state[src] = _new_source_state(src, True)
        row = source_run_state[src]
        if not row.get("enabled"):
            return
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        meta_obj = meta if isinstance(meta, dict) else {}
        if ev == "source_start":
            row["state"] = "running"
            row["startedAt"] = row.get("startedAt") or now_iso
            row["finishedAt"] = None
            row["durationSec"] = None
            row["error"] = None
        elif ev == "source_complete":
            row["state"] = "complete"
            row["finishedAt"] = now_iso
            row["durationSec"] = _duration_sec(row.get("startedAt"), now_iso)
            row["error"] = None
        elif ev == "source_partial":
            row["state"] = "partial"
            row["finishedAt"] = now_iso
            row["durationSec"] = _duration_sec(row.get("startedAt"), now_iso)
        elif ev == "source_failed":
            msg_l = str(message or "").lower()
            timed_out = ("timed out" in msg_l) or ("timeout" in msg_l)
            row["state"] = "timeout" if timed_out else "failed"
            row["finishedAt"] = now_iso
            row["durationSec"] = _duration_sec(row.get("startedAt"), now_iso)
            row["error"] = str(message or "").strip() or f"{src} failed"
        if "valueCount" in meta_obj:
            try:
                row["valueCount"] = int(meta_obj.get("valueCount") or 0)
            except Exception:
                pass
        if meta_obj:
            prior_meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
            prior_meta.update(meta_obj)
            row["meta"] = prior_meta
        if message:
            row["message"] = str(message)
        if level == "error" and not row.get("error"):
            row["error"] = str(message or f"{src} failed")

    enabled_browser_sites = [
        s for s in (
            "KTC", "DynastyDaddy", "FantasyPros", "DraftSharks", "Yahoo", "DynastyNerds",
            "IDPTradeCalc", "PFF_IDP", "DraftSharks_IDP", "FantasyPros_IDP"
        ) if SITES.get(s)
    ]
    browser_needed = any(SITES.get(s) for s in (
        "KTC", "DynastyDaddy", "FantasyPros", "DraftSharks", "Yahoo", "DynastyNerds",
        "IDPTradeCalc", "PFF_IDP", "DraftSharks_IDP", "FantasyPros_IDP"
    )) or SITES.get("Flock")
    planned_total_steps = (
        1  # bootstrap
        + (1 if SITES.get("FantasyCalc") else 0)
        + (1 if SITES.get("DLF") else 0)
        + (1 if browser_needed else 0)  # browser launch phase
        + len(enabled_browser_sites)
        + (1 if SITES.get("Flock") else 0)
        + (2 if SITES.get("KTC") else 0)  # trade + waiver db
        + 4  # health report + build payload + write json/js + export
    )
    progress_index = 0

    async def _phase(step, source=None, event="phase_start", message=None, level="info", meta=None):
        nonlocal progress_index
        progress_index += 1
        await _emit_progress(
            step=step,
            source=source,
            step_index=progress_index,
            step_total=planned_total_steps,
            event=event,
            message=message,
            level=level,
            meta=meta or {},
        )

    await _phase("bootstrap", "init", message="Scraper run starting")
    print(f"  [Paths] Output dir: {SCRIPT_DIR}")
    if SCRIPT_DIR != BASE_SCRIPT_DIR:
        print(f"  [Paths] Base script dir: {BASE_SCRIPT_DIR} (input anchor)")
    all_results = {player: {} for player in PLAYERS}

    # ── Browser sites ──
    browser_order = [
        ("KTC",          scrape_ktc),
        ("IDPTradeCalc", scrape_idptradecalc),
    ]

    # Parallel scraping — these sites can be scraped concurrently
    PARALLEL_SITES = {"KTC"}

    browser_needed = any(SITES.get(s) for s, _ in browser_order)

    if browser_needed:
        await _phase("browser", "launch", message="Launching browser context")
        print("Launching browser...")
        async with async_playwright() as pw:

            # ── Browser sites ──
            active_browser = [(s, fn) for s, fn in browser_order if SITES.get(s)]
            if active_browser:
                browser = await pw.chromium.launch(headless=True, proxy=_PLAYWRIGHT_PROXY)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                    ignore_https_errors=bool(_PLAYWRIGHT_PROXY),
                )

                # Block heavy resources for speed
                async def _block_heavy(route):
                    try:
                        if route.request.resource_type in ("image", "font", "media"):
                            await route.abort()
                        else:
                            await route.continue_()
                    except Exception:
                        pass
                await context.route("**/*", _block_heavy)

                # Run each browser site sequentially
                for site, scraper in active_browser:
                    await _phase("source_start", site, event="source_start", message=f"Scraping {site}")
                    print(f"  Scraping {site}...")
                    page = await context.new_page()
                    try:
                        timeout_sec = source_timeouts.get(site, source_timeout_default)
                        site_results = await asyncio.wait_for(scraper(page, PLAYERS), timeout=timeout_sec)
                        value_count = sum(
                            1 for v in (site_results or {}).values()
                            if isinstance(v, (int, float)) and v > 0
                        )
                        for p, v in site_results.items():
                            all_results[p][site] = v
                        await _emit_progress(
                            step="source_complete" if value_count > 0 else "source_partial",
                            source=site,
                            step_index=progress_index,
                            step_total=planned_total_steps,
                            event="source_complete" if value_count > 0 else "source_partial",
                            level="info" if value_count > 0 else "warning",
                            message=f"{site} completed ({value_count} mapped values)",
                            meta={"valueCount": value_count},
                        )
                    except asyncio.TimeoutError:
                        # Recover partial results from FULL_DATA (autocomplete
                        # writes directly there even when the outer timeout fires)
                        if "IDPTradeCalc" in FULL_DATA:
                            recovered = 0
                            for p, v in FULL_DATA["IDPTradeCalc"].items():
                                if p in all_results and v is not None:
                                    all_results[p]["IDPTradeCalc"] = v
                                    recovered += 1
                            print(f"  [IDPTradeCalc] Timeout after {source_timeouts.get(site, source_timeout_default)}s — recovered {recovered} values from partial autocomplete")
                        else:
                            print(f"  [IDPTradeCalc] Timeout after {source_timeouts.get(site, source_timeout_default)}s")
                        await _emit_progress(
                            step="source_failed",
                            source=site,
                            step_index=progress_index,
                            step_total=planned_total_steps,
                            event="source_failed",
                            level="error",
                            message=f"{site} timed out after {source_timeouts.get(site, source_timeout_default)}s",
                        )
                    except Exception as e:
                        await _emit_progress(
                            step="source_failed",
                            source=site,
                            step_index=progress_index,
                            step_total=planned_total_steps,
                            event="source_failed",
                            level="error",
                            message=f"{site} failed: {type(e).__name__}: {e}",
                        )
                        print(f"  [{site}] Unexpected error: {e}")
                    finally:
                        await page.close()

                # ── KTC Trade + Waiver Database scraping ──
                if SITES.get("KTC") and KTC_ID_TO_NAME:
                    try:
                        await _phase("source_start", "KTC_TradeDB", event="source_start", message="Scraping KTC trade database")
                        trade_page = await context.new_page()
                        await asyncio.wait_for(
                            scrape_ktc_trade_database(trade_page),
                            timeout=source_timeouts["KTC_TradeDB"],
                        )
                        trade_count = len(KTC_CROWD_DATA.get("trades", []) or [])
                        await _emit_progress(
                            step="source_complete" if trade_count > 0 else "source_partial",
                            source="KTC_TradeDB",
                            step_index=progress_index,
                            step_total=planned_total_steps,
                            event="source_complete" if trade_count > 0 else "source_partial",
                            level="info" if trade_count > 0 else "warning",
                            message=f"KTC trade database complete ({trade_count} trades)",
                            meta={"valueCount": trade_count},
                        )
                        await trade_page.close()
                    except asyncio.TimeoutError:
                        await _emit_progress(
                            step="source_failed",
                            source="KTC_TradeDB",
                            step_index=progress_index,
                            step_total=planned_total_steps,
                            event="source_failed",
                            level="error",
                            message=f"KTC trade DB timed out after {source_timeouts['KTC_TradeDB']}s",
                        )
                        print(f"  [KTC Trade DB error] Timeout after {source_timeouts['KTC_TradeDB']}s")
                    except Exception as e:
                        await _emit_progress(
                            step="source_failed",
                            source="KTC_TradeDB",
                            step_index=progress_index,
                            step_total=planned_total_steps,
                            event="source_failed",
                            level="error",
                            message=f"KTC trade DB failed: {type(e).__name__}: {e}",
                        )
                        print(f"  [KTC Trade DB error] {e}")
                    try:
                        await _phase("source_start", "KTC_WaiverDB", event="source_start", message="Scraping KTC waiver database")
                        waiver_page = await context.new_page()
                        await asyncio.wait_for(
                            scrape_ktc_waiver_database(waiver_page),
                            timeout=source_timeouts["KTC_WaiverDB"],
                        )
                        waiver_count = len(KTC_CROWD_DATA.get("waivers", []) or [])
                        await _emit_progress(
                            step="source_complete" if waiver_count > 0 else "source_partial",
                            source="KTC_WaiverDB",
                            step_index=progress_index,
                            step_total=planned_total_steps,
                            event="source_complete" if waiver_count > 0 else "source_partial",
                            level="info" if waiver_count > 0 else "warning",
                            message=f"KTC waiver database complete ({waiver_count} waivers)",
                            meta={"valueCount": waiver_count},
                        )
                        await waiver_page.close()
                    except asyncio.TimeoutError:
                        await _emit_progress(
                            step="source_failed",
                            source="KTC_WaiverDB",
                            step_index=progress_index,
                            step_total=planned_total_steps,
                            event="source_failed",
                            level="error",
                            message=f"KTC waiver DB timed out after {source_timeouts['KTC_WaiverDB']}s",
                        )
                        print(f"  [KTC Waiver DB error] Timeout after {source_timeouts['KTC_WaiverDB']}s")
                    except Exception as e:
                        await _emit_progress(
                            step="source_failed",
                            source="KTC_WaiverDB",
                            step_index=progress_index,
                            step_total=planned_total_steps,
                            event="source_failed",
                            level="error",
                            message=f"KTC waiver DB failed: {type(e).__name__}: {e}",
                        )
                        print(f"  [KTC Waiver DB error] {e}")
                elif SITES.get("KTC"):
                    print("  [KTC Crowd] Skipping trade/waiver DB — no playerID→name mapping available")
                    await _emit_progress(
                        step="source_partial",
                        source="KTC_TradeDB",
                        step_index=progress_index,
                        step_total=planned_total_steps,
                        event="source_partial",
                        level="warning",
                        message="KTC trade DB skipped — no playerID→name mapping available",
                        meta={"valueCount": 0, "skipReason": "missing_ktc_id_map"},
                    )
                    await _emit_progress(
                        step="source_partial",
                        source="KTC_WaiverDB",
                        step_index=progress_index,
                        step_total=planned_total_steps,
                        event="source_partial",
                        level="warning",
                        message="KTC waiver DB skipped — no playerID→name mapping available",
                        meta={"valueCount": 0, "skipReason": "missing_ktc_id_map"},
                    )

                await browser.close()

    def _count_site_values_from_results(site_name):
        if site_name == "DLF_LocalCSV":
            dlf_keys = ("DLF_SF", "DLF_IDP", "DLF_RSF", "DLF_RIDP")
            return sum(
                1
                for _player, row in all_results.items()
                for k in dlf_keys
                if isinstance((row or {}).get(k), (int, float)) and (row or {}).get(k) > 0
            )
        if site_name == "KTC_TradeDB":
            return len(KTC_CROWD_DATA.get("trades", []) or [])
        if site_name == "KTC_WaiverDB":
            return len(KTC_CROWD_DATA.get("waivers", []) or [])
        return sum(
            1 for _player, row in all_results.items()
            if isinstance((row or {}).get(site_name), (int, float)) and (row or {}).get(site_name) > 0
        )

    # Reconcile final per-source state after all source phases complete.
    for _source_name, _state in source_run_state.items():
        if not _state.get("enabled"):
            _state["state"] = "disabled"
            continue
        _count = int(_state.get("valueCount") or 0)
        if _count <= 0:
            _count = _count_site_values_from_results(_source_name)
        _state["valueCount"] = int(_count)
        if _state.get("state") == "running":
            _state["state"] = "partial" if _count <= 0 else "complete"
            _state["finishedAt"] = _state.get("finishedAt") or datetime.datetime.now(datetime.timezone.utc).isoformat()
            _state["durationSec"] = _duration_sec(_state.get("startedAt"), _state.get("finishedAt"))
            if _count <= 0:
                _state["message"] = _state.get("message") or "source ended without mapped values"
        if _state.get("state") == "complete" and _count <= 0:
            _state["state"] = "partial"
            _state["message"] = _state.get("message") or "source completed with zero mapped values"

    enabled_sources = sorted([s for s, row in source_run_state.items() if row.get("enabled")])
    complete_sources = sorted([s for s, row in source_run_state.items() if row.get("enabled") and row.get("state") == "complete"])
    partial_sources = sorted([s for s, row in source_run_state.items() if row.get("enabled") and row.get("state") == "partial"])
    timeout_sources = sorted([s for s, row in source_run_state.items() if row.get("enabled") and row.get("state") == "timeout"])
    failed_sources = sorted([s for s, row in source_run_state.items() if row.get("enabled") and row.get("state") == "failed"])
    run_finished_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Inject KTC blocker diagnosis into source state if available
    if _KTC_BLOCKER and "KTC" in source_run_state:
        ktc_state = source_run_state["KTC"]
        ktc_state.setdefault("meta", {})["blocker"] = _KTC_BLOCKER
        if not ktc_state.get("error"):
            ktc_state["error"] = f"KTC blocked: {_KTC_BLOCKER}"

    source_run_summary = {
        "startedAt": run_started_at_iso,
        "finishedAt": run_finished_at_iso,
        "durationSec": _duration_sec(run_started_at_iso, run_finished_at_iso),
        "overallStatus": "partial" if (partial_sources or timeout_sources or failed_sources) else "complete",
        "partialRun": bool(partial_sources or timeout_sources or failed_sources),
        "enabledSources": enabled_sources,
        "completeSources": complete_sources,
        "partialSources": partial_sources,
        "timedOutSources": timeout_sources,
        "failedSources": failed_sources,
        "sourceTimeouts": {k: int(v) for k, v in source_timeouts.items()},
        "sources": source_run_state,
    }
    print(
        "  [Source Summary] "
        f"complete={len(complete_sources)}/{len(enabled_sources)} "
        f"partial={len(partial_sources)} timeout={len(timeout_sources)} failed={len(failed_sources)}"
    )

    # ── KTC Freshness Report ──
    ktc_row = source_run_state.get("KTC", {})
    ktc_count = int(ktc_row.get("valueCount") or 0)
    ktc_state_label = ktc_row.get("state", "unknown")
    ktc_blocker_label = (ktc_row.get("meta") or {}).get("blocker", "")
    if ktc_count > 0:
        print(f"  [KTC Status] FRESH — {ktc_count} players scraped")
    elif ktc_state_label == "disabled":
        print("  [KTC Status] DISABLED in config")
    elif ktc_blocker_label:
        print(f"  [KTC Status] BLOCKED — {ktc_blocker_label} (0 players)")
    else:
        print(f"  [KTC Status] FAILED — state={ktc_state_label}, error={ktc_row.get('error', 'unknown')} (0 players)")

    # [NEW] Print scrape health report
    await _phase("health_report", "summary", message="Generating scrape health report")
    print_health_report()

    # ── Print results table ──
    active_sites = [s for s, on in SITES.items() if on]
    name_w, col_w = 26, 15
    sep = "=" * (name_w + col_w * len(active_sites))

    def fmt_val(val):
        if val is None:
            return "—"
        if val != int(val):
            return f"{val:.2f}"
        return str(int(val))

    print(f"\n\n{sep}")
    print(f"{'Player':<{name_w}}" + "".join(f"{s:>{col_w}}" for s in active_sites))
    print(sep)
    for player in PLAYERS:
        row = f"{player:<{name_w}}"
        for site in active_sites:
            val = all_results[player].get(site)
            row += f"{fmt_val(val):>{col_w}}"
        print(row)
    print(sep)

    # ── Save CSV (all players with composites) ──
    # Keep spreadsheet outputs stable so each run overwrites the previous file.
    fname = os.path.join(SCRIPT_DIR, "dynasty_values.csv")
    with open(fname, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Player"] + active_sites)
        for player in PLAYERS:
            writer.writerow([player] + [
                fmt_val(all_results[player].get(s)) if all_results[player].get(s) is not None else ""
                for s in active_sites
            ])
    print(f"\nSaved to: {fname} (console players: {len(PLAYERS)})")

    # ── Save JSON for dashboard ──
    site_key_map = {
        "KTC":          "ktc",
        "IDPTradeCalc": "idpTradeCalc",
    }

    RANK_BASED_SITES = set()  # No rank-based sites in the two-source model
    max_values = {}
    for scraper_name, full_map in FULL_DATA.items():
        dash_key = site_key_map.get(scraper_name, scraper_name)
        if dash_key in RANK_BASED_SITES:
            max_values[dash_key] = 9999
        else:
            max_values[dash_key] = compute_max(full_map)
        if DEBUG:
            print(f"  [Max] {scraper_name} → {max_values[dash_key]}")

    # ── Trim sites to top N players before building JSON ──
    _OFFENSIVE_SITES = {"KTC", "FantasyCalc", "DynastyDaddy", "FantasyPros",
                        "DraftSharks", "Yahoo", "DynastyNerds", "DLF_SF"}
    _DEFENSIVE_SITES = {"PFF_IDP", "FantasyPros_IDP", "DLF_IDP"}
    _ROOKIE_ONLY_DLF_SITES = {"DLF_RSF", "DLF_RIDP"}
    _COMBINED_SITES = {"IDPTradeCalc"}  # has both OFF and IDP
    _SITE_CAPS = {}
    for s in _OFFENSIVE_SITES:
        _SITE_CAPS[s] = SITE_CAP_OFFENSE
    for s in _DEFENSIVE_SITES:
        _SITE_CAPS[s] = SITE_CAP_DEFENSE
    for s in _ROOKIE_ONLY_DLF_SITES:
        _SITE_CAPS[s] = SITE_CAP_DEFENSE
    for s in _COMBINED_SITES:
        _SITE_CAPS[s] = SITE_CAP_COMBINED
    # DraftSharks load-rows now provides full offensive pool; don't trim below that.
    _SITE_CAPS["DraftSharks"] = max(SITE_CAP_DRAFTSHARKS, SITE_CAP_OFFENSE)
    if DEBUG:
        print(
            f"  [Coverage Config] caps(off={SITE_CAP_OFFENSE}, def={SITE_CAP_DEFENSE}, "
            f"combined={SITE_CAP_COMBINED}, draftSharks={_SITE_CAPS['DraftSharks']})"
        )

    for site_name, full_map in FULL_DATA.items():
        cap = _SITE_CAPS.get(site_name, 700)
        if len(full_map) > cap:
            # Keep top N by value (higher = better for value sites, lower = better for rank sites)
            dash_key = site_key_map.get(site_name, site_name)
            rank_sites = {"Flock", "DynastyNerds", "PFF_IDP", "FantasyPros_IDP", "DraftSharks_IDP", "DraftSharks"}
            if site_name in rank_sites:
                # Rank-based: lower values are better
                sorted_players = sorted(full_map.items(), key=lambda x: x[1] if x[1] is not None else 99999)
            else:
                # Value-based: higher values are better
                sorted_players = sorted(full_map.items(), key=lambda x: -(x[1] if x[1] is not None else 0))
            trimmed = dict(sorted_players[:cap])
            if DEBUG:
                print(f"  [Cap] {site_name}: {len(full_map)} → {cap} players")
            FULL_DATA[site_name] = trimmed

    all_names = set()
    for full_map in FULL_DATA.values():
        all_names.update(full_map.keys())

    # ── Canonical pool builder: authoritative universe membership ──
    # The pool builder defines the authoritative player universe from three
    # membership sources (Sleeper, KTC top 525, Adamidp PDFs) and enriches
    # with IDPTradeCalc as a crosswalk.  Its output is merged into all_names
    # so downstream valuation logic still processes every member.
    _pool_audit = None
    try:
        from src.pool.builder import build_canonical_pool, PoolAuditReport
        _ktc_full_for_pool = FULL_DATA.get("KTC", {}) if isinstance(FULL_DATA.get("KTC"), dict) else {}
        _idp_tc_for_pool = FULL_DATA.get("IDPTradeCalc", {}) if isinstance(FULL_DATA.get("IDPTradeCalc"), dict) else {}
        _adamidp_artifact = os.path.join(SCRIPT_DIR, "data", "adamidp_normalized.json")
        _pool_rows, _pool_audit = build_canonical_pool(
            sleeper_roster_data=SLEEPER_ROSTER_DATA,
            full_data_ktc=_ktc_full_for_pool,
            adamidp_artifact_path=_adamidp_artifact if os.path.exists(_adamidp_artifact) else None,
            idp_trade_calc_data=_idp_tc_for_pool,
            sleeper_all_nfl=SLEEPER_ALL_NFL,
        )
        # Merge pool members into all_names so downstream valuation covers them
        for _pr in _pool_rows:
            if _pr.canonical_name:
                all_names.add(_pr.canonical_name)
        print(f"  [Pool Builder] Union: {_pool_audit.final_union_count} players "
              f"(sleeper={_pool_audit.sleeper_count}, ktc525={_pool_audit.ktc_top525_count}, "
              f"adamidp={_pool_audit.adamidp_unique_count})")
        print(f"  [Pool Builder] IDPTradeCalc crosswalk: "
              f"queried={_pool_audit.idp_trade_calc_queried_count}, "
              f"matched={_pool_audit.idp_trade_calc_matched_count}, "
              f"unmatched={_pool_audit.idp_trade_calc_unmatched_count}")
    except Exception as _pool_err:
        print(f"  [Pool Builder] Error building canonical pool: {_pool_err}")
        import traceback
        traceback.print_exc()

    # ── Build canonical name resolution map ──
    # Maps variant names (e.g. "A. St. Brown" from DynastyNerds) → Sleeper canonical name.
    _canonical_map = {}  # variant_cleaned → canonical_name
    _sleeper_names = set()
    if SLEEPER_ROSTER_DATA.get("positions"):
        _sleeper_names = set(SLEEPER_ROSTER_DATA["positions"].keys())

    # Build initial-expansion index from rostered Sleeper names: (initial, last) → full_name
    _sleeper_initial_idx = {}
    for sn in _sleeper_names:
        parts = sn.split()
        if len(parts) >= 2:
            initial = parts[0][0].lower()
            last = ' '.join(parts[1:]).lower().replace('-', ' ').replace('.', '')
            _sleeper_initial_idx[(initial, last)] = sn

    # Build normalized lookup from rostered Sleeper names
    _sleeper_norm = {}
    for sn in _sleeper_names:
        _sleeper_norm[normalize_lookup_name(sn)] = sn

    for name in all_names:
        cn = clean_name(name)
        if not cn:
            continue
        # Already a rostered Sleeper canonical name?
        if cn in _sleeper_names:
            _canonical_map[cn] = cn
            continue
        # Normalized match?
        cn_norm = normalize_lookup_name(cn)
        if cn_norm in _sleeper_norm:
            _canonical_map[cn] = _sleeper_norm[cn_norm]
            continue
        # Initial-expansion match? (e.g. "A. St. Brown" → "Amon-Ra St. Brown")
        parts = cn.split()
        if len(parts) >= 2 and len(parts[0].rstrip('.')) <= 2:
            initial = parts[0].rstrip('.')[0].lower()
            last = ' '.join(parts[1:]).lower().replace('-', ' ').replace('.', '')
            key = (initial, last)
            if key in _sleeper_initial_idx:
                _canonical_map[cn] = _sleeper_initial_idx[key]
                if DEBUG:
                    print(f"  [Dedup] '{cn}' → '{_sleeper_initial_idx[key]}'")
                continue
        # Fuzzy match against rostered Sleeper names
        fm = best_match(cn, _sleeper_names, threshold=0.85, match_guard=_is_safe_name_merge)
        if fm:
            _canonical_map[cn] = fm
            continue
        # No match — keep as-is
        _canonical_map[cn] = cn

    # ── Build full Sleeper identity indexes from the global Sleeper player DB ──
    _sleeper_name_candidates = {}     # clean_name -> [candidate...]
    _sleeper_norm_candidates = {}     # normalized_name -> [candidate...]
    _sleeper_initial_candidates = {}  # (initial, last_norm) -> [candidate...]

    for pid, pdata in SLEEPER_ALL_NFL.items():
        if not isinstance(pdata, dict):
            continue
        full = clean_name(
            pdata.get("full_name")
            or f"{pdata.get('first_name', '')} {pdata.get('last_name', '')}".strip()
        )
        if not full:
            continue
        pos = str(pdata.get("position", "") or "").upper()
        cand = {
            "id": str(pid),
            "name": full,
            "pos": pos,
            "active": 1 if pdata.get("active") else 0,
            "team": pdata.get("team") or "",
            "search_rank": float(pdata.get("search_rank", 0) or 0),
            "years_exp": int(pdata.get("years_exp", pdata.get("experience", 0)) or 0),
        }
        _sleeper_name_candidates.setdefault(full, []).append(cand)
        _sleeper_norm_candidates.setdefault(normalize_lookup_name(full), []).append(cand)
        parts = full.split()
        if len(parts) >= 2:
            key = (parts[0][0].lower(), ' '.join(parts[1:]).lower().replace('-', ' ').replace('.', ''))
            _sleeper_initial_candidates.setdefault(key, []).append(cand)

    _sleeper_name_pool = list(_sleeper_name_candidates.keys())

    def _pos_family(pos):
        up = str(pos or "").upper()
        if up in {"DE", "DT", "EDGE", "NT"}:
            return "DL"
        if up in {"CB", "S", "FS", "SS"}:
            return "DB"
        if up in {"OLB", "ILB"}:
            return "LB"
        return up

    def _candidate_score(cand, preferred_pos=""):
        score = 0.0
        if cand.get("active"):
            score += 1000.0
        if cand.get("team"):
            score += 20.0
        score += cand.get("search_rank", 0.0) * 0.01
        score += cand.get("years_exp", 0) * 2.0
        if preferred_pos:
            if _pos_family(cand.get("pos")) == _pos_family(preferred_pos):
                score += 300.0
        return score

    def _pick_best_candidate(candidates, preferred_pos=""):
        if not candidates:
            return None
        return max(candidates, key=lambda c: _candidate_score(c, preferred_pos))

    def _looks_like_pick_name(name):
        s = str(name or "").upper().strip()
        if not s:
            return False
        if re.match(r"^20\d{2}\s+(PICK\s+)?[1-6]\.(0?[1-9]|1[0-2])$", s):
            return True
        if re.match(r"^[1-6]\.(0?[1-9]|1[0-2])$", s):
            return True
        if re.match(r"^20\d{2}\s+(EARLY|MID|LATE)\s+[1-6](ST|ND|RD|TH)$", s):
            return True
        if re.match(r"^(EARLY|MID|LATE)\s+[1-6](ST|ND|RD|TH)$", s):
            return True
        if re.match(r"^20\d{2}\s+[1-6]\s*(ST|ND|RD|TH)\s*(EARLY|MID|LATE)?$", s):
            return True
        if re.match(r"^[1-6]\s*(ST|ND|RD|TH)\s*(EARLY|MID|LATE)?$", s):
            return True
        if " PICK " in f" {s} ":
            return True
        return False

    def _resolve_sleeper_identity(name, preferred_pos=""):
        cleaned = clean_name(name)
        if not cleaned or _looks_like_pick_name(cleaned):
            return None

        candidates = list(_sleeper_name_candidates.get(cleaned, []))
        if not candidates:
            candidates = list(_sleeper_norm_candidates.get(normalize_lookup_name(cleaned), []))
        if not candidates:
            parts = cleaned.split()
            if len(parts) >= 2:
                key = (parts[0][0].lower(), ' '.join(parts[1:]).lower().replace('-', ' ').replace('.', ''))
                candidates = list(_sleeper_initial_candidates.get(key, []))
        if not candidates and _sleeper_name_pool:
            fm = best_match(cleaned, _sleeper_name_pool, threshold=0.90, match_guard=_is_safe_name_merge)
            if fm:
                candidates = list(_sleeper_name_candidates.get(fm, []))
        best = _pick_best_candidate(candidates, preferred_pos)
        if not best:
            return None
        return {
            "id": best["id"],
            "name": best["name"],
            "pos": _pos_family(best.get("pos", "")),
        }

    # Position-based site filtering:
    # IDP-only sites should not contribute values to offensive players
    _OFF_POSITIONS = {"QB", "RB", "WR", "TE", "K"}
    _IDP_POSITIONS = {"LB", "DL", "DE", "DT", "CB", "S", "DB", "EDGE"}
    _IDP_ONLY_SITES = {"pffIdp", "fantasyProsIdp", "dlfIdp", "dlfRidp"}  # IDPTradeCalc removed — it has both OFF and IDP
    _OFF_ONLY_SITES = {"dlfSf", "dlfRsf"}
    _pos_map = dict(SLEEPER_ROSTER_DATA.get("positions", {}))
    _player_id_map = dict(SLEEPER_ROSTER_DATA.get("playerIds", {}))
    _id_to_player = dict(SLEEPER_ROSTER_DATA.get("idToPlayer", {}))

    def _get_pos(name):
        """Get position from Sleeper data (case-insensitive lookup)."""
        if name in _pos_map:
            return _pos_map[name].upper()
        nl = name.lower()
        for k, v in _pos_map.items():
            if k.lower() == nl:
                return v.upper()
        return ""

    players_json = {}
    for name in sorted(all_names):
        raw_canonical = clean_name(name)
        if not raw_canonical:
            continue
        # Drop non-player bucket rows and ambiguous yearless pick labels.
        if re.match(r"^ALL OTHER\b", raw_canonical.upper()):
            continue
        if _looks_like_pick_name(raw_canonical) and not re.match(r"^20\d{2}\b", raw_canonical.upper()):
            continue

        # Resolve to canonical rostered name first (merges "A. St. Brown" → "Amon-Ra St. Brown")
        canonical = _canonical_map.get(raw_canonical, raw_canonical)
        player_pos = _get_pos(canonical) or _get_pos(raw_canonical) or _get_pos(name)

        # Then resolve to a full Sleeper identity for robust cross-source linkage.
        sleeper_identity = None
        if not _looks_like_pick_name(canonical):
            sleeper_identity = _resolve_sleeper_identity(canonical, preferred_pos=player_pos)
            if not sleeper_identity and canonical != raw_canonical:
                sleeper_identity = _resolve_sleeper_identity(raw_canonical, preferred_pos=player_pos)
            if sleeper_identity:
                canonical = sleeper_identity.get("name") or canonical
                if sleeper_identity.get("pos"):
                    player_pos = sleeper_identity["pos"]

        entry = players_json.get(canonical, {})
        is_idp = player_pos in _IDP_POSITIONS
        is_off = player_pos in _OFF_POSITIONS

        for scraper_name, full_map in FULL_DATA.items():
            if name in full_map and full_map[name] is not None:
                dash_key = site_key_map.get(scraper_name, scraper_name)
                if dash_key not in entry:
                    # Skip IDP-only sites for offensive players
                    if dash_key in _IDP_ONLY_SITES and is_off:
                        continue
                    # Skip offensive-only sites for IDP players
                    if dash_key in _OFF_ONLY_SITES and is_idp:
                        continue
                    val = full_map[name]
                    entry[dash_key] = round(val, 2) if val != int(val) else int(val)

        if not entry:
            continue

        if sleeper_identity and sleeper_identity.get("id"):
            sid = str(sleeper_identity["id"])
            entry["_sleeperId"] = sid
            _player_id_map[canonical] = sid
            _id_to_player[sid] = canonical
            if player_pos and canonical not in _pos_map:
                _pos_map[canonical] = player_pos
        elif player_pos and canonical not in _pos_map:
            _pos_map[canonical] = player_pos

        players_json[canonical] = entry

    # Merge punctuation/initial variants that still slipped through canonical resolution.
    # Example: "T.J. Parker" and "TJ Parker" must resolve to one player row.
    def _entry_site_count(e):
        if not isinstance(e, dict):
            return 0
        c = 0
        for _k, _v in e.items():
            if str(_k).startswith("_"):
                continue
            if isinstance(_v, (int, float)) and _v is not None and float(_v) > 0:
                c += 1
        return c

    def _pick_primary_name(a, b):
        ea = players_json.get(a, {}) if isinstance(players_json.get(a), dict) else {}
        eb = players_json.get(b, {}) if isinstance(players_json.get(b), dict) else {}
        score_a = (
            (10 if ea.get("_sleeperId") else 0)
            + (5 if _get_pos(a) else 0)
            + _entry_site_count(ea)
        )
        score_b = (
            (10 if eb.get("_sleeperId") else 0)
            + (5 if _get_pos(b) else 0)
            + _entry_site_count(eb)
        )
        if score_a != score_b:
            return a if score_a > score_b else b
        # Prefer the cleaner display form (fewer punctuation marks).
        punct_a = len(re.findall(r"[.\-']", a))
        punct_b = len(re.findall(r"[.\-']", b))
        if punct_a != punct_b:
            return a if punct_a < punct_b else b
        return a if a <= b else b

    _by_norm_name = {}
    _merged_name_variants = 0
    for _name in sorted(list(players_json.keys())):
        _norm = normalize_lookup_name(_name)
        if not _norm:
            continue
        if _norm not in _by_norm_name:
            _by_norm_name[_norm] = _name
            continue
        _other = _by_norm_name[_norm]
        if _other == _name or _other not in players_json or _name not in players_json:
            continue
        _primary = _pick_primary_name(_other, _name)
        _secondary = _name if _primary == _other else _other
        if _primary == _secondary:
            continue

        _p_entry = players_json.get(_primary, {})
        _s_entry = players_json.get(_secondary, {})
        if not isinstance(_p_entry, dict) or not isinstance(_s_entry, dict):
            continue

        # Keep real site values additive (only fill missing source slots).
        for _k, _v in _s_entry.items():
            if str(_k).startswith("_"):
                continue
            if _k not in _p_entry and isinstance(_v, (int, float)) and _v is not None and float(_v) > 0:
                _p_entry[_k] = _v

        # Preserve identity metadata if primary lacks it.
        if not _p_entry.get("_sleeperId") and _s_entry.get("_sleeperId"):
            _p_entry["_sleeperId"] = _s_entry.get("_sleeperId")

        _primary_pos = _get_pos(_primary)
        _secondary_pos = _get_pos(_secondary)
        if not _primary_pos and _secondary_pos:
            _pos_map[_primary] = _secondary_pos

        _sid = _p_entry.get("_sleeperId") or _s_entry.get("_sleeperId") or _player_id_map.get(_secondary)
        if _sid:
            _sid = str(_sid)
            _p_entry["_sleeperId"] = _sid
            _player_id_map[_primary] = _sid
            _id_to_player[_sid] = _primary

        players_json[_primary] = _p_entry
        players_json.pop(_secondary, None)
        _pos_map.pop(_secondary, None)
        _player_id_map.pop(_secondary, None)
        _by_norm_name[_norm] = _primary
        _merged_name_variants += 1

    if DEBUG and _merged_name_variants:
        print(f"  [Dedup] Merged {_merged_name_variants} punctuation/initial name variants")

    # Backfill IDP positions for players that only came in through IDP-specific feeds.
    # This keeps IDP filters/coverage accurate even for deep-tier defenders not rostered.
    # Rookie-only DLF feeds are not treated as primary cross-source identity/evidence signals.
    _IDP_SIGNAL_KEYS = {"pffIdp", "fantasyProsIdp", "draftSharksIdp", "dlfIdp"}
    _OFF_SIGNAL_KEYS = {"ktc", "fantasyCalc", "dynastyDaddy", "fantasyPros", "draftSharks", "yahoo", "dynastyNerds", "dlfSf"}
    _idp_pos_backfilled = 0
    for pname, entry in players_json.items():
        if not isinstance(entry, dict):
            continue
        if _looks_like_pick_name(pname):
            continue

        cur_pos = _get_pos(pname)
        if cur_pos in _IDP_POSITIONS:
            continue

        has_idp_signal = any(isinstance(entry.get(k), (int, float)) for k in _IDP_SIGNAL_KEYS)
        if not has_idp_signal:
            continue

        ident = _resolve_sleeper_identity(pname, preferred_pos="LB")
        if ident and ident.get("pos") in _IDP_POSITIONS:
            _pos_map[pname] = ident.get("pos")
            sid = ident.get("id")
            if sid:
                sid = str(sid)
                entry["_sleeperId"] = sid
                _player_id_map[pname] = sid
                _id_to_player[sid] = pname
            _idp_pos_backfilled += 1
            continue

        has_off_signal = any(isinstance(entry.get(k), (int, float)) for k in _OFF_SIGNAL_KEYS)
        if not has_off_signal:
            # Conservative fallback: IDP-site-only players with unknown position
            # are treated as LB so they remain in the IDP universe.
            _pos_map[pname] = "LB"
            _idp_pos_backfilled += 1

    if DEBUG and _idp_pos_backfilled:
        print(f"  [IDP Coverage] Backfilled positions for {_idp_pos_backfilled} IDP-signaled players")

    # Keep enriched Sleeper identity data attached to the exported roster block.
    if _pos_map:
        SLEEPER_ROSTER_DATA["positions"] = _pos_map
    if _player_id_map:
        SLEEPER_ROSTER_DATA["playerIds"] = _player_id_map
        SLEEPER_ROSTER_DATA["idToPlayer"] = _id_to_player

    # Canonical KTC playerID map for URL imports and DB joins in the UI.
    ktc_id_map = {}
    for pid, pname in KTC_ID_TO_NAME.items():
        clean = clean_name(pname)
        if not clean:
            continue
        canonical = _canonical_map.get(clean, clean)
        pref_pos = _get_pos(canonical)
        ident = _resolve_sleeper_identity(canonical, preferred_pos=pref_pos)
        if ident and ident.get("name"):
            canonical = ident["name"]
        if canonical in players_json:
            ktc_id_map[str(pid)] = canonical

    def _pick_value(v):
        if v is None or not isinstance(v, (int, float)):
            return None
        if v <= 0:
            return None
        return float(v)

    def _fmt_pick_value(v):
        if v is None:
            return None
        if abs(v - round(v)) < 1e-9:
            return int(round(v))
        return round(v, 2)

    def _pick_suffix(round_num):
        if round_num == 1:
            return "st"
        if round_num == 2:
            return "nd"
        if round_num == 3:
            return "rd"
        return "th"

    def _slot_tier_ranges(league_size=12):
        per_tier = max(1, int(league_size) // 3)
        early_end = per_tier
        mid_end = per_tier * 2
        return {
            "early": (1, early_end),
            "mid": (early_end + 1, mid_end),
            "late": (mid_end + 1, int(league_size)),
        }

    def _slot_to_tier(slot, league_size=12):
        ranges = _slot_tier_ranges(league_size)
        for tier, (lo, hi) in ranges.items():
            if lo <= slot <= hi:
                return tier
        return "late"

    def _parse_pick_label(raw):
        if not isinstance(raw, str):
            return None
        s = re.sub(r"\s+", " ", raw.strip().upper())
        if not s:
            return None
        s = re.sub(r"\b(PICK|ROUND|RD|DRAFT|OVERALL)\b", " ", s)
        s = re.sub(r"\s+", " ", s).strip()

        m = re.match(r"^(20\d{2})\s+([1-6])\.(0?[1-9]|1[0-2])$", s)
        if m:
            return {
                "kind": "slot",
                "year": int(m.group(1)),
                "round": int(m.group(2)),
                "slot": int(m.group(3)),
            }
        m = re.match(r"^([1-6])\.(0?[1-9]|1[0-2])$", s)
        if m:
            return {
                "kind": "slot",
                "year": None,
                "round": int(m.group(1)),
                "slot": int(m.group(2)),
            }

        m = re.match(r"^(20\d{2})\s+(EARLY|MID|LATE)\s+([1-6])\s*(ST|ND|RD|TH)$", s)
        if m:
            return {
                "kind": "tier",
                "year": int(m.group(1)),
                "tier": m.group(2).lower(),
                "round": int(m.group(3)),
            }
        m = re.match(r"^(EARLY|MID|LATE)\s+([1-6])\s*(ST|ND|RD|TH)$", s)
        if m:
            return {
                "kind": "tier",
                "year": None,
                "tier": m.group(1).lower(),
                "round": int(m.group(2)),
            }

        m = re.match(r"^(20\d{2})\s+([1-6])\s*(ST|ND|RD|TH)\s*(EARLY|MID|LATE)?$", s)
        if m:
            return {
                "kind": "tier",
                "year": int(m.group(1)),
                "tier": (m.group(4) or "MID").lower(),
                "round": int(m.group(2)),
            }
        m = re.match(r"^([1-6])\s*(ST|ND|RD|TH)\s*(EARLY|MID|LATE)?$", s)
        if m:
            return {
                "kind": "tier",
                "year": None,
                "tier": (m.group(3) or "MID").lower(),
                "round": int(m.group(1)),
            }

        m = re.match(r"^(20\d{2})\s+([1-6])$", s)
        if m:
            return {
                "kind": "tier",
                "year": int(m.group(1)),
                "tier": "mid",
                "round": int(m.group(2)),
            }
        m = re.match(r"^([1-6])$", s)
        if m:
            return {
                "kind": "tier",
                "year": None,
                "tier": "mid",
                "round": int(m.group(1)),
            }
        return None

    def _nearest_year(years, target):
        years = sorted(y for y in years if y is not None)
        if not years:
            return None
        return min(years, key=lambda y: abs(y - target))

    def _avg(vals):
        if not vals:
            return None
        return sum(vals) / len(vals)

    def _build_site_pick_map(parsed_rows, target_years, league_size=12):
        if not parsed_rows:
            return {}

        tier_values = {}  # (year, round, tier) -> [values]
        slot_values = {}  # (year, round, slot) -> [values]
        rounds_found = set()

        for row in parsed_rows:
            year = row.get("year")
            round_num = row.get("round")
            if not isinstance(round_num, int) or not (1 <= round_num <= 6):
                continue
            rounds_found.add(round_num)
            val = row["value"]
            if row["kind"] == "tier":
                key = (year, round_num, row["tier"])
                tier_values.setdefault(key, []).append(val)
            elif row["kind"] == "slot":
                slot = row["slot"]
                if 1 <= slot <= league_size:
                    key = (year, round_num, slot)
                    slot_values.setdefault(key, []).append(val)

        if not rounds_found:
            return {}

        max_round = min(6, max(rounds_found))
        emit_max_round = max(4, max_round)
        rounds_to_emit = range(1, emit_max_round + 1)
        tier_ranges = _slot_tier_ranges(league_size)

        def lookup_tier(year, round_num, tier):
            for y in (year, None):
                vals = tier_values.get((y, round_num, tier), [])
                if vals:
                    return _avg(vals)

            lo, hi = tier_ranges[tier]
            for y in (year, None):
                vals = []
                for slot in range(lo, hi + 1):
                    vals.extend(slot_values.get((y, round_num, slot), []))
                if vals:
                    return _avg(vals)

            years_with_tier = {
                y for (y, r, t) in tier_values.keys()
                if y is not None and r == round_num and t == tier
            }
            near_year = _nearest_year(years_with_tier, year)
            if near_year is not None:
                vals = tier_values.get((near_year, round_num, tier), [])
                if vals:
                    return _avg(vals)

            years_with_slots = {
                y for (y, r, s) in slot_values.keys()
                if y is not None and r == round_num and lo <= s <= hi
            }
            near_year = _nearest_year(years_with_slots, year)
            if near_year is not None:
                vals = []
                for slot in range(lo, hi + 1):
                    vals.extend(slot_values.get((near_year, round_num, slot), []))
                if vals:
                    return _avg(vals)
            return None

        def _estimate_slot_from_tier(year, round_num, slot):
            tier = _slot_to_tier(slot, league_size)
            tier_val = lookup_tier(year, round_num, tier)
            if tier_val is None:
                return None

            lo, hi = tier_ranges[tier]
            if hi <= lo:
                return tier_val

            # Spread tier-only values into a slot curve so 1.01 != "Early 1st".
            # Keeps the average near the tier value while creating realistic separation.
            spread = 0.20 if tier == "early" else 0.14 if tier == "mid" else 0.12
            rel = 1.0 - (2.0 * (slot - lo) / float(hi - lo))  # +1 at start, -1 at end
            est = tier_val * (1.0 + spread * rel)
            return max(1.0, est)

        def lookup_slot(year, round_num, slot):
            for y in (year, None):
                vals = slot_values.get((y, round_num, slot), [])
                if vals:
                    return _avg(vals)

            years_with_slot = {
                y for (y, r, s) in slot_values.keys()
                if y is not None and r == round_num and s == slot
            }
            near_year = _nearest_year(years_with_slot, year)
            if near_year is not None:
                vals = slot_values.get((near_year, round_num, slot), [])
                if vals:
                    return _avg(vals)

            est = _estimate_slot_from_tier(year, round_num, slot)
            if est is not None:
                return est
            return None

        out = {}
        for year in target_years:
            for round_num in rounds_to_emit:
                for tier in ("early", "mid", "late"):
                    t_val = lookup_tier(year, round_num, tier)
                    if t_val is not None:
                        out[f"{year} {tier.capitalize()} {round_num}{_pick_suffix(round_num)}"] = _fmt_pick_value(t_val)

                for slot in range(1, league_size + 1):
                    s_val = lookup_slot(year, round_num, slot)
                    if s_val is not None:
                        out[f"{year} {round_num}.{slot:02d}"] = _fmt_pick_value(s_val)
        return out

    current_year = datetime.date.today().year
    target_pick_years = [current_year, current_year + 1, current_year + 2]
    # Explicitly exclude non-pick sources from pick values.
    PICK_VALUE_EXCLUDED_SITES = {"draftSharks", "pffIdp"}
    pick_anchors = {}
    pick_anchors_raw = {}
    for scraper_name, full_map in FULL_DATA.items():
        dash_key = site_key_map.get(scraper_name, scraper_name)
        if dash_key in PICK_VALUE_EXCLUDED_SITES:
            continue
        parsed_rows = []
        raw_picks = {}
        for name, val in full_map.items():
            pval = _pick_value(val)
            if pval is None:
                continue
            parsed = _parse_pick_label(name)
            if not parsed:
                continue
            parsed["value"] = pval
            parsed_rows.append(parsed)
            raw_picks[name] = _fmt_pick_value(pval)

        if not parsed_rows:
            continue

        pick_anchors_raw[dash_key] = raw_picks
        site_map = _build_site_pick_map(parsed_rows, target_pick_years, league_size=12)
        if site_map:
            pick_anchors[dash_key] = site_map
            if DEBUG:
                years = sorted({
                    int(m.group(1))
                    for key in site_map.keys()
                    for m in [re.match(r"^(20\d{2})\s+", key)]
                    if m
                })
                print(f"  [Pick Anchors] {dash_key}: {len(site_map)} canonical picks ({years})")
        else:
            pick_anchors[dash_key] = raw_picks

    # Inject canonical slot-pick rows from pick anchors so individual picks
    # are multi-source across years (not just tier labels from raw site rows).
    _slot_key_rx = re.compile(r"^(20\d{2})\s+([1-6]\.(0?[1-9]|1[0-2]))$")
    _tier_key_rx = re.compile(r"^(20\d{2})\s+(Early|Mid|Late)\s+([1-6])(st|nd|rd|th)$")
    _pick_slots_added = 0
    _pick_slots_updated = 0
    _pick_tiers_updated = 0
    for site_key, site_map in pick_anchors.items():
        if not isinstance(site_map, dict):
            continue
        for pick_key, val in site_map.items():
            pval = _pick_value(val)
            if pval is None:
                continue

            pick_key_s = str(pick_key)
            slot_m = _slot_key_rx.match(pick_key_s)
            tier_m = _tier_key_rx.match(pick_key_s)

            canonical_pick_name = None
            if slot_m:
                year = int(slot_m.group(1))
                slot_key = slot_m.group(2)
                canonical_pick_name = f"{year} Pick {slot_key}"
            elif tier_m:
                year = int(tier_m.group(1))
                tier = tier_m.group(2).capitalize()
                round_num = int(tier_m.group(3))
                canonical_pick_name = f"{year} {tier} {round_num}{_pick_suffix(round_num)}"
            else:
                continue

            existed = canonical_pick_name in players_json
            entry = players_json.get(canonical_pick_name, {})

            prev = entry.get(site_key)
            entry[site_key] = _fmt_pick_value(pval)
            players_json[canonical_pick_name] = entry

            if slot_m:
                if existed:
                    if prev != entry.get(site_key):
                        _pick_slots_updated += 1
                else:
                    _pick_slots_added += 1
            else:
                if prev != entry.get(site_key):
                    _pick_tiers_updated += 1

    if DEBUG and (_pick_slots_added or _pick_slots_updated or _pick_tiers_updated):
        print(
            f"  [Pick Slots] Added {_pick_slots_added} canonical slot picks, "
            f"updated {_pick_slots_updated} slot values, updated {_pick_tiers_updated} tier values"
        )

    # Conservative cross-source backfill for missing site values.
    # Purpose: catch safe name/key mismatches without inventing data.
    _dash_to_scraper = {
        site_key_map.get(scraper_name, scraper_name): scraper_name
        for scraper_name in FULL_DATA.keys()
    }

    def _has_numeric_value(v):
        return isinstance(v, (int, float)) and v > 0

    def _fmt_site_value(v):
        if not _has_numeric_value(v):
            return None
        if abs(float(v) - round(float(v))) < 1e-9:
            return int(round(float(v)))
        return round(float(v), 2)

    def _build_site_indices(full_map):
        out = {
            "clean": {},
            "norm": {},
            "initial_last": {},
            "names": [],
        }
        for src_name in full_map.keys():
            if not isinstance(src_name, str):
                continue
            cleaned = clean_name(src_name)
            normed = normalize_lookup_name(src_name)
            if cleaned:
                out["clean"].setdefault(cleaned, set()).add(src_name)
            if normed:
                out["norm"].setdefault(normed, set()).add(src_name)
                parts = normed.split()
                if len(parts) >= 2:
                    out["initial_last"].setdefault((parts[0][0], parts[-1]), set()).add(src_name)
            out["names"].append(src_name)
        return out

    def _unique_lookup(index_map, key):
        vals = index_map.get(key)
        if not vals or len(vals) != 1:
            return None
        return next(iter(vals))

    _identity_cache = {}

    def _resolve_identity_cached(name, preferred_pos=""):
        key = (clean_name(name), _pos_family(preferred_pos))
        if key in _identity_cache:
            return _identity_cache[key]
        ident = _resolve_sleeper_identity(name, preferred_pos=preferred_pos)
        _identity_cache[key] = ident
        return ident

    def _candidate_identity_ok(target_sid, target_pos, candidate_name):
        if not candidate_name:
            return False
        sid = str(target_sid or "").strip()
        if not sid and not target_pos:
            return True
        ident = _resolve_identity_cached(candidate_name, preferred_pos=target_pos)
        if sid:
            if not ident or not ident.get("id"):
                return False
            return str(ident.get("id")) == sid
        if target_pos:
            if not ident or not ident.get("pos"):
                return False
            return _pos_family(ident.get("pos")) == _pos_family(target_pos)
        return False

    _site_indices = {}
    for scraper_name, full_map in FULL_DATA.items():
        dash_key = site_key_map.get(scraper_name, scraper_name)
        _site_indices[dash_key] = _build_site_indices(full_map)

    def _find_site_candidate(site_key, target_name, target_pos="", target_sid="", allow_fuzzy=True):
        scraper_name = _dash_to_scraper.get(site_key)
        if not scraper_name:
            return None, None, "site_unavailable"
        full_map = FULL_DATA.get(scraper_name, {})
        if not full_map:
            return None, None, "site_unavailable"
        idx = _site_indices.get(site_key, {})
        target_clean = clean_name(target_name)
        target_norm = normalize_lookup_name(target_name)
        sid = str(target_sid or "").strip()

        def _accept(candidate_name, reason):
            if not candidate_name:
                return None, None, reason
            val = full_map.get(candidate_name)
            if not _has_numeric_value(val):
                return None, None, "invalid_value"
            # Initial+last and fuzzy paths are high-risk for same-last-name collisions.
            # Require identity checks there so players don't inherit values across positions.
            if reason in {"initial_last", "fuzzy"}:
                if not _candidate_identity_ok(sid, target_pos, candidate_name):
                    return None, None, "identity_mismatch"
            return candidate_name, float(val), reason

        # Exact keys first (raw + cleaned string key).
        for key in (target_name, target_clean):
            if key in full_map:
                cand, val, why = _accept(key, "exact")
                if cand and val is not None:
                    return cand, val, why

        # Unique normalized-key matches.
        cand_key = _unique_lookup(idx.get("clean", {}), target_clean)
        cand, val, why = _accept(cand_key, "clean")
        if cand and val is not None:
            return cand, val, why

        cand_key = _unique_lookup(idx.get("norm", {}), target_norm)
        cand, val, why = _accept(cand_key, "normalized")
        if cand and val is not None:
            return cand, val, why

        parts = target_norm.split() if target_norm else []
        if len(parts) >= 2:
            cand_key = _unique_lookup(idx.get("initial_last", {}), (parts[0][0], parts[-1]))
            cand, val, why = _accept(cand_key, "initial_last")
            if cand and val is not None:
                return cand, val, why

        if allow_fuzzy:
            fuzzy_target = target_clean or target_name
            fm = best_match(fuzzy_target, idx.get("names", []), threshold=0.90, match_guard=_is_safe_name_merge)
            cand, val, why = _accept(fm, "fuzzy")
            if cand and val is not None:
                return cand, val, why

        return None, None, "no_candidate"

    def _expected_sites_for_pos(pos):
        p = str(pos or "").upper()
        if p in _OFF_POSITIONS:
            return TOP_OFF_EXPECTED_SITE_KEYS
        if p in _IDP_POSITIONS:
            return TOP_IDP_EXPECTED_SITE_KEYS
        return ()

    _coverage_repair_stats = {
        "playersTouched": 0,
        "valuesBackfilled": 0,
        "bySite": {},
        "byMethod": {},
    }
    for pname, entry in players_json.items():
        if not isinstance(entry, dict) or _looks_like_pick_name(pname):
            continue
        pos = _get_pos(pname)
        expected_sites = _expected_sites_for_pos(pos)
        if not expected_sites:
            continue
        sid = str(entry.get("_sleeperId") or _player_id_map.get(pname) or "").strip()
        touched = False
        for site_key in expected_sites:
            if _has_numeric_value(entry.get(site_key)):
                continue
            cand, val, method = _find_site_candidate(
                site_key,
                pname,
                target_pos=pos,
                target_sid=sid,
                allow_fuzzy=True,
            )
            if cand and val is not None:
                entry[site_key] = _fmt_site_value(val)
                _coverage_repair_stats["valuesBackfilled"] += 1
                _coverage_repair_stats["bySite"][site_key] = _coverage_repair_stats["bySite"].get(site_key, 0) + 1
                _coverage_repair_stats["byMethod"][method] = _coverage_repair_stats["byMethod"].get(method, 0) + 1
                touched = True
        if touched:
            _coverage_repair_stats["playersTouched"] += 1

    if _coverage_repair_stats["valuesBackfilled"]:
        print(
            f"  [Coverage Repair] Backfilled {_coverage_repair_stats['valuesBackfilled']} "
            f"values across {_coverage_repair_stats['playersTouched']} players"
        )
        if DEBUG:
            print(f"  [Coverage Repair] Methods: {_coverage_repair_stats['byMethod']}")
            print(f"  [Coverage Repair] Sites: {_coverage_repair_stats['bySite']}")

    sites_meta = []
    _dlf_dash_keys = ("dlfSf", "dlfIdp", "dlfRsf", "dlfRidp")

    def _count_players_with_site_value(dash_key):
        c = 0
        for entry in players_json.values():
            if isinstance(entry, dict) and _has_numeric_value(entry.get(dash_key)):
                c += 1
        return c

    for scraper_name in active_sites:
        dash_key = site_key_map.get(scraper_name, scraper_name)
        if scraper_name == "DLF":
            count = 0
            for k in _dlf_dash_keys:
                count = max(count, _count_players_with_site_value(k))
        else:
            count = len(FULL_DATA.get(scraper_name, {}))
        sites_meta.append({
            "key": dash_key,
            "label": scraper_name,
            "max": max_values.get(dash_key, 0),
            "playerCount": count,
        })

    # Expose per-file DLF sources for site status + source table toggles.
    _dlf_meta_sources = (
        ("DLF_SF", "dlfSf", "DLF SF"),
        ("DLF_IDP", "dlfIdp", "DLF IDP"),
        ("DLF_RSF", "dlfRsf", "DLF R SF"),
        ("DLF_RIDP", "dlfRidp", "DLF R IDP"),
    )
    existing_site_keys = {str(s.get("key")) for s in sites_meta if isinstance(s, dict)}
    for scraper_name, dash_key, label in _dlf_meta_sources:
        if dash_key in existing_site_keys:
            continue
        if scraper_name not in FULL_DATA:
            continue
        count = _count_players_with_site_value(dash_key)
        sites_meta.append({
            "key": dash_key,
            "label": label,
            "max": max_values.get(dash_key, 9999),
            "playerCount": count,
        })

    # [NEW] Compute per-site mean and stdev for z-score normalization
    site_stats = {}
    # Site mode mapping
    _rank_sites = {"dynastyNerds", "pffIdp", "draftSharksIdp", "fantasyProsIdp", "draftSharks"}
    _idp_rank_sites = set()  # currently none use idpRank mode in scraper (handled in dashboard)
    # DynastyDaddy values are treated as non-TEP and get TEP_MULT applied for TEs.
    _tep_sites = {"ktc", "fantasyCalc", "fantasyPros", "draftSharks",
                  "yahoo", "dynastyNerds", "idpTradeCalc"}
    # Z-score parameters
    Z_FLOOR, Z_CEILING = -2.0, 4.0
    RANK_OFFSET, RANK_DIVISOR, RANK_EXPONENT = 27, 28, -0.66
    # IDP Anchor System: tether the #1 IDP player to IDPTradeCalc's top non-Hunter value
    # This makes the anchor self-adjusting as the IDP market shifts
    _IDP_ANCHOR_EXCLUDE = {"travis hunter"}  # Excluded from anchor — he's a WR in dynasty
    _IDP_ANCHOR_POSITIONS = {"LB", "DL", "DE", "DT", "CB", "S", "DB", "EDGE", "NT", "OLB", "ILB", "FS", "SS"}
    _idp_tc_data = FULL_DATA.get("IDPTradeCalc", {})
    _pos_map_anchor = SLEEPER_ROSTER_DATA.get("positions", {})

    def _anchor_pos(name):
        """Get position for anchor filtering (case-insensitive Sleeper lookup)."""
        pos = _pos_map_anchor.get(name, "")
        if not pos:
            nl = name.lower()
            for k, v in _pos_map_anchor.items():
                if k.lower() == nl:
                    return v.upper()
        return pos.upper()

    _idp_anchor_candidates = [
        (name, v) for name, v in _idp_tc_data.items()
        if v is not None and isinstance(v, (int, float)) and v > 0
        and name.lower() not in _IDP_ANCHOR_EXCLUDE
        and _anchor_pos(name) in _IDP_ANCHOR_POSITIONS
    ]
    if _idp_anchor_candidates:
        _idp_anchor_candidates.sort(key=lambda x: -x[1])
        IDP_ANCHOR_TOP = _idp_anchor_candidates[0][1]
        print(f"  [IDP Anchor] Top defensive player: {_idp_anchor_candidates[0][0]} = {IDP_ANCHOR_TOP}")
        if len(_idp_anchor_candidates) >= 3:
            print(f"  [IDP Anchor] Top 3: {[(n, v) for n, v in _idp_anchor_candidates[:3]]}")
    else:
        IDP_ANCHOR_TOP = 6250
        print(f"  [IDP Anchor] No defensive players found — fallback {IDP_ANCHOR_TOP}")

    def _idp_bucket(pos):
        p = str(pos or '').upper()
        if p in {'DE', 'DT', 'EDGE', 'NT'}:
            return 'DL'
        if p in {'CB', 'S', 'FS', 'SS', 'DB'}:
            return 'DB'
        if p in {'LB', 'OLB', 'ILB'}:
            return 'LB'
        return 'ALL'

    def _build_idp_anchor_points(values, fallback_top):
        vals = sorted([float(v) for v in values if isinstance(v, (int, float)) and v > 0], reverse=True)
        if not vals:
            return [(1, float(fallback_top))]
        ranks = [1, 3, 6, 12, 24, 48, 72, 96]
        pts = []
        for rank in ranks:
            idx = min(len(vals) - 1, max(0, rank - 1))
            pts.append((rank, vals[idx]))
        mono = []
        for rank, value in pts:
            if mono:
                value = min(mono[-1][1], value)
            if not mono or mono[-1][0] != rank:
                mono.append((rank, value))
        return mono

    def _interp_anchor_points(rank_value, points):
        import math
        rank = max(1.0, float(rank_value))
        pts = [(float(r), float(v)) for r, v in points if r and v and v > 0]
        pts.sort(key=lambda x: x[0])
        if not pts:
            return float(IDP_ANCHOR_TOP)
        if rank <= pts[0][0]:
            return pts[0][1]
        for i in range(1, len(pts)):
            r0, v0 = pts[i - 1]
            r1, v1 = pts[i]
            if rank <= r1:
                t = (math.log(rank) - math.log(r0)) / max(1e-9, (math.log(r1) - math.log(r0)))
                return math.exp(math.log(v0) + (math.log(v1) - math.log(v0)) * max(0.0, min(1.0, t)))
        r0, v0 = pts[-2] if len(pts) >= 2 else pts[-1]
        r1, v1 = pts[-1]
        if r0 == r1:
            return v1
        slope = (math.log(v1) - math.log(v0)) / (math.log(r1) - math.log(r0))
        return max(1.0, math.exp(math.log(v1) + slope * (math.log(rank) - math.log(r1))))

    _idp_backbone_values = {'ALL': [], 'LB': [], 'DL': [], 'DB': []}
    for _name, _value in _idp_anchor_candidates:
        _bucket = _idp_bucket(_anchor_pos(_name))
        _idp_backbone_values['ALL'].append(_value)
        if _bucket != 'ALL':
            _idp_backbone_values[_bucket].append(_value)
    _idp_anchor_curves = {
        bucket: _build_idp_anchor_points(vals, IDP_ANCHOR_TOP)
        for bucket, vals in _idp_backbone_values.items()
        if vals or bucket == 'ALL'
    }

    def _idp_rank_to_value(rank_value, pos=''):
        bucket = _idp_bucket(pos)
        curve = _idp_anchor_curves.get(bucket) or _idp_anchor_curves.get('ALL') or [(1, float(IDP_ANCHOR_TOP))]
        return _interp_anchor_points(rank_value, curve)

    IDP_RANK_OFFSET = 15     # Controls curve flatness near the top
    IDP_RANK_DIVISOR = 16    # Paired with offset so rank 1 → exactly IDP_ANCHOR_TOP
    IDP_RANK_EXPONENT = -0.72  # Steeper than offense (-0.66) since IDP value drops faster
    TEP_MULT = 1.15
    SINGLE_SOURCE_DISCOUNT = 0.85  # 15% discount for players on only 1 site
    COMPOSITE_SCALE = 9999
    OUTLIER_TRIM_GAP = 0.18       # Trim only true outliers, not legitimate elite values
    # Elite ceiling expansion: allows top-consensus players to approach 9999.
    # Phase 3 fix: raised from 0.045 → 0.09 and lowered threshold from 0.91 → 0.88
    # so Josh Allen (highest ranked) gets closer to true top-of-market ceiling.
    ELITE_NORM_THRESHOLD = 0.88   # Start elite expansion at moderate consensus
    ELITE_BOOST_MAX = 0.09        # Cap elite expansion at +9%
    IDP_VALUE_HEADROOM_FRACTION = 0.18  # controlled IDP lift above value-site cap
    # Single-source suppression: Phase 3 fix — lowered min from 0.70 → 0.55
    # so fragile one-source veterans (Tyler Lockett etc.) get much stronger
    # low-liquidity penalty, making their values materially less reliable.
    SINGLE_SOURCE_DISCOUNT_MIN = 0.55
    SINGLE_SOURCE_DISCOUNT_MAX = 0.82

    # IDP rank sites get their own rank→value curve anchored at IDP_ANCHOR_TOP
    _idp_rank_sites = {"pffIdp", "fantasyProsIdp"}
    # IDPTradeCalc is value-based but we cap it at IDP_ANCHOR_TOP
    _idp_value_cap_sites = {"idpTradeCalc"}
    # DLF IDP exports are rank-derived synthetic values (converted to canonical scale),
    # so they should not define value-site cap anchors.
    _idp_synthetic_value_sites = {"dlfIdp", "dlfRidp"}

    # Default site weights (market-based sources weighted higher)
    SITE_WEIGHTS = {
        "ktc": 1.3, "fantasyCalc": 1.0, "dynastyDaddy": 1.0,
        "fantasyPros": 0.8, "draftSharks": 0.9, "yahoo": 0.8,
        "dynastyNerds": 0.8, "idpTradeCalc": 1.0,
        "dlfSf": 0.8, "dlfIdp": 0.8, "dlfRsf": 0.7, "dlfRidp": 0.7,
        "pffIdp": 0.7, "fantasyProsIdp": 0.7,
    }
    # Rookie-only DLF exports remain visible as source signals, but are quarantined
    # from normal dynasty composite math so rookie rank lists cannot inflate market value.
    _ROOKIE_ONLY_DLF_SITE_KEYS = {"dlfRsf", "dlfRidp"}
    _REAL_IDP_MARKET_SITE_KEYS = {"idpTradeCalc", "pffIdp", "fantasyProsIdp", "dlfIdp", "draftSharksIdp"}
    IDP_ROOKIE_ONLY_NO_MARKET_CAP = 2600

    _curve_pos_map = SLEEPER_ROSTER_DATA.get("positions", {}) if isinstance(SLEEPER_ROSTER_DATA, dict) else {}
    _rookie_must_have_norm = {
        normalize_lookup_name(n)
        for n in (ROOKIE_MUST_HAVE_NAMES or [])
        if isinstance(n, str) and n.strip()
    }

    def _pos_for_curve(name, pdata=None):
        p = str((pdata or {}).get("position") or _curve_pos_map.get(name) or _get_pos(name) or "").upper()
        if p:
            return p
        ident = _resolve_identity_cached(name, preferred_pos="")
        if ident and ident.get("pos"):
            return str(ident.get("pos") or "").upper()
        return ""

    def _player_years_exp_for_curve(pname, pdata=None):
        sid = str((pdata or {}).get("_sleeperId") or _player_id_map.get(pname) or "").strip()
        if not sid:
            ident = _resolve_identity_cached(pname, preferred_pos=_pos_for_curve(pname, pdata))
            if ident and ident.get("id"):
                sid = str(ident.get("id"))
        if not sid:
            return None
        row = SLEEPER_ALL_NFL.get(sid)
        if not isinstance(row, dict):
            return None
        raw = row.get("years_exp", row.get("experience", None))
        try:
            return int(raw)
        except Exception:
            return None

    def _is_rookie_for_curve(pname, pdata=None):
        yrs = _player_years_exp_for_curve(pname, pdata)
        if yrs == 0:
            return True
        return normalize_lookup_name(pname) in _rookie_must_have_norm

    def _asset_universe_key(pname, pdata=None, pos_hint=""):
        if _looks_like_pick_name(pname):
            return "picks"
        pos = str(pos_hint or _pos_for_curve(pname, pdata) or "").upper()
        is_idp = pos in _IDP_POSITIONS
        is_rookie = _is_rookie_for_curve(pname, pdata)
        if is_idp:
            return "idp_rookies" if is_rookie else "idp_veterans"
        return "offense_rookies" if is_rookie else "offense_veterans"

    _asset_universe_cache = {}

    def _asset_universe_cached(pname, pdata=None, pos_hint=""):
        key = f"{str(pname or '')}|{str(pos_hint or '')}"
        if not key:
            return _asset_universe_key(pname, pdata, pos_hint=pos_hint)
        if key in _asset_universe_cache:
            return _asset_universe_cache[key]
        u = _asset_universe_key(pname, pdata, pos_hint=pos_hint)
        _asset_universe_cache[key] = u
        return u

    def _value_economy_target_from_entry(entry):
        if not isinstance(entry, dict):
            return None
        for key in ("_finalAdjusted", "_composite", "_rawComposite"):
            v = entry.get(key)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
        return None

    def _latest_file(directory, pattern):
        try:
            import fnmatch
            if not directory or not os.path.isdir(directory):
                return None
            candidates = [
                os.path.join(directory, n)
                for n in os.listdir(directory)
                if fnmatch.fnmatch(n, pattern)
            ]
            if not candidates:
                return None
            return max(candidates, key=lambda p: os.path.getmtime(p))
        except Exception:
            return None

    def _load_json_file(path):
        try:
            if not path or not os.path.isfile(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _load_rank_curve_reference_payload():
        p = None
        candidate_dirs = [
            os.path.join(SCRIPT_DIR, "data"),
            SCRIPT_DIR,
            os.path.join(BASE_SCRIPT_DIR, "data"),
            BASE_SCRIPT_DIR,
        ]
        for d in candidate_dirs:
            p = _latest_file(d, "dynasty_data_*.json")
            if p:
                break
        if not p:
            return {}, {}, ""
        payload = _load_json_file(p) or {}
        players = payload.get("players", {}) if isinstance(payload.get("players"), dict) else {}
        sleeper = payload.get("sleeper", {}) if isinstance(payload.get("sleeper"), dict) else {}
        pos_map = sleeper.get("positions", {}) if isinstance(sleeper.get("positions"), dict) else {}
        return players, pos_map, str(p)

    _curve_universes = ("offense_veterans", "offense_rookies", "idp_veterans", "idp_rookies", "picks")
    _rank_curve_targets = {u: [] for u in _curve_universes}
    _ref_players, _ref_pos_map, _rank_curve_ref_path = _load_rank_curve_reference_payload()
    for _nm, _pd in (_ref_players or {}).items():
        _val = _value_economy_target_from_entry(_pd)
        if not isinstance(_val, (int, float)) or _val <= 0:
            continue
        _u = _asset_universe_cached(_nm, _pd, pos_hint=_ref_pos_map.get(_nm, ""))
        _rank_curve_targets.setdefault(_u, []).append(float(_val))
    # Conservative fallback if no prior snapshot is available.
    for _nm, _pd in players_json.items():
        _u = _asset_universe_cached(_nm, _pd)
        if len(_rank_curve_targets.get(_u, [])) >= 24:
            continue
        _v = _value_economy_target_from_entry(_pd)
        if isinstance(_v, (int, float)) and _v > 0:
            _rank_curve_targets.setdefault(_u, []).append(float(_v))
    for _u in list(_rank_curve_targets.keys()):
        _rank_curve_targets[_u] = sorted(
            [float(v) for v in _rank_curve_targets.get(_u, []) if isinstance(v, (int, float)) and v > 0],
            reverse=True,
        )

    _rank_curve_sites = set(_rank_sites) | set(_idp_rank_sites)
    _rank_curve_source_ranks = {}  # (site, universe) -> ascending rank list
    for _nm, _pd in players_json.items():
        if not isinstance(_pd, dict):
            continue
        _u = _asset_universe_cached(_nm, _pd)
        for _sk in _rank_curve_sites:
            _rv = _pd.get(_sk)
            if isinstance(_rv, (int, float)) and _rv > 0:
                _rank_curve_source_ranks.setdefault((_sk, _u), []).append(float(_rv))
    for _k in list(_rank_curve_source_ranks.keys()):
        _rank_curve_source_ranks[_k] = sorted(_rank_curve_source_ranks.get(_k, []))

    RANK_CURVE_MIN_SOURCE_COUNT = 10
    RANK_CURVE_MIN_TARGET_COUNT = 24

    def _rank_percentile(rank_value, sorted_ranks):
        ranks = sorted_ranks or []
        if not ranks:
            return 1.0
        n = len(ranks)
        if n <= 1:
            return 0.0
        r = float(rank_value)
        left = bisect.bisect_left(ranks, r)
        right = bisect.bisect_right(ranks, r)
        if left < right:
            pos = (left + right - 1) / 2.0
        elif left <= 0:
            pos = 0.0
        elif left >= n:
            pos = float(n - 1)
        else:
            lo = float(ranks[left - 1])
            hi = float(ranks[left])
            frac = 0.0 if hi <= lo else max(0.0, min(1.0, (r - lo) / (hi - lo)))
            pos = (left - 1) + frac
        return max(0.0, min(1.0, pos / float(max(1, n - 1))))

    def _value_at_percentile_desc(values_desc, pct):
        vals = values_desc or []
        if not vals:
            return None
        if len(vals) == 1:
            return float(vals[0])
        p = max(0.0, min(1.0, float(pct)))
        idx = p * float(len(vals) - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if hi <= lo:
            return float(vals[lo])
        t = idx - lo
        return float(vals[lo] + ((vals[hi] - vals[lo]) * t))

    def _fallback_sparse_rank_value(rank_value, universe_key, site_max=9999.0):
        rank = max(1.0, float(rank_value))
        defaults = {
            "offense_veterans": float(COMPOSITE_SCALE),
            "offense_rookies": 3800.0,
            "idp_veterans": float(IDP_ANCHOR_TOP),
            "idp_rookies": 2800.0,
            "picks": 4200.0,
        }
        targets = _rank_curve_targets.get(universe_key, [])
        top_ref = float(targets[0]) if targets else float(defaults.get(universe_key, site_max or COMPOSITE_SCALE))
        top_ref = max(200.0, min(float(COMPOSITE_SCALE), top_ref))
        exp = 0.68 if "rookies" in universe_key else 0.62
        off = 8.0 if "rookies" in universe_key else 18.0
        val = top_ref * (((rank + off) / (1.0 + off)) ** (-exp))
        floor_mult = 0.10 if "rookies" in universe_key else 0.06
        floor_val = max(1.0, top_ref * floor_mult)
        return max(floor_val, min(float(COMPOSITE_SCALE), float(val)))

    _rank_curve_diagnostics = {
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "referencePath": _rank_curve_ref_path,
        "minSourceCount": RANK_CURVE_MIN_SOURCE_COUNT,
        "minTargetCount": RANK_CURVE_MIN_TARGET_COUNT,
        "universes": {u: {"targetCount": len(_rank_curve_targets.get(u, []))} for u in _curve_universes},
        "sources": {},
    }

    def _calibrated_rank_to_value(dash_key, rank_value, pname, pdata=None, site_max=9999.0, universe_override=None):
        universe_key = universe_override or _asset_universe_cached(pname, pdata)
        source_ranks = _rank_curve_source_ranks.get((dash_key, universe_key), [])
        target_curve = _rank_curve_targets.get(universe_key, [])
        curve_ready = (
            len(source_ranks) >= RANK_CURVE_MIN_SOURCE_COUNT
            and len(target_curve) >= RANK_CURVE_MIN_TARGET_COUNT
        )
        if curve_ready:
            pct = _rank_percentile(rank_value, source_ranks)
            mapped = _value_at_percentile_desc(target_curve, pct)
            if isinstance(mapped, (int, float)) and mapped > 0:
                return float(mapped), universe_key, False
        # Sparse conservative fallback (explicitly logged in diagnostics).
        return float(_fallback_sparse_rank_value(rank_value, universe_key, site_max=site_max)), universe_key, True

    for _sk in sorted(_rank_curve_sites):
        for _u in _curve_universes:
            _src = _rank_curve_source_ranks.get((_sk, _u), [])
            _tgt = _rank_curve_targets.get(_u, [])
            _curve_ready = len(_src) >= RANK_CURVE_MIN_SOURCE_COUNT and len(_tgt) >= RANK_CURVE_MIN_TARGET_COUNT
            _samples = {}
            if _src:
                for _label, _rank in (
                    ("top", _src[0]),
                    ("middle", _src[len(_src) // 2]),
                    ("tail", _src[-1]),
                ):
                    _val, _, _fb = _calibrated_rank_to_value(_sk, _rank, "", None, site_max=max_values.get(_sk, 9999), universe_override=_u)
                    _samples[_label] = {"rank": round(float(_rank), 4), "value": int(round(_val)), "fallback": bool(_fb)}
            _top_v = (_samples.get("top") or {}).get("value")
            _tail_v = (_samples.get("tail") or {}).get("value")
            _spread_ratio = (
                round(float(_top_v) / max(1.0, float(_tail_v)), 3)
                if isinstance(_top_v, (int, float)) and isinstance(_tail_v, (int, float))
                else None
            )
            _suspicious = None
            if isinstance(_spread_ratio, (int, float)):
                if _spread_ratio < 1.35:
                    _suspicious = "compressed_spacing"
                elif _spread_ratio > 280:
                    _suspicious = "inflated_spacing"
            _rank_curve_diagnostics["sources"][f"{_sk}:{_u}"] = {
                "sourceCount": len(_src),
                "targetCount": len(_tgt),
                "curveBuilt": bool(_curve_ready),
                "fallbackUsed": not bool(_curve_ready),
                "examples": _samples,
                "spreadRatioTopToTail": _spread_ratio,
                "suspiciousSpacing": _suspicious,
            }

    _curve_total = len(_rank_curve_diagnostics["sources"])
    _curve_built = sum(1 for _v in _rank_curve_diagnostics["sources"].values() if _v.get("curveBuilt"))
    _curve_fallback = _curve_total - _curve_built
    print(
        f"  [RankCurve] Built {_curve_built}/{_curve_total} source-universe curves "
        f"(fallback {_curve_fallback}); reference={_rank_curve_ref_path or 'current run'}"
    )

    # Build site stats from the same transformed values used by composite math.
    _site_keys_for_stats = set(site_key_map.values()) | set(SITE_WEIGHTS.keys())
    for dash_key in sorted(_site_keys_for_stats):
        if dash_key in _ROOKIE_ONLY_DLF_SITE_KEYS:
            continue
        site_max = max_values.get(dash_key, 9999)
        transformed = []
        for _nm, _pd in players_json.items():
            if not isinstance(_pd, dict):
                continue
            _raw = _pd.get(dash_key)
            if _raw is None or not isinstance(_raw, (int, float)) or _raw <= 0:
                continue
            _is_this_idp_local = _asset_universe_cached(_nm, _pd).startswith("idp_")
            if dash_key in _rank_sites or dash_key in _idp_rank_sites:
                tv, _, _ = _calibrated_rank_to_value(dash_key, _raw, _nm, _pd, site_max=site_max)
            elif dash_key in _idp_value_cap_sites and _is_this_idp_local:
                tv = min(float(_raw), float(IDP_ANCHOR_TOP))
            else:
                tv = float(_raw)
            if isinstance(tv, (int, float)) and tv > 0:
                transformed.append(float(tv))
        if len(transformed) >= 2:
            mean_val = sum(transformed) / len(transformed)
            variance = sum((v - mean_val) ** 2 for v in transformed) / len(transformed)
            stdev_val = variance ** 0.5
            site_stats[dash_key] = {
                "mean": round(mean_val, 2),
                "stdev": round(stdev_val, 2),
                "count": len(transformed),
            }
            if DEBUG:
                print(f"  [Stats] {dash_key}: μ={mean_val:.1f}  σ={stdev_val:.1f}  n={len(transformed)}")

    # ── Compute composite value for every player ──
    _pos_map = SLEEPER_ROSTER_DATA.get("positions", {})
    def _is_te(name):
        pos = _pos_map.get(name, "")
        if pos.upper() == "TE":
            return True
        for k, v in _pos_map.items():
            if k.lower() == name.lower() and v.upper() == "TE":
                return True
        return False

    composites = {}
    def _player_is_idp(pname):
        pos = _pos_map.get(pname, "")
        if not pos:
            nl = pname.lower()
            for k, v in _pos_map.items():
                if k.lower() == nl:
                    pos = v
                    break
        return pos.upper() in _IDP_POSITIONS

    def _coeff_var(vals):
        if not vals or len(vals) < 2:
            return 0.0
        mean = sum(vals) / len(vals)
        if mean <= 0:
            return 0.0
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        return (var ** 0.5) / mean

    def _clampf(v, lo, hi):
        try:
            return max(lo, min(hi, float(v)))
        except Exception:
            return lo

    def _market_confidence(norm_vals, site_count):
        cv = _coeff_var(norm_vals)
        site_score = _clampf(float(site_count) / 8.0, 0.20, 1.00)
        cv_score = _clampf(1.0 - (min(cv, 0.35) / 0.35), 0.20, 1.00)
        conf = _clampf((site_score * 0.65) + (cv_score * 0.35), 0.20, 1.00)
        return conf, cv

    for name, pdata in players_json.items():
        wNorms = []
        canonical_site_values = {}
        max_value_site_raw = 0
        _is_this_idp = _player_is_idp(name)
        _is_this_rookie = _is_rookie_for_curve(name, pdata)
        _has_rookie_only_dlf_signal = False
        _real_idp_market_source_count = 0
        for dash_key, raw_val in pdata.items():
            if raw_val is None or not isinstance(raw_val, (int, float)):
                continue
            if dash_key in _ROOKIE_ONLY_DLF_SITE_KEYS:
                if raw_val > 0:
                    _has_rookie_only_dlf_signal = True
                # Rookie-only DLF sources are implemented as rookie-context signals only.
                # They are excluded for non-rookies so rookie list ranks cannot distort
                # veteran market composites.
                if not _is_this_rookie:
                    continue
            site_stat = site_stats.get(dash_key)
            site_max = max_values.get(dash_key, 9999)
            if site_max <= 0:
                continue

            # Transform rank-only sources into canonical values via universe-specific
            # Fully-Adjusted economy curves. Fallback uses conservative sparse curves.
            if dash_key in _rank_sites or dash_key in _idp_rank_sites:
                site_raw, _u_key, _fb_used = _calibrated_rank_to_value(
                    dash_key,
                    raw_val,
                    name,
                    pdata,
                    site_max=site_max,
                )
            elif dash_key in _idp_value_cap_sites and _is_this_idp:
                # IDPTradeCalc: only cap IDP players at anchor
                site_raw = min(raw_val, IDP_ANCHOR_TOP)
            else:
                site_raw = raw_val

            # TEP boost for TEs on non-TEP sites
            is_te = _is_te(name)
            if is_te and dash_key not in _tep_sites and TEP_MULT > 1:
                site_raw *= TEP_MULT

            if site_raw <= 0:
                continue

            canonical_site_values[dash_key] = int(round(site_raw))

            if _is_this_idp and dash_key in _REAL_IDP_MARKET_SITE_KEYS:
                _real_idp_market_source_count += 1

            # Track cap anchor from value-based sources only.
            # Rank-derived curves are synthetic and can force artificial top-end ties.
            if (
                site_max > 1000
                and dash_key not in _rank_sites
                and dash_key not in _idp_rank_sites
                and (not (_is_this_idp and dash_key in _idp_synthetic_value_sites))
                and site_raw > max_value_site_raw
            ):
                max_value_site_raw = site_raw

            # Z-score normalization
            if site_stat and site_stat["stdev"] > 0:
                z = (site_raw - site_stat["mean"]) / site_stat["stdev"]
                norm = max(0, min(1, (z - Z_FLOOR) / (Z_CEILING - Z_FLOOR)))
            else:
                norm = max(0, min(1, site_raw / site_max))

            wNorms.append((norm, SITE_WEIGHTS.get(dash_key, 1.0)))

        if not wNorms:
            continue

        # Adaptive trimming: remove only true edge outliers at either end.
        if len(wNorms) >= 5:
            sorted_norms = sorted(wNorms, key=lambda x: x[0])
            low_gap = sorted_norms[1][0] - sorted_norms[0][0]
            high_gap = sorted_norms[-1][0] - sorted_norms[-2][0]
            start_idx = 1 if low_gap >= OUTLIER_TRIM_GAP else 0
            end_idx = -1 if high_gap >= OUTLIER_TRIM_GAP else None
            trimmed = sorted_norms[start_idx:end_idx] if end_idx is not None else sorted_norms[start_idx:]
            if not trimmed:
                trimmed = sorted_norms
        else:
            trimmed = wNorms

        w_total = sum(n * w for n, w in trimmed)
        w_sum = sum(w for _, w in trimmed)
        meta_norm = w_total / w_sum if w_sum > 0 else 0

        composite = meta_norm * COMPOSITE_SCALE

        norm_vals = [n for n, _ in wNorms]
        market_conf, cv = _market_confidence(norm_vals, len(wNorms))

        # Elite-separation expansion: consensus top-tier players should stay near ceiling.
        if len(norm_vals) >= 4:
            sorted_vals = sorted(norm_vals)
            mid = len(sorted_vals) // 2
            if len(sorted_vals) % 2:
                median_norm = sorted_vals[mid]
            else:
                median_norm = (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0
            if median_norm >= ELITE_NORM_THRESHOLD:
                agreement = max(0.0, 1.0 - min(cv, 0.30) / 0.30)
                span = min(1.0, (median_norm - ELITE_NORM_THRESHOLD) / (1.0 - ELITE_NORM_THRESHOLD))
                elite_boost = 1.0 + (ELITE_BOOST_MAX * span * agreement * market_conf)
                composite *= elite_boost

        # Single-source discount
        if len(wNorms) == 1:
            single_src_discount = (
                SINGLE_SOURCE_DISCOUNT_MIN
                + ((SINGLE_SOURCE_DISCOUNT_MAX - SINGLE_SOURCE_DISCOUNT_MIN) * market_conf)
            )
            composite *= single_src_discount

        # Cap against value-site ceiling (not rank-derived ceiling).
        cap_limit = max_value_site_raw
        if _is_this_idp and cap_limit > 0:
            # For IDPs, allow a controlled lift toward the anchor when rank sites strongly agree.
            idp_headroom = max(0.0, IDP_ANCHOR_TOP - cap_limit)
            idp_conf_factor = 0.60 + (0.40 * market_conf)
            cap_limit = cap_limit + ((IDP_VALUE_HEADROOM_FRACTION * idp_conf_factor) * idp_headroom)
        if cap_limit > 0 and composite > cap_limit:
            composite = cap_limit

        # Top-end guardrail: synthetic transforms cannot exceed value-site consensus
        # by more than a confidence-gated margin.
        # Phase 3 fix: widened from 4% → 8% for offense so elite players can
        # approach the 9999 ceiling when market confidence is high.
        if cap_limit > 0:
            if _is_this_idp:
                elite_cap = cap_limit * (1.0 + (0.03 * market_conf))
            else:
                elite_cap = cap_limit * (1.0 + (0.08 * market_conf))
            composite = min(composite, elite_cap)

        # Safety rule: rookie-only DLF IDP signals cannot create elevated normal-dynasty values
        # unless at least one real non-rookie IDP market source is present.
        rookie_only_guardrail_applied = False
        if _is_this_idp and _has_rookie_only_dlf_signal and _real_idp_market_source_count <= 0:
            if composite > IDP_ROOKIE_ONLY_NO_MARKET_CAP:
                composite = IDP_ROOKIE_ONLY_NO_MARKET_CAP
                rookie_only_guardrail_applied = True

        composite = max(1, round(composite))
        composites[name] = {
            "value": composite,
            "sites": len(wNorms),
            "canonicalSiteValues": canonical_site_values,
            "marketConfidence": round(market_conf, 4),
            "dispersionCV": round(cv, 6),
            "idpRealMarketSources": int(_real_idp_market_source_count),
            "rookieOnlyDlfGuardrailApplied": bool(rookie_only_guardrail_applied),
        }

    # Add composite to players_json
    for name, comp in composites.items():
        players_json[name]["_composite"] = comp["value"]
        players_json[name]["_sites"] = comp["sites"]
        players_json[name]["_canonicalSiteValues"] = dict(comp.get("canonicalSiteValues") or {})
        players_json[name]["_marketConfidence"] = comp.get("marketConfidence", 0.5)
        players_json[name]["_marketDispersionCV"] = comp.get("dispersionCV", 0.0)
        players_json[name]["_idpRealMarketSources"] = int(comp.get("idpRealMarketSources", 0) or 0)
        players_json[name]["_rookieOnlyDlfGuardrailApplied"] = bool(comp.get("rookieOnlyDlfGuardrailApplied", False))

    # ── Hard floor: seed rankings with at least top 400 KTC players ──
    _ktc_seed_added = 0
    _ktc_full = FULL_DATA.get("KTC", {}) if isinstance(FULL_DATA.get("KTC"), dict) else {}
    _ktc_ranked = sorted(
        [
            (clean_name(n), float(v))
            for n, v in _ktc_full.items()
            if isinstance(v, (int, float)) and v > 0 and not _looks_like_pick_name(n)
        ],
        key=lambda x: -x[1],
    )[:400]
    for clean_nm, ktc_val in _ktc_ranked:
        if not clean_nm:
            continue
        canonical = _canonical_map.get(clean_nm, clean_nm)
        pref_pos = _get_pos(canonical) or _get_pos(clean_nm)
        ident = _resolve_identity_cached(canonical, preferred_pos=pref_pos)
        if ident and ident.get("name"):
            canonical = ident.get("name") or canonical
            if ident.get("pos"):
                pref_pos = ident.get("pos")
        entry = players_json.get(canonical, {})
        if not _has_numeric_value(entry.get("ktc")):
            entry["ktc"] = int(round(float(ktc_val)))
        if ident and ident.get("id"):
            sid = str(ident.get("id"))
            entry["_sleeperId"] = sid
            _player_id_map[canonical] = sid
            _id_to_player[sid] = canonical
        if pref_pos and canonical not in _pos_map:
            _pos_map[canonical] = pref_pos
        if "_composite" not in entry and _has_numeric_value(entry.get("ktc")):
            entry["_composite"] = int(round(float(entry.get("ktc"))))
            entry["_sites"] = max(1, int(entry.get("_sites", 0) or 0))
            _ktc_seed_added += 1
        players_json[canonical] = entry

    if _ktc_seed_added:
        print(f"  [KTC Seed] Ensured top-400 baseline by adding {_ktc_seed_added} KTC-only entries")

    # ── Pick model reset/rebuild (2026 rookie-proxy centered) ──
    # Legacy pick anchors are only used as outside-market inputs for 2027/2028 rounds 1-4.
    _legacy_pick_anchors = pick_anchors if isinstance(pick_anchors, dict) else {}
    _pick_suffix_local = _pick_suffix

    def _player_years_exp_local(pname, pdata):
        sid = str((pdata or {}).get("_sleeperId") or _player_id_map.get(pname) or "").strip()
        if not sid:
            ident = _resolve_identity_cached(pname, preferred_pos=_get_pos(pname))
            if ident and ident.get("id"):
                sid = str(ident.get("id"))
        if not sid:
            return None
        row = SLEEPER_ALL_NFL.get(sid)
        if not isinstance(row, dict):
            return None
        raw = row.get("years_exp", row.get("experience", None))
        try:
            return int(raw)
        except Exception:
            return None

    def _median(vals, default_val):
        arr = sorted(v for v in vals if isinstance(v, (int, float)) and v > 0)
        if not arr:
            return float(default_val)
        mid = len(arr) // 2
        if len(arr) % 2:
            return float(arr[mid])
        return float((arr[mid - 1] + arr[mid]) / 2.0)

    def _tier_for_slot(slot):
        if 1 <= slot <= 4:
            return "early"
        if 5 <= slot <= 8:
            return "mid"
        return "late"

    def _slot_range_for_tier(tier):
        t = str(tier or "mid").lower()
        if t == "early":
            return range(1, 5)
        if t == "mid":
            return range(5, 9)
        return range(9, 13)

    def _fmt_site_val(v):
        if not isinstance(v, (int, float)) or v <= 0:
            return None
        return int(round(float(v)))

    def _legacy_pick_site_value(site_key, year, round_num, slot=None, tier=None):
        smap = _legacy_pick_anchors.get(site_key, {})
        if not isinstance(smap, dict):
            return None
        if slot is not None:
            k1 = f"{year} {round_num}.{int(slot):02d}"
            k2 = f"{year} {round_num}.{int(slot)}"
            for k in (k1, k2):
                v = _pick_value(smap.get(k))
                if v is not None:
                    return v
            if tier is None:
                tier = _tier_for_slot(int(slot))
        if tier is not None:
            tk = f"{year} {str(tier).capitalize()} {round_num}{_pick_suffix_local(round_num)}"
            v = _pick_value(smap.get(tk))
            if v is not None:
                return v
        return None

    def _site_weight_for_pick(site_key):
        return float(SITE_WEIGHTS.get(site_key, 1.0))

    def _weighted_site_blend(site_vals):
        if not isinstance(site_vals, dict) or not site_vals:
            return None
        num = 0.0
        den = 0.0
        for sk, sv in site_vals.items():
            v = _pick_value(sv)
            if v is None:
                continue
            w = _site_weight_for_pick(sk)
            num += v * w
            den += w
        if den <= 0:
            return None
        return num / den

    # Remove all existing pick rows before rebuilding from the new model.
    for _nm in list(players_json.keys()):
        if _looks_like_pick_name(_nm):
            players_json.pop(_nm, None)

    # 2026 slots = direct one-to-one mapping to top 72 rookie composites.
    # Rookies are sourced from either:
    #  - Sleeper years_exp == 0, or
    #  - must-have rookie list (if the player has at least one site value).
    _rookie_must_have_norm = {
        normalize_lookup_name(n)
        for n in (ROOKIE_MUST_HAVE_NAMES or [])
        if n
    }
    _rookie_site_keys = tuple(
        k for k in (
            "ktc", "fantasyCalc", "dynastyDaddy", "fantasyPros", "draftSharks", "yahoo",
            "dynastyNerds", "dlfSf", "dlfIdp", "dlfRsf", "dlfRidp",
            "idpTradeCalc", "pffIdp", "fantasyProsIdp"
        )
    )

    def _has_site_signal_for_rookie(entry):
        if not isinstance(entry, dict):
            return False
        for sk in _rookie_site_keys:
            v = entry.get(sk)
            if isinstance(v, (int, float)) and v > 0:
                return True
        return False

    def _is_rookie_candidate(pname, pdata):
        yrs = _player_years_exp_local(pname, pdata)
        if yrs == 0:
            return True
        return normalize_lookup_name(pname) in _rookie_must_have_norm

    rookie_pool = []
    rookie_pool_year0 = 0
    rookie_pool_manual = 0
    for pname, pdata in players_json.items():
        if not isinstance(pdata, dict):
            continue
        comp = pdata.get("_composite")
        if not isinstance(comp, (int, float)) or comp <= 0:
            continue
        if _looks_like_pick_name(pname):
            continue
        pos = _get_pos(pname)
        if str(pos).upper() == "K":
            continue
        if not _has_site_signal_for_rookie(pdata):
            continue
        if _is_rookie_candidate(pname, pdata):
            yrs = _player_years_exp_local(pname, pdata)
            if yrs == 0:
                rookie_pool_year0 += 1
            elif normalize_lookup_name(pname) in _rookie_must_have_norm:
                rookie_pool_manual += 1
            rookie_pool.append((pname, int(round(comp))))
    rookie_pool.sort(key=lambda x: -x[1])
    if DEBUG:
        print(
            f"  [Pick Model] 2026 rookie pool candidates: {len(rookie_pool)} "
            f"(years_exp==0: {rookie_pool_year0}, must-have matched: {rookie_pool_manual})"
        )

    rookie_slot_vals = []
    for _, rv in rookie_pool[:72]:
        rookie_slot_vals.append(max(1, int(round(rv))))
    if not rookie_slot_vals:
        rookie_slot_vals = [2500]
    while len(rookie_slot_vals) < 72:
        last = rookie_slot_vals[-1]
        rookie_slot_vals.append(max(1, int(round(last * 0.94))))

    base_2026_slot = {}  # (round, slot) -> value
    for idx in range(72):
        r = (idx // 12) + 1
        s = (idx % 12) + 1
        base_2026_slot[(r, s)] = int(rookie_slot_vals[idx])

    def _tier_avg_from_slots(slot_map, round_num, tier):
        vals = []
        for s in _slot_range_for_tier(tier):
            v = slot_map.get((round_num, s))
            if isinstance(v, (int, float)) and v > 0:
                vals.append(float(v))
        if not vals:
            return None
        return sum(vals) / len(vals)

    # Real pick-anchor sources available from ingestion (site-specific evidence).
    # Used to avoid stamping synthetic uniform values across multiple sites.
    _legacy_pick_site_keys = [
        sk for sk in (
            "ktc", "fantasyCalc", "dynastyDaddy", "fantasyPros", "draftSharks", "yahoo",
            "dynastyNerds", "dlfSf", "dlfIdp", "dlfRsf", "dlfRidp",
            "idpTradeCalc", "pffIdp", "fantasyProsIdp"
        )
        if sk in _legacy_pick_anchors
    ]

    # Outside-market tier values for 2027/2028 rounds 1-4.
    outside_site_keys = [
        sk for sk in ("ktc", "fantasyCalc", "dynastyDaddy", "fantasyPros", "yahoo", "idpTradeCalc")
        if sk in _legacy_pick_anchors
    ]
    outside_tier = {}  # (year, round, tier) -> {"siteVals":{}, "blend":float|None}
    for year in (2027, 2028):
        for rnd in range(1, 5):
            for tier in ("early", "mid", "late"):
                site_vals = {}
                for sk in outside_site_keys:
                    sv = _legacy_pick_site_value(sk, year, rnd, tier=tier)
                    if sv is None:
                        slot_vals = []
                        for slot in _slot_range_for_tier(tier):
                            mv = _legacy_pick_site_value(sk, year, rnd, slot=slot, tier=tier)
                            if mv is not None:
                                slot_vals.append(mv)
                        if slot_vals:
                            sv = sum(slot_vals) / len(slot_vals)
                    if sv is not None:
                        site_vals[sk] = float(sv)
                outside_tier[(year, rnd, tier)] = {
                    "siteVals": site_vals,
                    "blend": _weighted_site_blend(site_vals),
                }

    # Discount calibration from rounds 1-4 outside markets relative to 2026 rookie-proxy base.
    discount_by_year = {2027: 0.84, 2028: 0.70}
    for year in (2027, 2028):
        ratios = []
        for rnd in range(1, 5):
            for tier in ("early", "mid", "late"):
                base = _tier_avg_from_slots(base_2026_slot, rnd, tier)
                ext = outside_tier.get((year, rnd, tier), {}).get("blend")
                if isinstance(base, (int, float)) and base > 0 and isinstance(ext, (int, float)) and ext > 0:
                    ratios.append(ext / base)
        if ratios:
            med = _median(ratios, discount_by_year[year])
            if year == 2027:
                discount_by_year[year] = max(0.60, min(0.95, med))
            else:
                discount_by_year[year] = max(0.45, min(0.85, med))

    rebuilt_pick_entries = {}   # players_json labels -> entry
    rebuilt_pick_anchors = {}   # site -> canonical pick key (no "Pick")

    def _put_pick(label, canonical_key, value, site_vals):
        v = max(1, int(round(float(value))))
        e = {}
        if isinstance(site_vals, dict):
            for sk, sv in site_vals.items():
                if sk in PICK_VALUE_EXCLUDED_SITES:
                    continue
                fv = _fmt_site_val(sv)
                if fv is not None:
                    e[sk] = fv
                    rebuilt_pick_anchors.setdefault(sk, {})[canonical_key] = fv
        if "ktc" not in e:
            e["ktc"] = v
            rebuilt_pick_anchors.setdefault("ktc", {})[canonical_key] = v
        e["_composite"] = v
        e["_sites"] = max(1, sum(1 for kk, vv in e.items() if kk and kk[0] != "_" and _has_numeric_value(vv)))
        rebuilt_pick_entries[label] = e

    # Year 2026: direct rookie-slot mapping.
    for rnd in range(1, 7):
        for slot in range(1, 13):
            val = base_2026_slot.get((rnd, slot), 1)
            slot_label = f"2026 Pick {rnd}.{slot:02d}"
            slot_key = f"2026 {rnd}.{slot:02d}"
            site_vals = {}
            for sk in _legacy_pick_site_keys:
                sv = _legacy_pick_site_value(sk, 2026, rnd, slot=slot, tier=_tier_for_slot(slot))
                if sv is not None:
                    site_vals[sk] = float(sv)
            _put_pick(slot_label, slot_key, val, site_vals)

        for tier in ("early", "mid", "late"):
            tval = _tier_avg_from_slots(base_2026_slot, rnd, tier) or 1
            tier_label = f"2026 {tier.capitalize()} {rnd}{_pick_suffix_local(rnd)}"
            tier_key = tier_label
            site_vals = {}
            for sk in _legacy_pick_site_keys:
                sv = _legacy_pick_site_value(sk, 2026, rnd, tier=tier)
                if sv is None:
                    slot_vals = []
                    for slot in _slot_range_for_tier(tier):
                        mv = _legacy_pick_site_value(sk, 2026, rnd, slot=slot, tier=tier)
                        if mv is not None:
                            slot_vals.append(mv)
                    if slot_vals:
                        sv = sum(slot_vals) / len(slot_vals)
                if sv is not None:
                    site_vals[sk] = float(sv)
            _put_pick(tier_label, tier_key, tval, site_vals)

    # Years 2027/2028: tier-first model only (no slot-specific rows),
    # with rounds 5-6 internal curve from 2026 structure + calibrated discounts.
    for year in (2027, 2028):
        y_disc = float(discount_by_year.get(year, 0.70 if year == 2028 else 0.84))
        for rnd in range(1, 7):
            tier_values = {}
            tier_site_values = {}
            for tier in ("early", "mid", "late"):
                base_tier = _tier_avg_from_slots(base_2026_slot, rnd, tier) or 1
                ext = outside_tier.get((year, rnd, tier), {})
                ext_blend = ext.get("blend")
                ext_site_vals = dict(ext.get("siteVals") or {})

                if rnd <= 2:
                    # First two rounds: outside-market led, with discounted 2026 anchor as stabilizer.
                    if isinstance(ext_blend, (int, float)) and ext_blend > 0:
                        model_val = (0.75 * float(ext_blend)) + (0.25 * (base_tier * y_disc))
                    else:
                        model_val = base_tier * y_disc
                elif rnd <= 4:
                    # Rounds 3-4: integrate available outside data in same weighted framework.
                    if isinstance(ext_blend, (int, float)) and ext_blend > 0:
                        model_val = (0.65 * float(ext_blend)) + (0.35 * (base_tier * y_disc))
                    else:
                        model_val = base_tier * y_disc
                else:
                    # Rounds 5-6: internal curve from 2026 rookie structure + calibrated year discount.
                    model_val = base_tier * y_disc

                final_val = max(1, int(round(model_val)))
                tier_values[tier] = final_val
                tier_site_values[tier] = ext_site_vals

                tier_label = f"{year} {tier.capitalize()} {rnd}{_pick_suffix_local(rnd)}"
                tier_key = tier_label
                _put_pick(tier_label, tier_key, final_val, ext_site_vals)

    # Remove stale future-year slot picks from earlier raw ingestion paths.
    _future_slot_rx = re.compile(r"^202[78]\s+(PICK\s+)?[1-6]\.(0?[1-9]|1[0-2])$", re.IGNORECASE)
    _removed_future_slot_rows = 0
    for _pick_name in list(players_json.keys()):
        if _future_slot_rx.match(str(_pick_name).strip()):
            players_json.pop(_pick_name, None)
            _removed_future_slot_rows += 1
    if DEBUG and _removed_future_slot_rows:
        print(f"  [Pick Model] Removed {_removed_future_slot_rows} future-year slot pick rows (2027/2028 tier-only).")

    # Attach rebuilt picks and overwrite exported pick anchors.
    players_json.update(rebuilt_pick_entries)
    pick_anchors = rebuilt_pick_anchors
    pick_anchors_raw = dict(rebuilt_pick_anchors)
    print(
        f"  [Pick Model] Rebuilt {len(rebuilt_pick_entries)} pick assets "
        f"(2026 rookie-proxy + 2027/2028 tier model; discounts y+1={discount_by_year.get(2027, 0):.3f}, "
        f"y+2={discount_by_year.get(2028, 0):.3f})"
    )

    # ── Roster guarantee: every rostered player gets a value/rank entry ──
    _fallback_site_keys = ("ktc", "fantasyCalc", "dynastyDaddy", "fantasyPros", "yahoo", "idpTradeCalc")
    _rostered_missing_added = 0
    _rostered_fallback_applied = 0

    def _fallback_site_values_for_entry(entry, pos_hint=""):
        vals = []
        has_rookie_only_dlf = False
        has_real_idp_market = False
        is_idp_pos = str(pos_hint or "").upper() in _IDP_POSITIONS
        for _k, _v in (entry or {}).items():
            if not _k or str(_k).startswith("_"):
                continue
            if not isinstance(_v, (int, float)) or _v <= 0:
                continue
            if _k in _ROOKIE_ONLY_DLF_SITE_KEYS:
                has_rookie_only_dlf = True
                continue
            vals.append(float(_v))
            if is_idp_pos and _k in _REAL_IDP_MARKET_SITE_KEYS:
                has_real_idp_market = True
        return vals, has_rookie_only_dlf, has_real_idp_market

    _pos_floor = {}
    for _name, _pdata in players_json.items():
        if not isinstance(_pdata, dict) or _looks_like_pick_name(_name):
            continue
        _v = _pdata.get("_composite")
        if not isinstance(_v, (int, float)) or _v <= 0:
            continue
        _p = _get_pos(_name)
        _pos_floor.setdefault(_p, []).append(float(_v))
    for _p, _vals in list(_pos_floor.items()):
        _pos_floor[_p] = int(round(_median(_vals, 1.0) * 0.35)) if _vals else 1
        _pos_floor[_p] = max(1, _pos_floor[_p])
    _global_floor = max(1, int(round(_median([
        float(p.get("_composite")) for n, p in players_json.items()
        if (
            isinstance(p, dict)
            and not _looks_like_pick_name(n)
            and isinstance(p.get("_composite"), (int, float))
            and p.get("_composite") > 0
        )
    ], 800.0) * 0.20)))

    # Pre-build reverse index: normalized name → first matching player key.
    # Replaces O(N*M) inner-loop scans with O(1) dict lookups.
    _norm_to_player_key: dict[str, str] = {}
    for _pn in players_json.keys():
        _nk = normalize_lookup_name(_pn)
        if _nk and _nk not in _norm_to_player_key:
            _norm_to_player_key[_nk] = _pn

    for raw_name in SLEEPER_PLAYERS:
        clean_nm = clean_name(raw_name)
        if not clean_nm:
            continue

        existing_key = None
        if clean_nm in players_json:
            existing_key = clean_nm
        else:
            can = _canonical_map.get(clean_nm, clean_nm)
            if can in players_json:
                existing_key = can
            else:
                norm = normalize_lookup_name(clean_nm)
                existing_key = _norm_to_player_key.get(norm)

        target_name = existing_key or _canonical_map.get(clean_nm, clean_nm)
        pref_pos = _get_pos(target_name) or _get_pos(clean_nm)
        ident = _resolve_identity_cached(target_name, preferred_pos=pref_pos)
        if ident and ident.get("name"):
            target_name = ident.get("name") or target_name
            if ident.get("pos"):
                pref_pos = ident.get("pos")

        entry = players_json.get(target_name, {})
        if not entry:
            _rostered_missing_added += 1

        # Try to populate fallback site values if missing.
        sid = str(entry.get("_sleeperId") or (ident.get("id") if ident else "") or _player_id_map.get(target_name) or "").strip()
        for sk in _fallback_site_keys:
            if _has_numeric_value(entry.get(sk)):
                continue
            cand, val, _ = _find_site_candidate(
                sk,
                target_name,
                target_pos=pref_pos,
                target_sid=sid,
                allow_fuzzy=True,
            )
            if cand and val is not None:
                fv = _fmt_site_value(val)
                if fv is not None:
                    entry[sk] = fv

        if ident and ident.get("id"):
            sid = str(ident.get("id"))
            entry["_sleeperId"] = sid
            _player_id_map[target_name] = sid
            _id_to_player[sid] = target_name
        if pref_pos and target_name not in _pos_map:
            _pos_map[target_name] = pref_pos

        if not isinstance(entry.get("_composite"), (int, float)) or entry.get("_composite", 0) <= 0:
            site_vals, has_rookie_only_dlf, has_real_idp_market = _fallback_site_values_for_entry(entry, pref_pos)
            if site_vals:
                comp_val = int(round(sum(site_vals) / len(site_vals)))
            else:
                comp_val = _pos_floor.get(pref_pos, _global_floor)
            if (
                str(pref_pos or "").upper() in _IDP_POSITIONS
                and has_rookie_only_dlf
                and not has_real_idp_market
            ):
                comp_val = min(comp_val, IDP_ROOKIE_ONLY_NO_MARKET_CAP)
                entry["_rookieOnlyDlfGuardrailApplied"] = True
            comp_val = max(1, int(comp_val))
            entry["_composite"] = comp_val
            entry["_sites"] = max(1, len(site_vals))
            entry["_fallbackValue"] = True
            entry["_fallbackReason"] = "rostered_guarantee"
            _rostered_fallback_applied += 1
        elif not isinstance(entry.get("_sites"), int) or entry.get("_sites", 0) <= 0:
            site_vals, _, _ = _fallback_site_values_for_entry(entry, pref_pos)
            entry["_sites"] = max(1, len(site_vals))

        players_json[target_name] = entry
        # Keep reverse index current for the rookie guarantee phase that follows.
        _tn_norm = normalize_lookup_name(target_name)
        if _tn_norm and _tn_norm not in _norm_to_player_key:
            _norm_to_player_key[_tn_norm] = target_name

    if _rostered_missing_added or _rostered_fallback_applied:
        print(
            f"  [Roster Guarantee] Added {_rostered_missing_added} missing rostered players, "
            f"applied fallback values to {_rostered_fallback_applied}"
        )

    # Must-have rookie guarantee: ensure every listed must-have rookie exists
    # in players_json with at least a fallback composite value.
    _must_have_added = 0
    _must_have_fallback = 0
    _must_have_curve = [max(1, int(round(rv))) for _, rv in rookie_pool]
    if not _must_have_curve:
        _must_have_curve = [2500]
    _target_curve_len = max(72, len(ROOKIE_MUST_HAVE_NAMES or []))
    while len(_must_have_curve) < _target_curve_len:
        _last = _must_have_curve[-1]
        _must_have_curve.append(max(1, int(round(_last * 0.94))))

    _must_have_order = {}
    for _idx, _nm in enumerate(ROOKIE_MUST_HAVE_NAMES or []):
        _nn = normalize_lookup_name(_nm)
        if _nn and _nn not in _must_have_order:
            _must_have_order[_nn] = _idx

    for _raw_name in (ROOKIE_MUST_HAVE_NAMES or []):
        _clean_nm = clean_name(_raw_name)
        if not _clean_nm:
            continue

        _existing_key = None
        if _clean_nm in players_json:
            _existing_key = _clean_nm
        else:
            _norm = normalize_lookup_name(_clean_nm)
            _existing_key = _norm_to_player_key.get(_norm)

        _target_name = _existing_key or _canonical_map.get(_clean_nm, _clean_nm)
        _pref_pos = _get_pos(_target_name) or _get_pos(_clean_nm)
        _ident = _resolve_identity_cached(_target_name, preferred_pos=_pref_pos)
        if _ident and _ident.get("name"):
            _ident_name = clean_name(_ident.get("name") or "")
            _match_source = _existing_key or _clean_nm
            _match_ok = bool(_ident_name) and (
                normalize_lookup_name(_ident_name) == normalize_lookup_name(_match_source)
            )
            if _match_ok:
                _target_name = _ident_name
                if _ident.get("pos"):
                    _pref_pos = _ident.get("pos")
            else:
                # Do not remap must-have prospects to unrelated NFL players via fuzzy identity.
                _ident = None

        _entry = players_json.get(_target_name, {})
        if not isinstance(_entry, dict):
            _entry = {}

        if not isinstance(_entry.get("_composite"), (int, float)) or _entry.get("_composite", 0) <= 0:
            _ord = _must_have_order.get(normalize_lookup_name(_clean_nm), len(_must_have_curve) - 1)
            _ord = max(0, min(_ord, len(_must_have_curve) - 1))
            _seed = max(1, int(round(_must_have_curve[_ord])))
            _entry["_composite"] = _seed
            _site_vals, _, _ = _fallback_site_values_for_entry(_entry, _pref_pos)
            _entry["_sites"] = max(1, len(_site_vals))
            _entry["_fallbackValue"] = True
            _entry["_fallbackReason"] = "must_have_rookie_guarantee"
            _must_have_fallback += 1

        _must_have_hint = _must_have_rookie_bucket(_target_name) or _must_have_rookie_bucket(_clean_nm)
        if _ident and _ident.get("id"):
            _sid = str(_ident["id"])
            _entry["_sleeperId"] = _sid
            _player_id_map[_target_name] = _sid
            _id_to_player[_sid] = _target_name
        if _pref_pos and _target_name not in _pos_map:
            _pos_map[_target_name] = _pref_pos
        if _must_have_hint:
            _entry["_positionHint"] = _must_have_hint
            _entry["_mustHaveRookiePos"] = _must_have_hint
            _entry["_assetClass"] = "idp" if _must_have_hint in {"DL", "LB", "DB"} else "offense"
            _entry["position"] = _must_have_hint
            if _target_name not in _pos_map:
                _pos_map[_target_name] = _must_have_hint

        if _existing_key is None:
            _must_have_added += 1
        players_json[_target_name] = _entry

    if _must_have_added or _must_have_fallback:
        print(
            f"  [Rookie Guarantee] Added {_must_have_added} must-have rookies, "
            f"applied fallback values to {_must_have_fallback}"
        )

    # Persist rookie visibility metadata for dashboard filtering/debugging.
    _years_exp_tagged = 0
    _rookie_tagged = 0
    for _name, _pdata in players_json.items():
        if not isinstance(_pdata, dict) or _looks_like_pick_name(_name):
            continue
        _yrs = _player_years_exp_local(_name, _pdata)
        if isinstance(_yrs, int) and _yrs >= 0:
            _pdata["_yearsExp"] = int(_yrs)
            _years_exp_tagged += 1
            if _yrs == 0:
                _pdata["_isRookie"] = True
                _rookie_tagged += 1
        elif normalize_lookup_name(_name) in _rookie_must_have_norm:
            # Must-have rookies that are not in Sleeper's NFL player DB yet.
            _pdata["_isRookie"] = True
            _rookie_tagged += 1

    # Final must-have rookie position enforcement. Do this after fallback creation and
    # rookie tagging so defensive prospects cannot drift back into generic offense entries.
    for _name, _pdata in players_json.items():
        if not isinstance(_pdata, dict) or _looks_like_pick_name(_name):
            continue
        _hint = _must_have_rookie_bucket(_name)
        if not _hint:
            continue
        _pdata["_positionHint"] = _hint
        _pdata["_mustHaveRookiePos"] = _hint
        _pdata["position"] = _hint
        _pdata["_assetClass"] = "idp" if _hint in {"DL", "LB", "DB"} else "offense"
        if _name not in _pos_map:
            _pos_map[_name] = _hint

    if DEBUG:
        print(f"  [Rookies] Tagged years_exp for {_years_exp_tagged} players; rookie-flagged {_rookie_tagged}")

    # Set _rawComposite and _finalAdjusted directly from _composite.
    for name, pdata in players_json.items():
        if not isinstance(pdata, dict):
            continue
        raw_comp = pdata.get("_composite")
        if not isinstance(raw_comp, (int, float)) or raw_comp <= 0:
            continue
        pdata["_rawComposite"] = int(round(raw_comp))
        pdata["_finalAdjusted"] = int(round(raw_comp))

    if composites:
        top5 = sorted(composites.items(), key=lambda x: -x[1]["value"])[:5]
        print(f"  [Composite] Computed for {len(composites)} players")
        print(f"  [Composite] Top 5: {[(n, c['value']) for n, c in top5]}")

    # Coverage guardrails for deep dynasty + IDP leagues.
    def _coverage_counts():
        off = 0
        idp = 0
        for n, pdata in players_json.items():
            if not isinstance(pdata, dict) or "_composite" not in pdata:
                continue
            if _looks_like_pick_name(n):
                continue
            pos = _get_pos(n)
            if pos in _OFF_POSITIONS:
                off += 1
            elif pos in _IDP_POSITIONS:
                idp += 1
        return off, idp

    offensive_count, idp_count = _coverage_counts()
    idp_floor_target = max(TARGET_IDP_POOL, MIN_IDP_POOL_FLOOR)

    # Hard-floor pass: if IDP count is low, force-classify IDP-signal-only players.
    if idp_count < idp_floor_target:
        promoted = 0
        for n, pdata in players_json.items():
            if not isinstance(pdata, dict) or "_composite" not in pdata:
                continue
            if _looks_like_pick_name(n):
                continue
            if _get_pos(n) in _IDP_POSITIONS:
                continue
            has_idp_signal = any(isinstance(pdata.get(k), (int, float)) for k in ("pffIdp", "fantasyProsIdp", "draftSharksIdp"))
            has_off_signal = any(
                isinstance(pdata.get(k), (int, float))
                for k in ("ktc", "fantasyCalc", "dynastyDaddy", "fantasyPros", "draftSharks", "yahoo", "dynastyNerds", "dlfSf")
            )
            if has_idp_signal and not has_off_signal:
                _pos_map[n] = "LB"
                promoted += 1
        if promoted:
            SLEEPER_ROSTER_DATA["positions"] = _pos_map
            offensive_count, idp_count = _coverage_counts()
            print(f"  [Coverage] IDP hard-floor promoted {promoted} players; IDP count now {idp_count}")

    print(f"  [Coverage] Offensive composite players: {offensive_count} (target {TARGET_OFFENSIVE_POOL})")
    print(f"  [Coverage] IDP composite players: {idp_count} (target {TARGET_IDP_POOL}, floor {idp_floor_target})")
    if offensive_count < TARGET_OFFENSIVE_POOL:
        print(f"  [Coverage] ⚠ Offensive pool below target by {TARGET_OFFENSIVE_POOL - offensive_count}")
    if idp_count < idp_floor_target:
        print(f"  [Coverage] ⚠ IDP pool below floor by {idp_floor_target - idp_count}")

    def _player_years_exp(pname, pdata):
        sid = str((pdata or {}).get("_sleeperId") or _player_id_map.get(pname) or "").strip()
        if not sid:
            ident = _resolve_identity_cached(pname, preferred_pos=_get_pos(pname))
            if ident and ident.get("id"):
                sid = str(ident.get("id"))
        if not sid:
            return None
        row = SLEEPER_ALL_NFL.get(sid)
        if not isinstance(row, dict):
            return None
        raw = row.get("years_exp", row.get("experience", None))
        try:
            return int(raw)
        except Exception:
            return None

    def _is_non_rookie(pname, pdata):
        yrs = _player_years_exp(pname, pdata)
        if yrs is None:
            return True
        return yrs > 0

    def _diagnose_missing_site(pname, pdata, site_key, pos):
        sid = str((pdata or {}).get("_sleeperId") or _player_id_map.get(pname) or "").strip()
        scraper_name = _dash_to_scraper.get(site_key)
        if not scraper_name or not isinstance(FULL_DATA.get(scraper_name), dict):
            return {"reason": "site_unavailable"}

        cand, _, method = _find_site_candidate(
            site_key,
            pname,
            target_pos=pos,
            target_sid=sid,
            allow_fuzzy=False,
        )
        if cand:
            return {"reason": "likely_name_mismatch", "method": method, "candidate": cand}

        cand, _, method = _find_site_candidate(
            site_key,
            pname,
            target_pos=pos,
            target_sid=sid,
            allow_fuzzy=True,
        )
        if cand:
            return {"reason": "likely_name_mismatch", "method": method, "candidate": cand}
        if method == "identity_mismatch":
            return {"reason": "identity_mismatch"}
        return {"reason": "not_in_source"}

    def _audit_top_group(candidates, expected_sites, top_n, min_sources):
        evaluated = candidates[:top_n]
        deficits = []
        missing_by_site = {k: 0 for k in expected_sites}
        reason_counts = {}

        for name, pdata, pos, comp in evaluated:
            present_sites = [k for k in expected_sites if _has_numeric_value(pdata.get(k))]
            if len(present_sites) >= min_sources:
                continue

            missing_sites = [k for k in expected_sites if k not in present_sites]
            diagnostics = {}
            for sk in missing_sites:
                diag = _diagnose_missing_site(name, pdata, sk, pos)
                diagnostics[sk] = diag
                missing_by_site[sk] = missing_by_site.get(sk, 0) + 1
                reason = diag.get("reason", "unknown")
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

            deficits.append({
                "name": name,
                "pos": pos,
                "composite": int(round(comp)),
                "siteCount": len(present_sites),
                "missingSites": missing_sites,
                "missingDiagnostics": diagnostics,
            })

        missing_by_site = {k: v for k, v in missing_by_site.items() if v > 0}
        return {
            "evaluated": len(evaluated),
            "requiredSources": int(min_sources),
            "expectedSites": list(expected_sites),
            "passPlayers": max(0, len(evaluated) - len(deficits)),
            "deficitPlayers": len(deficits),
            "missingBySite": missing_by_site,
            "missingReasons": reason_counts,
            "deficitSample": deficits[:40],
        }

    _off_candidates = []
    _idp_candidates = []
    for pname, pdata in players_json.items():
        if not isinstance(pdata, dict):
            continue
        comp = pdata.get("_composite")
        if not isinstance(comp, (int, float)) or comp <= 0:
            continue
        if _looks_like_pick_name(pname):
            continue
        pos = _get_pos(pname)
        if pos in _OFF_POSITIONS:
            if _is_non_rookie(pname, pdata):
                _off_candidates.append((pname, pdata, pos, float(comp)))
        elif pos in _IDP_POSITIONS:
            _idp_candidates.append((pname, pdata, pos, float(comp)))

    _off_candidates.sort(key=lambda x: -x[3])
    _idp_candidates.sort(key=lambda x: -x[3])

    coverage_audit = {
        "thresholds": {
            "topOffenseN": int(TOP_OFF_COVERAGE_AUDIT_N),
            "topIdpN": int(TOP_IDP_COVERAGE_AUDIT_N),
            "offenseMinSources": int(TOP_OFF_MIN_SOURCES),
            "idpMinSources": int(TOP_IDP_MIN_SOURCES),
        },
        "expectedSites": {
            "offense": list(TOP_OFF_EXPECTED_SITE_KEYS),
            "idp": list(TOP_IDP_EXPECTED_SITE_KEYS),
        },
        "repair": _coverage_repair_stats,
        "offense": _audit_top_group(
            _off_candidates,
            TOP_OFF_EXPECTED_SITE_KEYS,
            TOP_OFF_COVERAGE_AUDIT_N,
            TOP_OFF_MIN_SOURCES,
        ),
        "idp": _audit_top_group(
            _idp_candidates,
            TOP_IDP_EXPECTED_SITE_KEYS,
            TOP_IDP_COVERAGE_AUDIT_N,
            TOP_IDP_MIN_SOURCES,
        ),
    }

    off_cov = coverage_audit["offense"]
    idp_cov = coverage_audit["idp"]
    print(
        f"  [Top Coverage] Offense non-rookies: {off_cov['passPlayers']}/{off_cov['evaluated']} "
        f"meet >= {TOP_OFF_MIN_SOURCES} of {len(TOP_OFF_EXPECTED_SITE_KEYS)} sites"
    )
    print(
        f"  [Top Coverage] IDP: {idp_cov['passPlayers']}/{idp_cov['evaluated']} "
        f"meet >= {TOP_IDP_MIN_SOURCES} of {len(TOP_IDP_EXPECTED_SITE_KEYS)} sites"
    )
    if off_cov["deficitPlayers"]:
        print(f"  [Top Coverage] ⚠ Offensive deficits: {off_cov['deficitPlayers']}")
        if DEBUG:
            print(f"  [Top Coverage] Offensive missing by site: {off_cov.get('missingBySite', {})}")
    if idp_cov["deficitPlayers"]:
        print(f"  [Top Coverage] ⚠ IDP deficits: {idp_cov['deficitPlayers']}")
        if DEBUG:
            print(f"  [Top Coverage] IDP missing by site: {idp_cov.get('missingBySite', {})}")

    await _phase("build_payload", "dashboard_json", message="Building canonical dashboard payload")
    dashboard_json = {
        "version": 4,
        "date": str(datetime.date.today()),
        "scrapeTimestamp": datetime.datetime.now().isoformat(),
        "settings": {
            "superflex": SUPERFLEX,
            "tep": TEP,
            "idpAnchor": IDP_ANCHOR_TOP,
            "coverageTargets": {
                "offense": TARGET_OFFENSIVE_POOL,
                "idp": TARGET_IDP_POOL,
                "idpFloor": max(TARGET_IDP_POOL, MIN_IDP_POOL_FLOOR),
            },
            "pickModel": {
                "name": "rookie_proxy_2026_then_tiered_future",
                "activeUntil": "2026 NFL Draft completion",
                "notes": "2026 slots map 1:1 to top-72 rookie composites (years_exp==0 + must-have list, minimum one source hit); 2027/2028 use tier model with outside-market blend and calibrated future discount.",
            },
            "rankCurveDiagnostics": _rank_curve_diagnostics,
            "mustHaveRookies": list(ROOKIE_MUST_HAVE_NAMES or []),
            "dlfImport": dict(DLF_IMPORT_DEBUG or {}),
            "sourceRunSummary": source_run_summary,
        },
        "sites": sites_meta,
        "maxValues": max_values,
        "siteStats": site_stats,
        "pickAnchors": pick_anchors,
        "pickAnchorsRaw": pick_anchors_raw,
        "coverageAudit": coverage_audit,
        "poolAudit": _pool_audit.to_dict() if _pool_audit else None,
        "players": players_json,
    }

    if SLEEPER_ROSTER_DATA:
        dashboard_json["sleeper"] = SLEEPER_ROSTER_DATA

    if KTC_CROWD_DATA.get("trades") or KTC_CROWD_DATA.get("waivers"):
        dashboard_json["ktcCrowd"] = KTC_CROWD_DATA
        print(f"  [KTC Crowd] {len(KTC_CROWD_DATA.get('trades', []))} trades, "
              f"{len(KTC_CROWD_DATA.get('waivers', []))} waivers")

    if ktc_id_map:
        dashboard_json["ktcIdMap"] = ktc_id_map

    await _phase("write_files", "dynasty_data_json", message="Writing dashboard JSON/JS outputs")
    json_fname = os.path.join(SCRIPT_DIR, f"dynasty_data_{datetime.date.today()}.json")
    with open(json_fname, "w", encoding="utf-8") as f:
        json.dump(dashboard_json, f, indent=2, ensure_ascii=False)
    print(f"Saved to: {json_fname}")

    js_fname = os.path.join(SCRIPT_DIR, "dynasty_data.js")
    with open(js_fname, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by Dynasty Scraper — "
                f"{datetime.date.today()}\n")
        f.write("window.DYNASTY_DATA = ")
        json.dump(dashboard_json, f, indent=2, ensure_ascii=False)
        f.write(";\n")
    print(f"Saved to: {js_fname}")

    print(f"  {len(players_json)} players, {len(max_values)} sites with max values")
    if pick_anchors:
        print(f"  Pick anchors from: {', '.join(pick_anchors.keys())}")
    print()

    # Check for value movement alerts
    check_value_alerts(dashboard_json)

    # ── Save FULL CSV (all players with per-site values and composite) ──
    full_csv_fname = os.path.join(SCRIPT_DIR, "dynasty_full.csv")
    try:
        site_keys = [site_key_map.get(s, s) for s in active_sites if s in site_key_map]
        with open(full_csv_fname, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Player", "Composite", "Sites"] + site_keys)
            for name in sorted(players_json.keys()):
                pdata = players_json[name]
                comp = pdata.get("_composite", "")
                nsites = pdata.get("_sites", "")
                row = [name, comp, nsites]
                for sk in site_keys:
                    row.append(pdata.get(sk, ""))
                writer.writerow(row)
        print(f"  Full CSV: {full_csv_fname} ({len(players_json)} players)")
    except Exception as e:
        print(f"  [CSV] Error saving full CSV: {e}")

    await _phase("write_files", "export_bundle", message="Writing export bundle and raw site CSVs")
    # ── Local export bundle (easy sharing) ──
    # Creates:
    #   exports/latest/...
    #   exports/latest/site_raw/*.csv
    #   exports/dynasty_export_latest.zip
    try:
        export_root = os.path.join(SCRIPT_DIR, "exports")
        latest_dir = os.path.join(export_root, "latest")
        site_raw_dir = os.path.join(latest_dir, "site_raw")
        os.makedirs(site_raw_dir, exist_ok=True)

        # Reset latest folder contents — but preserve site_raw CSVs for
        # sources that didn't produce new data this run (e.g. KTC blocked
        # in sandbox).  We back up existing site_raw CSVs, wipe the dir,
        # then restore any that weren't overwritten.
        _prev_site_raw: dict[str, bytes] = {}
        if os.path.isdir(site_raw_dir):
            for fname_sr in os.listdir(site_raw_dir):
                fpath_sr = os.path.join(site_raw_dir, fname_sr)
                if os.path.isfile(fpath_sr) and fname_sr.endswith(".csv"):
                    try:
                        _prev_site_raw[fname_sr] = open(fpath_sr, "rb").read()
                    except Exception:
                        pass
        for entry in os.listdir(latest_dir):
            p = os.path.join(latest_dir, entry)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except Exception:
                pass
        os.makedirs(site_raw_dir, exist_ok=True)

        # Core output files to copy into latest bundle.
        copy_paths = [
            json_fname,
            js_fname,
            fname,           # dynasty_values.csv
            full_csv_fname,  # dynasty_full.csv
        ]
        for p in copy_paths:
            if os.path.exists(p):
                try:
                    shutil.copy2(p, os.path.join(latest_dir, os.path.basename(p)))
                except Exception:
                    pass

        # Export raw per-site maps to CSV for easier external sharing/audit.
        _fresh_site_raw: set[str] = set()
        for scraper_name, full_map in FULL_DATA.items():
            dash_key = site_key_map.get(scraper_name, scraper_name)
            out_csv = os.path.join(site_raw_dir, f"{dash_key}.csv")
            try:
                with open(out_csv, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["name", "value"])
                    for n, v in sorted(full_map.items(), key=lambda x: x[0].lower()):
                        w.writerow([n, v])
                _fresh_site_raw.add(f"{dash_key}.csv")
            except Exception:
                continue

        # Restore any previous site_raw CSVs that weren't re-produced
        # this run.  This keeps sources like KTC alive across scrape runs
        # where they might fail due to proxy/TLS issues.
        _preserved_site_raw: set[str] = set()
        for fname_sr, content in _prev_site_raw.items():
            dest = os.path.join(site_raw_dir, fname_sr)
            if not os.path.exists(dest):
                try:
                    with open(dest, "wb") as f:
                        f.write(content)
                    _preserved_site_raw.add(fname_sr)
                    print(f"  [site_raw] Preserved previous {fname_sr}")
                except Exception:
                    pass

        # Write manifest with per-source freshness metadata.
        manifest = {
            "generatedAt": datetime.datetime.now().isoformat(),
            "date": str(datetime.date.today()),
            "files": sorted(os.listdir(latest_dir)),
            "siteRawCount": len(os.listdir(site_raw_dir)) if os.path.exists(site_raw_dir) else 0,
            "siteRawFresh": sorted(_fresh_site_raw),
            "siteRawPreserved": sorted(_preserved_site_raw),
        }
        with open(os.path.join(latest_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        def _write_bundle_zip(out_path):
            with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(latest_dir):
                    for fn in files:
                        ap = os.path.join(root, fn)
                        rp = os.path.relpath(ap, latest_dir)
                        zf.write(ap, arcname=rp)

        zip_path = os.path.join(export_root, "dynasty_export_latest.zip")
        _write_bundle_zip(zip_path)

        archive_dir = os.path.join(export_root, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        run_stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_zip_path = os.path.join(archive_dir, f"dynasty_export_{run_stamp}.zip")
        _write_bundle_zip(archive_zip_path)

        print(f"  [Export] Latest bundle: {latest_dir}")
        print(f"  [Export] Zip: {zip_path}")
        print(f"  [Export] Archive zip: {archive_zip_path}")
    except Exception as e:
        print(f"  [Export] Error creating local export bundle: {e}")

    await _emit_progress(
        step="complete",
        source="run",
        step_index=planned_total_steps,
        step_total=planned_total_steps,
        event="scrape_complete",
        message="Scraper run complete",
    )
    return dashboard_json


def check_value_alerts(current_json):
    """Compare current composite values against previous scrape and email alerts."""
    if not ALERT_ENABLED or not ALERT_EMAIL:
        return
    import smtplib
    from email.mime.text import MIMEText

    prev_file = os.path.join(SCRIPT_DIR, "data", "_prev_composites.json")

    # Load previous values
    prev_values = {}
    try:
        if os.path.exists(prev_file):
            with open(prev_file, "r") as f:
                prev_values = json.load(f)
    except Exception:
        pass

    # Get current player values (use KTC as proxy for composite since we can't
    # compute the full z-score normalized composite server-side easily)
    # Instead, store a simple weighted average of available big-scale sites
    current_values = {}
    players = current_json.get("players", {})
    big_sites = ["ktc", "fantasyCalc", "dynastyDaddy", "idpTradeCalc"]
    for name, pdata in players.items():
        vals = []
        for sk in big_sites:
            v = pdata.get(sk)
            if v and isinstance(v, (int, float)) and v > 100:
                vals.append(v)
        if vals:
            current_values[name] = sum(vals) / len(vals)

    # Save current for next time
    try:
        os.makedirs(os.path.dirname(prev_file), exist_ok=True)
        with open(prev_file, "w") as f:
            json.dump(current_values, f)
    except Exception:
        pass

    if not prev_values or len(prev_values) < 50:
        print("  [Alerts] No previous data to compare — skipping alerts this run.")
        return

    # Get my roster players
    my_team_name = ""  # Will be set from settings if available
    my_players = set()
    if SLEEPER_ROSTER_DATA and SLEEPER_ROSTER_DATA.get("teams"):
        # Use all rostered players for now (user picks team in dashboard)
        for team in SLEEPER_ROSTER_DATA["teams"]:
            for p in team.get("players", []):
                my_players.add(p.lower())

    # Find significant movers
    risers = []
    fallers = []
    for name, cur_val in current_values.items():
        prev_val = prev_values.get(name)
        if not prev_val or prev_val < 100:
            continue
        pct = ((cur_val - prev_val) / prev_val) * 100
        if abs(pct) >= ALERT_THRESHOLD:
            is_rostered = name.lower() in my_players
            entry = {
                "name": name,
                "prev": round(prev_val),
                "current": round(cur_val),
                "pct": round(pct, 1),
                "rostered": is_rostered,
            }
            if pct > 0:
                risers.append(entry)
            else:
                fallers.append(entry)

    risers.sort(key=lambda x: -x["pct"])
    fallers.sort(key=lambda x: x["pct"])

    # Filter to rostered players for the email
    my_risers = [r for r in risers if r["rostered"]][:10]
    my_fallers = [f for f in fallers if f["rostered"]][:10]

    if not my_risers and not my_fallers:
        print(f"  [Alerts] No rostered players moved {ALERT_THRESHOLD}%+. No alert sent.")
        return

    # Build email
    lines = [f"Dynasty Value Alert — {datetime.date.today()}\n"]
    lines.append(f"Players on your rosters that moved {ALERT_THRESHOLD}%+ since last scrape:\n")

    if my_risers:
        lines.append("📈 RISING:")
        for r in my_risers:
            lines.append(f"  {r['name']}: {r['prev']:,} → {r['current']:,} (+{r['pct']}%)")
        lines.append("")

    if my_fallers:
        lines.append("📉 FALLING:")
        for f in my_fallers:
            lines.append(f"  {f['name']}: {f['prev']:,} → {f['current']:,} ({f['pct']}%)")
        lines.append("")

    # Also show top league-wide movers
    top_risers = risers[:5]
    top_fallers = fallers[:5]
    if top_risers:
        lines.append("🔥 BIGGEST LEAGUE-WIDE RISERS:")
        for r in top_risers:
            tag = " ⭐" if r["rostered"] else ""
            lines.append(f"  {r['name']}: +{r['pct']}%{tag}")
        lines.append("")
    if top_fallers:
        lines.append("❄️ BIGGEST LEAGUE-WIDE FALLERS:")
        for f in top_fallers:
            tag = " ⭐" if f["rostered"] else ""
            lines.append(f"  {f['name']}: {f['pct']}%{tag}")

    body = "\n".join(lines)
    print(f"  [Alerts] {len(my_risers)} risers, {len(my_fallers)} fallers on your rosters")

    # Save alert to file (server can pick this up)
    alert_file = os.path.join(SCRIPT_DIR, "data", "_latest_alert.txt")
    try:
        with open(alert_file, "w") as f:
            f.write(body)
        print(f"  [Alerts] Saved alert to {alert_file}")
    except Exception:
        pass

    # Try sending via local sendmail or SMTP
    try:
        msg = MIMEText(body)
        msg["Subject"] = f"Dynasty Alert: {len(my_risers)} rising, {len(my_fallers)} falling"
        msg["From"] = "dynasty-alerts@localhost"
        msg["To"] = ALERT_EMAIL

        # Try localhost sendmail first
        smtp = smtplib.SMTP("localhost", 25, timeout=5)
        smtp.send_message(msg)
        smtp.quit()
        print(f"  [Alerts] Email sent to {ALERT_EMAIL}")
    except Exception as e:
        print(f"  [Alerts] Email send failed ({e}) — alert saved to file only")


if __name__ == "__main__":
    asyncio.run(run())
