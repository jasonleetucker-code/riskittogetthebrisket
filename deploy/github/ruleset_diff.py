#!/usr/bin/env python3
"""Show what applying main-protection-ruleset.json would change, sending nothing.

    ruleset_diff.py <payload.json> [<live.json>]

``live.json`` is the output of ``GET /repos/<repo>/rulesets/<id>`` (readable
without admin rights on this repository).  Without it the payload is reported as a
CREATE.  Both sides are normalized to the fields the apply call actually writes, so
server-assigned ids and timestamps never show up as noise.  Exit 0 always: a diff
is information, not a failure.  Stdlib only.
"""

from __future__ import annotations

import json
import sys
from typing import Any

WRITABLE = ("name", "target", "enforcement", "conditions", "bypass_actors", "rules")


def normalize(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: doc.get(k) for k in WRITABLE}
    out["bypass_actors"] = sorted(
        (
            {
                "actor_type": a.get("actor_type"),
                "actor_id": a.get("actor_id"),
                "bypass_mode": a.get("bypass_mode"),
            }
            for a in (doc.get("bypass_actors") or [])
        ),
        key=lambda a: (str(a["actor_type"]), str(a["actor_id"])),
    )
    out["rules"] = sorted((doc.get("rules") or []), key=lambda r: r.get("type", ""))
    return out


def rule_checks(doc: dict[str, Any]) -> list[str]:
    for rule in doc.get("rules") or []:
        if rule.get("type") == "required_status_checks":
            return sorted(
                f"{c.get('context')} (integration {c.get('integration_id')})"
                for c in rule["parameters"]["required_status_checks"]
            )
    return []


def _fmt_actor(a: dict[str, Any]) -> str:
    return f"{a['actor_type']} id={a['actor_id']} mode={a['bypass_mode']}"


def describe_diff(payload: dict[str, Any], live: dict[str, Any] | None) -> list[str]:
    new = normalize({k: v for k, v in payload.items() if k != "_comment"})
    if live is None:
        return ["no live ruleset named main-protection: this would CREATE it"]
    old = normalize(live)
    lines: list[str] = []
    for key in ("enforcement", "target", "conditions"):
        if old[key] != new[key]:
            lines.append(f"~ {key}: {json.dumps(old[key])} -> {json.dumps(new[key])}")
    old_b = {_fmt_actor(a) for a in old["bypass_actors"]}
    new_b = {_fmt_actor(a) for a in new["bypass_actors"]}
    lines += [f"- bypass {a}" for a in sorted(old_b - new_b)]
    lines += [f"+ bypass {a}" for a in sorted(new_b - old_b)]
    old_r = {r["type"]: r for r in old["rules"]}
    new_r = {r["type"]: r for r in new["rules"]}
    lines += [f"- rule {t}" for t in sorted(set(old_r) - set(new_r))]
    lines += [f"+ rule {t}" for t in sorted(set(new_r) - set(old_r))]
    for t in sorted(set(old_r) & set(new_r)):
        if old_r[t] != new_r[t]:
            lines.append(f"~ rule {t}: {json.dumps(old_r[t])} -> {json.dumps(new_r[t])}")
    oc, nc = rule_checks(live), rule_checks(payload)
    lines.append(f"required checks now: {oc or 'none'}")
    lines.append(f"required checks after: {nc or 'none'}")
    return lines if len(lines) > 2 else ["identical to the live ruleset (nothing to apply)", *lines]


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 1
    with open(argv[1], encoding="utf-8") as fh:
        payload = json.load(fh)
    live = None
    if len(argv) == 3:
        with open(argv[2], encoding="utf-8") as fh:
            live = json.load(fh)
    for line in describe_diff(payload, live):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
