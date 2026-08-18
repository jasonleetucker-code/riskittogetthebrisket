"""Person-level Sharp consensus with portfolio and network safeguards."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping, Sequence


def aggregate_person_consensus(
    rows: Sequence[Mapping[str, Any]],
    quality_by_manager: Mapping[str, float],
    network_by_manager: Mapping[str, str | None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Collapse many account/league movements into one vote per person.

    Raw movement counts remain available elsewhere. This view prevents one
    person with many observable leagues or accounts from behaving like many
    independent experts. Analysts sharing an affiliation receive a square-root
    concentration discount rather than being deleted or treated as clones.
    """

    network_by_manager = network_by_manager or {}
    state: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        asset_id = str(row.get("canonicalAssetId") or "").strip()
        manager_key = str(row.get("managerKey") or "").strip()
        person_id = str(row.get("canonicalManagerKey") or manager_key).strip()
        action = str(row.get("action") or "").strip().lower()
        if not asset_id or not person_id or action not in {"add", "drop"}:
            continue
        person = state[asset_id].setdefault(
            person_id,
            {
                "adds": 0,
                "drops": 0,
                "quality": 0.0,
                "network": None,
                "managerKeys": set(),
            },
        )
        person["adds" if action == "add" else "drops"] += 1
        person["managerKeys"].add(manager_key)
        person["quality"] = max(
            float(person["quality"] or 0.0),
            max(0.0, min(1.0, float(quality_by_manager.get(manager_key, 1.0)))),
        )
        network = str(network_by_manager.get(manager_key) or "").strip()
        if network:
            person["network"] = network.casefold()

    output: dict[str, dict[str, Any]] = {}
    for asset_id, people in state.items():
        network_sizes: dict[str, int] = defaultdict(int)
        for person_id, person in people.items():
            network = str(person.get("network") or f"independent:{person_id}")
            network_sizes[network] += 1

        buys = sells = mixed = 0
        weighted_net = weighted_volume = 0.0
        quality_total = 0.0
        voters = 0
        network_vote_abs: dict[str, float] = defaultdict(float)
        for person_id, person in people.items():
            net = int(person["adds"]) - int(person["drops"])
            if net == 0:
                if person["adds"] or person["drops"]:
                    mixed += 1
                continue
            voters += 1
            direction = 1 if net > 0 else -1
            buys += int(direction > 0)
            sells += int(direction < 0)
            # AN EXPLICIT ZERO IS NOT A MISSING VALUE.  ``or 1.0`` promoted a
            # manager scored 0.0 — the lowest possible quality — to 1.0, the
            # highest, so a worthless vote carried full weight into both the
            # consensus and the concentration cap.  The default already
            # happened upstream (``quality_by_manager.get(key, 1.0)``), so
            # this second one could only ever overwrite a real measurement.
            # A non-numeric value is genuinely unknown and still defaults.
            raw_quality = person["quality"]
            quality = float(raw_quality) if isinstance(raw_quality, (int, float)) else 1.0
            network = str(person.get("network") or f"independent:{person_id}")
            # Diminishing independence within a shared company/network/model.
            independence = 1.0 / math.sqrt(max(1, network_sizes[network]))
            weight = quality * independence
            weighted_net += direction * weight
            weighted_volume += weight
            quality_total += quality
            network_vote_abs[network] += weight

        # UNDEFINED, NOT DIVERSIFIED.  With no weighted volume there is no
        # share for any network to hold, so the ratio does not exist — and
        # ``0.0`` is the one value that reads as its opposite ("no single
        # network dominates").  ``None`` matches what
        # ``roster_percentage`` publishes for ``cohortCoveragePct`` in the
        # same situation.
        concentration = (
            max(network_vote_abs.values()) / weighted_volume
            if weighted_volume > 0 and network_vote_abs
            else None
        )
        output[asset_id] = {
            "personBuys": buys,
            "personSells": sells,
            "personNet": buys - sells,
            "personVotes": voters,
            "mixedPersonSignals": mixed,
            "weightedPersonNet": round(weighted_net, 6),
            "weightedPersonVolume": round(weighted_volume, 6),
            "personManagerQuality": quality_total / voters if voters else 1.0,
            "networkCount": len(network_vote_abs),
            "networkConcentration": (None if concentration is None else round(concentration, 4)),
            "personAgreement": (max(buys, sells) / voters if voters else None),
        }
    return output
