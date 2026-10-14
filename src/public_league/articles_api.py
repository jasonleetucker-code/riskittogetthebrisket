"""League narrative-article HTTP routes (preview / recap).

Moved verbatim out of ``server.py`` (CLEANUP-4, 2026-10-07) as a
behaviour-preserving extraction; ``server.py`` includes ``router`` at the
exact point the three decorators used to sit, so route order, paths,
methods, operationIds and responses are unchanged — pinned by
``tests/api/test_league_articles_route_characterization.py``.

Public read endpoints + admin-only generation trigger.  Articles are
persisted to ``exports/narratives/<season>/week-<NN>/<mode>-<id>.json``
by the cron generator (see ``scripts/generate_weekly_narratives.py``
and ``.github/workflows/weekly-narratives.yml``).  These endpoints
serve them — they do NOT generate on read so a slow Anthropic round
trip never blocks a page load.  The article store and generator are
owned by ``src/public_league/matchup_narrative.py``.

LATE BINDING TO THE HOST
────────────────────────
The generate trigger depends on collaborators that live in ``server.py``
(the admin gate, the league resolver and its error type, the optional
``anthropic`` SDK module, ``run_in_threadpool`` and the server logger).
They are looked up on the host module at REQUEST time through
``configure_host`` rather than imported here, for two reasons:

* ``server.py`` imports this module, so importing ``server`` back would be
  circular (and under ``python server.py`` the host is ``__main__``);
* tests patch those names on ``server`` (``monkeypatch.setattr(server,
  "_is_authenticated", ...)``, ``server.anthropic``, ...) and the patches
  must keep reaching the handler exactly as they did before the move.

Same injection posture as ``src/dfs/api.configure_session_resolver``.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.public_league.public_contract import public_payload

# No prefix and no tags: the OpenAPI operations must stay byte-identical
# to the pre-extraction app.
router = APIRouter()

_host_provider: Callable[[], Any] | None = None


def configure_host(provider: Callable[[], Any]) -> None:
    """Install the callable that returns the host (``server``) module."""
    global _host_provider
    _host_provider = provider


def _host() -> Any:
    if _host_provider is None:
        raise RuntimeError(
            "articles_api host not configured — server.py must call "
            "configure_host() before including the router"
        )
    return _host_provider()


def _public_league_key_error(request: Request) -> JSONResponse | None:
    """The public reads validate ``?leagueKey=`` exactly like every
    ``/api/public/league*`` route (``server._public_league_key_error``,
    resolved on the host at request time): articles describe the public
    league, so a request naming another league is refused, never answered
    with the default league's articles.  Read from ``query_params`` rather
    than a declared parameter so the pinned OpenAPI operations are unchanged.
    """
    return _host()._public_league_key_error(request.query_params.get("leagueKey") or "")


@router.get("/api/league/articles")
async def get_league_articles(request: Request):
    """List narrative articles, optionally filtered by season/week.

    Query params:
      * ``season`` (optional) — restrict to one season label.
      * ``week`` (optional) — restrict to one week within season.

    Returns a flat array of {season, week, mode, matchupId, title,
    generatedAt, home, away, kicker} so the frontend list page can
    render a slate without N follow-up requests.  Heavy fields
    (body, lede) are omitted from the index response — clients fetch
    them via the single-article endpoint.
    """
    from src.public_league import matchup_narrative as _mn

    league_err = _public_league_key_error(request)
    if league_err is not None:
        return league_err
    season = (request.query_params.get("season") or "").strip() or None
    week_raw = (request.query_params.get("week") or "").strip()
    try:
        week_filter = int(week_raw) if week_raw else None
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": "bad_request", "message": "week must be an integer"},
        )

    items = _mn.list_articles(season=season)
    if week_filter is not None:
        items = [r for r in items if int(r.get("week") or -1) == week_filter]

    # Hydrate index entries with the small subset of article fields
    # needed for a slate list (title, kicker, home/away identity).
    enriched = []
    for entry in items:
        full = _mn.load_article(
            entry["season"],
            entry["week"],
            entry["matchupId"],
            entry["mode"],
        )
        if not full:
            continue
        enriched.append(
            {
                "season": entry["season"],
                "week": entry["week"],
                "mode": entry["mode"],
                "matchupId": entry["matchupId"],
                "title": full.get("title"),
                "kicker": full.get("kicker"),
                "angleUsed": full.get("angleUsed"),
                "isChampionship": full.get("isChampionship", False),
                "roundLabel": full.get("roundLabel", ""),
                "home": full.get("home", {}),
                "away": full.get("away", {}),
                "generatedAt": full.get("generatedAt"),
                "wordCount": full.get("wordCount", 0),
            }
        )

    # Same serving projection as every public-league route (raw Sleeper ids
    # dropped, private-field walk) — fail-closed hygiene: articles carry
    # none today.
    return JSONResponse(
        content=public_payload(
            {
                "articles": enriched,
                "total": len(enriched),
                "season": season,
                "week": week_filter,
            }
        ),
        headers={"Cache-Control": "public, max-age=120"},
    )


@router.get("/api/league/articles/{season}/{week}/{matchup_id}/{mode}")
async def get_league_article(season: str, week: int, matchup_id: int, mode: str, request: Request):
    """Single article — full body, ready to render."""
    from src.public_league import matchup_narrative as _mn

    league_err = _public_league_key_error(request)
    if league_err is not None:
        return league_err
    if mode not in {"preview", "recap"}:
        return JSONResponse(
            status_code=400,
            content={"error": "bad_request", "message": "mode must be preview|recap"},
        )
    article = _mn.load_article(season, week, matchup_id, mode)
    if article is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found",
                "message": (f"No {mode} article on disk for {season} W{week} matchup {matchup_id}"),
            },
        )
    return JSONResponse(
        content=public_payload(article),
        # Cache for 5 minutes; new articles propagate via cron not on-demand.
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.post("/api/league/articles/generate")
async def post_generate_league_article(request: Request):
    """Admin trigger: generate a single article on demand.

    Body shape:
        {
          "season": "2025",         // optional, defaults to current season
          "week": 17,                // optional, detector picks live week
          "matchupId": 1,            // required for single-article runs
          "mode": "preview" | "recap",
          "force": true|false        // optional, default false
        }

    Returns the generated article on success, 404 if the matchup
    can't be found in the snapshot, 503 if the Anthropic SDK isn't
    configured.

    NOTE: this is the synchronous, single-matchup path — full slate
    generation is the cron's job.  Hold a session at the wheel; this
    will block for 10-30 seconds while Claude generates.
    """
    host = _host()
    session_or_err = host._require_admin_session(request)
    if isinstance(session_or_err, JSONResponse):
        return session_or_err

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}

    mode = str(body.get("mode") or "").strip().lower()
    if mode not in {"preview", "recap"}:
        return JSONResponse(
            status_code=400,
            content={"error": "bad_request", "message": "mode must be preview|recap"},
        )
    matchup_id = body.get("matchupId")
    if matchup_id is None:
        return JSONResponse(
            status_code=400,
            content={"error": "bad_request", "message": "matchupId required"},
        )
    try:
        matchup_id = int(matchup_id)
    except (TypeError, ValueError):
        return JSONResponse(
            status_code=400,
            content={"error": "bad_request", "message": "matchupId must be an integer"},
        )
    explicit_week = body.get("week")
    if explicit_week is not None:
        try:
            explicit_week = int(explicit_week)
        except (TypeError, ValueError):
            return JSONResponse(
                status_code=400,
                content={"error": "bad_request", "message": "week must be an integer"},
            )
    explicit_season = body.get("season")
    explicit_season = str(explicit_season) if explicit_season else None
    force = bool(body.get("force"))

    # Resolve league via the standard resolver (so admins can override
    # via ?leagueKey=).
    try:
        league_cfg = host._resolve_league_for_request(request, body=body)
    except host.LeagueResolutionError as err:
        return err.json_response()

    anthropic = host.anthropic
    if anthropic is None:
        return JSONResponse(
            status_code=503,
            content={"error": "anthropic_unavailable", "message": "anthropic SDK not installed"},
        )
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return JSONResponse(
            status_code=503,
            content={
                "error": "anthropic_unavailable",
                "message": "ANTHROPIC_API_KEY not configured",
            },
        )

    # Build the snapshot off the event loop — it does ~85 HTTP GETs
    # against Sleeper.
    from src.public_league import matchup_narrative as _mn
    from src.public_league.snapshot import build_public_snapshot

    snapshot = await host.run_in_threadpool(
        build_public_snapshot,
        league_cfg.sleeper_league_id,
    )
    current = snapshot.current_season
    if current is None:
        return JSONResponse(
            status_code=503,
            content={"error": "snapshot_unavailable", "message": "Sleeper snapshot empty"},
        )

    season = explicit_season or current.season
    if explicit_week is not None:
        week = explicit_week
    else:
        from src.public_league import matchup_preview as _mp

        detected_week, detected_mode = _mp._detect_current_week(current)  # noqa: SLF001
        if detected_week == 0:
            return JSONResponse(
                status_code=404,
                content={"error": "week_not_found", "message": "no live week detected"},
            )
        if mode == "recap" and detected_mode == "preview":
            week = max(1, detected_week - 1)
        else:
            week = detected_week

    if not force:
        existing = _mn.load_article(season, week, matchup_id, mode)
        if existing is not None:
            return JSONResponse(
                status_code=200,
                content={"article": existing, "regenerated": False},
            )

    brief = _mn.build_brief(
        snapshot,
        season=season,
        week=week,
        matchup_id=matchup_id,
        mode=mode,
    )
    if brief is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "matchup_not_found",
                "message": f"no matchup_id={matchup_id} in {season} W{week}",
            },
        )
    prior = _mn.collect_prior_articles(season, n=6)
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        article = await _mn.generate_article(
            client=client,
            brief=brief,
            prior_articles=prior,
        )
    except Exception as exc:  # noqa: BLE001 — collapse SDK / network / parse to one structured error
        # generate_article raises RuntimeError for malformed JSON, but
        # SDK layer can raise APIStatusError / RateLimitError /
        # APIConnectionError / asyncio.TimeoutError before parsing.
        # All of these are operational failures the admin caller wants
        # to retry against, not unstructured 500s.
        host.log.warning(
            "league_article_generation_failed",
            extra={
                "season": season,
                "week": week,
                "matchupId": matchup_id,
                "mode": mode,
                "error_type": type(exc).__name__,
            },
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "generation_failed",
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
    _mn.save_article(article)
    return JSONResponse(
        status_code=200,
        content={"article": article, "regenerated": True},
    )
