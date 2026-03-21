#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urlparse


LEAGUE_TOP_LEVEL_ROUTES = [
    "/league",
    "/league/standings",
    "/league/franchises",
    "/league/awards",
    "/league/draft",
    "/league/trades",
    "/league/records",
    "/league/money",
    "/league/constitution",
    "/league/history",
    "/league/league-media",
]

PRIVATE_ROUTE_EXPECTATIONS = {
    "/app": "/?next=/app&jason=1",
    "/rankings": "/?next=/rankings&jason=1",
    "/trade": "/?next=/trade&jason=1",
    "/calculator": "/?next=/calculator&jason=1",
}

PUBLIC_LEAGUE_AUTHORITIES = {
    "public-static-league-shell",
    "public-league-inline-fallback-shell",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # pragma: no cover
        return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _request(url: str, *, timeout: float, no_redirect: bool = False) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "dynasty-runtime-probe/1.0", "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect()) if no_redirect else urllib.request.build_opener()

    status = None
    headers = {}
    body = b""
    error = None
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            headers = {str(k).lower(): str(v) for k, v in resp.headers.items()}
            body = resp.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        headers = {str(k).lower(): str(v) for k, v in exc.headers.items()} if exc.headers else {}
        try:
            body = exc.read() or b""
        except Exception:
            body = b""
        error = f"HTTPError {exc.code}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    text = ""
    payload = None
    if body:
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            text = ""
    if text:
        try:
            payload = json.loads(text)
        except Exception:
            payload = None

    return {
        "url": url,
        "status": status,
        "headers": headers,
        "text": text,
        "json": payload,
        "error": error,
    }


def _join(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def _location_path_query(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme or parsed.netloc:
        path = parsed.path or "/"
        if parsed.query:
            return f"{path}?{parsed.query}"
        return path
    return text


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _severity_rank(level: str) -> int:
    if level == "critical":
        return 3
    if level == "warning":
        return 2
    return 1


def _summary_status(issues: list[dict]) -> str:
    worst = "ok"
    for item in issues:
        level = str(item.get("severity") or "warning").lower()
        if _severity_rank(level) > _severity_rank(worst):
            worst = level
    return worst


def main() -> int:
    parser = argparse.ArgumentParser(description="Runtime health/freshness/route smoke probe")
    parser.add_argument("--base-url", required=True, help="Runtime base URL, ex: https://riskittogetthebrisket.org")
    parser.add_argument("--mode", choices=["health", "smoke"], default="health")
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument("--max-scrape-age-hours", type=float, default=10.0)
    parser.add_argument("--strict-health", action="store_true", help="Fail when /api/health is not HTTP 200")
    parser.add_argument("--strict-operator", action="store_true", help="Fail when operator report status is critical")
    parser.add_argument("--strict-routes", action="store_true", help="Fail on route smoke mismatches in smoke mode")
    parser.add_argument("--output-json", help="Optional output report path")
    args = parser.parse_args()

    checks: dict[str, dict] = {}
    issues: list[dict] = []
    now = datetime.now(timezone.utc)

    health = _request(_join(args.base_url, "/api/health"), timeout=args.timeout_sec)
    checks["health"] = {
        "url": health["url"],
        "status": health.get("status"),
        "error": health.get("error"),
        "payload": health.get("json"),
    }
    if int(health.get("status") or 0) != 200:
        issues.append(
            {
                "severity": "critical" if args.strict_health else "warning",
                "code": "health_not_200",
                "detail": f"/api/health returned {health.get('status')} ({health.get('error') or 'no error details'})",
            }
        )

    status_compact = _request(_join(args.base_url, "/api/status?compact=1"), timeout=args.timeout_sec)
    compact_payload = status_compact.get("json") if isinstance(status_compact.get("json"), dict) else {}
    checks["status_compact"] = {
        "url": status_compact["url"],
        "status": status_compact.get("status"),
        "error": status_compact.get("error"),
        "payload": compact_payload,
    }
    if int(status_compact.get("status") or 0) != 200:
        issues.append(
            {
                "severity": "critical" if args.strict_health else "warning",
                "code": "status_compact_not_200",
                "detail": f"/api/status?compact=1 returned {status_compact.get('status')}",
            }
        )

    scrape_age_hours = None
    last_scrape = compact_payload.get("last_scrape") if isinstance(compact_payload, dict) else None
    last_scrape_ts = _parse_iso(str(last_scrape) if last_scrape is not None else None)
    if last_scrape_ts is not None:
        scrape_age_hours = max(0.0, (now - last_scrape_ts.astimezone(timezone.utc)).total_seconds() / 3600.0)
        if scrape_age_hours > float(args.max_scrape_age_hours):
            issues.append(
                {
                    "severity": "critical" if args.strict_health else "warning",
                    "code": "scrape_age_exceeded",
                    "detail": (
                        f"Last scrape age {scrape_age_hours:.2f}h exceeds max {float(args.max_scrape_age_hours):.2f}h"
                    ),
                }
            )
    else:
        issues.append(
            {
                "severity": "warning",
                "code": "last_scrape_missing",
                "detail": "Compact status did not include a parseable last_scrape timestamp",
            }
        )

    status_full = _request(_join(args.base_url, "/api/status"), timeout=args.timeout_sec)
    full_payload = status_full.get("json") if isinstance(status_full.get("json"), dict) else {}
    checks["status_full"] = {
        "url": status_full["url"],
        "status": status_full.get("status"),
        "error": status_full.get("error"),
        "payload_summary": {
            "has_data": bool(full_payload.get("has_data")) if isinstance(full_payload, dict) else False,
            "player_count": int(full_payload.get("player_count") or 0) if isinstance(full_payload, dict) else 0,
            "source_counts": (
                (full_payload.get("source_health") or {}).get("source_counts")
                if isinstance(full_payload, dict)
                else {}
            ),
            "frontend_raw_fallback": (
                ((full_payload.get("frontend_runtime") or {}).get("raw_fallback_health"))
                if isinstance(full_payload, dict)
                else {}
            ),
        },
    }
    frontend_raw_fallback = (
        ((full_payload.get("frontend_runtime") or {}).get("raw_fallback_health"))
        if isinstance(full_payload.get("frontend_runtime"), dict)
        else {}
    )
    skipped_file_count = int(frontend_raw_fallback.get("skipped_file_count") or 0)
    if skipped_file_count > 0:
        selected_source = str(frontend_raw_fallback.get("selected_source") or "none")
        issues.append(
            {
                "severity": "warning",
                "code": "frontend_raw_fallback_skipped_files",
                "detail": (
                    f"Frontend raw fallback skipped {skipped_file_count} invalid file(s); "
                    f"selected_source={selected_source}"
                ),
            }
        )

    operator = _request(_join(args.base_url, "/api/validation/operator-report"), timeout=args.timeout_sec)
    operator_payload = operator.get("json") if isinstance(operator.get("json"), dict) else {}
    operator_status = str(operator_payload.get("status") or "unknown").lower()
    checks["operator_report"] = {
        "url": operator["url"],
        "status": operator.get("status"),
        "error": operator.get("error"),
        "operator_status": operator_status,
        "summary": (
            ((operator_payload.get("operatorReport") or {}).get("summary"))
            if isinstance(operator_payload.get("operatorReport"), dict)
            else {}
        ),
        "flags": (
            ((operator_payload.get("operatorReport") or {}).get("flags"))
            if isinstance(operator_payload.get("operatorReport"), dict)
            else {}
        ),
    }
    if int(operator.get("status") or 0) not in {200, 503}:
        issues.append(
            {
                "severity": "critical" if args.strict_operator else "warning",
                "code": "operator_report_unavailable",
                "detail": f"/api/validation/operator-report returned {operator.get('status')}",
            }
        )
    if operator_status == "critical":
        issues.append(
            {
                "severity": "critical" if args.strict_operator else "warning",
                "code": "operator_critical",
                "detail": "Operator report status is critical",
            }
        )

    route_checks: list[dict] = []
    if args.mode == "smoke":
        route_map_resp = _request(_join(args.base_url, "/api/runtime/route-authority"), timeout=args.timeout_sec)
        route_map_ok = int(route_map_resp.get("status") or 0) == 200
        route_checks.append(
            {
                "route": "/api/runtime/route-authority",
                "status": route_map_resp.get("status"),
                "ok": route_map_ok,
                "expected": "200",
                "actual_authority": None,
            }
        )
        if not route_map_ok:
            issues.append(
                {
                    "severity": "critical" if args.strict_routes else "warning",
                    "code": "route_authority_endpoint_unavailable",
                    "detail": f"/api/runtime/route-authority returned {route_map_resp.get('status')}",
                }
            )

        root_resp = _request(_join(args.base_url, "/"), timeout=args.timeout_sec, no_redirect=True)
        root_authority = str((root_resp.get("headers") or {}).get("x-route-authority") or "")
        root_ok = int(root_resp.get("status") or 0) == 200 and (
            not root_authority or root_authority == "public-static-landing-shell"
        )
        route_checks.append(
            {
                "route": "/",
                "status": root_resp.get("status"),
                "ok": root_ok,
                "expected": "200 + public-static-landing-shell",
                "actual_authority": root_authority,
            }
        )
        if not root_ok:
            issues.append(
                {
                    "severity": "critical" if args.strict_routes else "warning",
                    "code": "root_route_authority_mismatch",
                    "detail": f"/ returned {root_resp.get('status')} with authority={root_authority}",
                }
            )

        for route in LEAGUE_TOP_LEVEL_ROUTES:
            resp = _request(_join(args.base_url, route), timeout=args.timeout_sec, no_redirect=True)
            authority = str((resp.get("headers") or {}).get("x-route-authority") or "")
            ok = int(resp.get("status") or 0) == 200 and (
                not authority or authority in PUBLIC_LEAGUE_AUTHORITIES
            )
            route_checks.append(
                {
                    "route": route,
                    "status": resp.get("status"),
                    "ok": ok,
                    "expected": "200 + public-static-league-shell/public-league-inline-fallback-shell",
                    "actual_authority": authority,
                }
            )
            if not ok:
                issues.append(
                    {
                        "severity": "critical" if args.strict_routes else "warning",
                        "code": "league_route_check_failed",
                        "detail": f"{route} returned {resp.get('status')} with authority={authority}",
                    }
                )

        for route, expected_location in PRIVATE_ROUTE_EXPECTATIONS.items():
            resp = _request(_join(args.base_url, route), timeout=args.timeout_sec, no_redirect=True)
            authority = str((resp.get("headers") or {}).get("x-route-authority") or "")
            location = str((resp.get("headers") or {}).get("location") or "")
            ok = (
                int(resp.get("status") or 0) == 302
                and _location_path_query(location) == _location_path_query(expected_location)
                and (not authority or authority == "auth-gate-redirect")
            )
            route_checks.append(
                {
                    "route": route,
                    "status": resp.get("status"),
                    "ok": ok,
                    "expected": f"302 + auth-gate-redirect + location={expected_location}",
                    "actual_authority": authority,
                    "actual_location": location,
                }
            )
            if not ok:
                issues.append(
                    {
                        "severity": "critical" if args.strict_routes else "warning",
                        "code": "private_route_auth_boundary_mismatch",
                        "detail": (
                            f"{route} returned {resp.get('status')} authority={authority} location={location}; "
                            f"expected location={expected_location}"
                        ),
                    }
                )

    report = {
        "checkedAtUtc": _iso_now(),
        "baseUrl": args.base_url,
        "mode": args.mode,
        "thresholds": {
            "maxScrapeAgeHours": float(args.max_scrape_age_hours),
            "strictHealth": bool(args.strict_health),
            "strictOperator": bool(args.strict_operator),
            "strictRoutes": bool(args.strict_routes),
        },
        "checks": checks,
        "routeChecks": route_checks,
        "derived": {
            "lastScrape": str(last_scrape or ""),
            "lastScrapeAgeHours": (round(scrape_age_hours, 3) if scrape_age_hours is not None else None),
        },
        "issues": issues,
        "status": _summary_status(issues),
    }

    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print("# Runtime Probe Summary")
    print(f"- Base URL: {args.base_url}")
    print(f"- Mode: {args.mode}")
    print(f"- Status: {report['status']}")
    print(f"- Health HTTP: {checks['health'].get('status')}")
    print(f"- Operator status: {checks['operator_report'].get('operator_status')}")
    if scrape_age_hours is not None:
        print(f"- Last scrape age (hours): {scrape_age_hours:.3f}")
    else:
        print("- Last scrape age (hours): unknown")
    print(f"- Issue count: {len(issues)}")
    if issues:
        print("## Issues")
        for item in issues:
            print(f"- [{item.get('severity')}] {item.get('code')}: {item.get('detail')}")

    should_fail = False
    if args.strict_health and int(health.get("status") or 0) != 200:
        should_fail = True
    if args.strict_health and any(str(i.get("code")) == "scrape_age_exceeded" for i in issues):
        should_fail = True
    if args.strict_operator and (operator_status in {"critical", "unknown", ""}):
        should_fail = True
    if args.strict_operator and any(str(i.get("code")) == "operator_report_unavailable" for i in issues):
        should_fail = True
    if args.strict_routes and any(str(i.get("code", "")).startswith(("route_", "league_", "private_", "root_")) for i in issues):
        should_fail = True

    return 1 if should_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
