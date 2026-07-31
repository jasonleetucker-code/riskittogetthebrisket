#!/usr/bin/env python3
"""Materialize the Sharp production-population fix on the feature branch.

This temporary script exists because the GitHub connector writes whole files
but does not apply textual patches. It is deleted by the workflow after the
patches and tests succeed.
"""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing patch anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_parser() -> None:
    path = Path("src/platforms/ffpc/parser.py")
    text = path.read_text(encoding="utf-8")
    if "from src.platforms.ffpc.league_home import" in text:
        return

    text = text.replace(
        "from src.platforms.ffpc.identity import resolve_identity\n",
        "from src.platforms.ffpc.identity import resolve_identity\n"
        "from src.platforms.ffpc.league_home import (\n"
        "    parse_action_statement,\n"
        "    parse_asset_label,\n"
        "    split_action_statements,\n"
        ")\n",
        1,
    )
    text = text.replace(
        '"points_for": {"points for", "pf", "pts for"},',
        '"points_for": {"points for", "pf", "pts for", "pts", "points"},',
        1,
    )
    text = text.replace(
        'for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", '
        '"%m/%d/%Y", "%Y-%m-%d %H:%M"):',
        'for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", '
        '"%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d %H:%M"):',
        1,
    )
    text = text.replace(
        '("teamid", "entryid"),',
        '("viewingteam", "teamid", "entryid"),',
    )
    text = text.replace(
        "        for _table, rows in tables:\n"
        "            team_count = len(rows)\n"
        "            for row in rows:\n",
        "        for _table, rows in tables:\n"
        "            rows = [\n"
        "                row\n"
        "                for row in rows\n"
        "                if _text(row.get(\"team\"))\n"
        "                and _int(row.get(\"wins\")) is not None\n"
        "                and _int(row.get(\"losses\")) is not None\n"
        "            ]\n"
        "            team_count = len(rows)\n"
        "            for row in rows:\n",
        1,
    )

    loop_anchor = (
        "        for row in candidates:\n"
        '            tx_type = _tx_type(row.get("type"))\n'
    )
    expanded = '''        team_ids_by_name: dict[str, str] = {}
        for link in soup.find_all("a", href=True):
            linked_team_id = _query_id(
                link.get("href"), "viewingteam", "teamid", "entryid"
            )
            linked_name = normalize_asset_name(_text(link))
            if linked_team_id and linked_name:
                team_ids_by_name[linked_name] = linked_team_id

        expanded_candidates: list[dict[str, Any]] = []
        for row in candidates:
            if _tx_type(row.get("type")):
                expanded_candidates.append(row)
                continue
            parsed_any = False
            for statement in split_action_statements(
                row.get("_action_tag") or row.get("action")
            ):
                parsed = parse_action_statement(statement)
                if parsed is None:
                    continue
                asset = parse_asset_label(parsed.asset_label)
                expanded_row = dict(row)
                expanded_row["type"] = parsed.transaction_type
                expanded_row["action"] = parsed.action
                expanded_row["player"] = asset.display_name
                expanded_row["counterparty"] = parsed.counterparty or row.get(
                    "counterparty"
                )
                if parsed.faab_bid is not None:
                    expanded_row["faab"] = parsed.faab_bid
                expanded_row["_ffpc_asset_label"] = parsed.asset_label
                expanded_row["_ffpc_asset_type"] = asset.asset_type
                expanded_row["_ffpc_pick_season"] = asset.pick_season
                expanded_row["_ffpc_pick_round"] = asset.pick_round
                expanded_row["_ffpc_pick_owner_or_slot"] = asset.pick_owner_or_slot
                if asset.nfl_team:
                    expanded_row["nfl_team"] = asset.nfl_team
                if asset.position:
                    expanded_row["position"] = asset.position
                expanded_candidates.append(expanded_row)
                parsed_any = True
            if not parsed_any:
                expanded_candidates.append(row)
        candidates = expanded_candidates

        for row in candidates:
            tx_type = _tx_type(row.get("type"))
'''
    if loop_anchor not in text:
        raise RuntimeError("missing parser transaction loop anchor")
    text = text.replace(loop_anchor, expanded, 1)

    transaction_start = text.index("    def _parse_transactions(")
    section = text[transaction_start:]
    team_anchor = '''            team_id = _data_or_query(
                team_tag,
                None,
                ("data-team-id", "data-entry-id"),
                ("viewingteam", "teamid", "entryid"),
            )
            global_id = _data_or_query(
'''
    team_replacement = '''            team_id = _data_or_query(
                team_tag,
                None,
                ("data-team-id", "data-entry-id"),
                ("viewingteam", "teamid", "entryid"),
            ) or team_ids_by_name.get(normalize_asset_name(team_name))
            global_id = _data_or_query(
'''
    if team_anchor not in section:
        raise RuntimeError("missing parser team id anchor")
    section = section.replace(team_anchor, team_replacement, 1)
    text = text[:transaction_start] + section

    counterparty_anchor = '''            counterparty_team_id = _text(row.get("counterparty_team_id")) or None
            counterparty_name = _text(row.get("counterparty")) or None
'''
    counterparty_replacement = '''            counterparty_name = _text(row.get("counterparty")) or None
            counterparty_team_id = (
                _text(row.get("counterparty_team_id"))
                or team_ids_by_name.get(normalize_asset_name(counterparty_name))
                or None
            )
'''
    if counterparty_anchor not in text:
        raise RuntimeError("missing parser counterparty anchor")
    text = text.replace(counterparty_anchor, counterparty_replacement, 1)

    block_start = text.index(
        '            asset_name = _text(row.get("player"))', transaction_start
    )
    block_end = text.index(
        '            source_asset_id = _row_source_id(', block_start
    )
    asset_block = '''            asset_name = _text(row.get("player"))
            source_asset_label = _text(row.get("_ffpc_asset_label")) or asset_name
            configured_asset_type = _text(row.get("_ffpc_asset_type"))
            pick_match = re.search(
                r"\\b(20\\d{2})\\s*(?:(?:round|rd|r)\\s*)?([1-7])(?:st|nd|rd|th)?\\b",
                source_asset_label.lower(),
            )
            slot_match = re.search(
                r"\\b(20\\d{2})\\s+draft\\s+pick\\s+([1-7])\\.(\\d{1,2})\\b",
                source_asset_label.lower(),
            )
            asset_type = configured_asset_type or (
                "pick" if pick_match or slot_match else "player"
            )
            pick_season = _text(row.get("_ffpc_pick_season")) or (
                slot_match.group(1)
                if slot_match
                else pick_match.group(1) if pick_match else None
            )
            pick_round = _text(row.get("_ffpc_pick_round")) or (
                slot_match.group(2)
                if slot_match
                else pick_match.group(2) if pick_match else None
            )
            pick_owner = _text(row.get("_ffpc_pick_owner_or_slot")) or _text(
                row.get("original_owner")
            ) or None
            if not pick_owner and slot_match:
                pick_owner = f"slot-{int(slot_match.group(3))}"
            if not pick_owner and asset_type == "pick":
                owner_match = re.search(
                    r"(?:from|original(?:ly)? owned by)\\s+(.+)$",
                    source_asset_label,
                    re.I,
                )
                pick_owner = owner_match.group(1).strip() if owner_match else None
            normalized_pick_owner = (
                re.sub(r"\\s+", "-", pick_owner.strip().lower()) if pick_owner else None
            )
'''
    text = text[:block_start] + asset_block + text[block_end:]
    path.write_text(text, encoding="utf-8")


def patch_market() -> None:
    path = Path("src/sharp/market.py")
    text = path.read_text(encoding="utf-8")
    if "def provisional_members(" in text:
        return
    text = text.replace(
        '_ALLOWED_QUALIFICATION = ("all", "automated", "curated")',
        '_ALLOWED_QUALIFICATION = ("all", "automated", "curated", "provisional")',
        1,
    )
    marker = "\n\ndef cohort_members(\n"
    provisional_code = '''

def provisional_members(
    config: dict[str, Any],
    *,
    ledger_path: Path | None = None,
) -> list[CohortMember]:
    """Select public FFPC observations without claiming sharp-v2 qualification."""
    if not bool(config.get("enabled")) or not bool(
        config.get("allowProvisionalPublicInCombinedSignals")
    ):
        return []
    league_keys = [
        f"ffpc:{str(source.get('sourceLeagueId') or '').strip()}"
        for source in config.get("seedLeagues") or []
        if isinstance(source, dict)
        and bool(source.get("enabled", True))
        and bool(source.get("allowProvisionalContribution"))
        and str(source.get("sourceLeagueId") or "").strip()
    ]
    if not league_keys:
        return []
    weight = max(
        0.0,
        min(1.0, float(config.get("provisionalPublicWeight") or 0.5)),
    )
    placeholders = ",".join("?" for _ in league_keys)
    conn = platform_ledger.ensure_platform_schema(ledger_path)
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT am.manager_key, pm.display_name
              FROM asset_movements am
              JOIN transactions tx
                ON tx.transaction_key=am.transaction_key
              LEFT JOIN platform_managers pm
                ON pm.manager_key=am.manager_key
             WHERE am.platform='ffpc'
               AND am.league_key IN ({placeholders})
               AND tx.tx_type='trade'
               AND am.manager_key IS NOT NULL
            """,
            league_keys,
        ).fetchall()
    finally:
        conn.close()
    return [
        CohortMember(
            manager_key=str(row["manager_key"]),
            platform="ffpc",
            qualification_method="provisional_public",
            quality=weight,
            display_name=str(row["display_name"] or "") or None,
            source_rationale=(
                "Observed on an explicitly configured public FFPC dynasty page; "
                "has not passed Sharp Score v2 history gates."
            ),
        )
        for row in rows
    ]
'''
    if marker not in text:
        raise RuntimeError("missing market cohort marker")
    text = text.replace(marker, provisional_code + marker, 1)

    selection_anchor = '''    curated_enabled = bool(ffpc_enabled and config.get("allowCuratedInCombinedSignals"))
    curated = curated_members(config) if curated_enabled else []
    if qualification == "automated":
        selected = automatic
    elif qualification == "curated":
        selected = curated
    else:
        selected = [*automatic, *curated]
'''
    selection_replacement = '''    curated_enabled = bool(ffpc_enabled and config.get("allowCuratedInCombinedSignals"))
    curated = curated_members(config) if curated_enabled else []
    provisional_enabled = bool(
        ffpc_enabled and config.get("allowProvisionalPublicInCombinedSignals")
    )
    provisional = (
        provisional_members(config, ledger_path=ledger_path)
        if provisional_enabled
        else []
    )
    if qualification == "automated":
        selected = automatic
    elif qualification == "curated":
        selected = curated
    elif qualification == "provisional":
        selected = provisional
    else:
        selected = [*automatic, *curated, *provisional]
'''
    if selection_anchor not in text:
        raise RuntimeError("missing market selection anchor")
    text = text.replace(selection_anchor, selection_replacement, 1)

    dedupe_anchor = '''    by_key: dict[str, CohortMember] = {}
    for item in selected:
        prior = by_key.get(item.manager_key)
        if (
            prior is None
            or item.qualification_method == "automated_qualified"
            or item.quality > prior.quality
        ):
            by_key[item.manager_key] = item
'''
    dedupe_replacement = '''    by_key: dict[str, CohortMember] = {}
    priority = {
        "provisional_public": 1,
        "curated_high_stakes": 2,
        "automated_qualified": 3,
    }
    for item in selected:
        prior = by_key.get(item.manager_key)
        if prior is None or (
            priority.get(item.qualification_method, 0), item.quality
        ) > (priority.get(prior.qualification_method, 0), prior.quality):
            by_key[item.manager_key] = item
'''
    if dedupe_anchor not in text:
        raise RuntimeError("missing market method-priority anchor")
    text = text.replace(dedupe_anchor, dedupe_replacement, 1)

    coverage_anchor = '''        "curatedManagers": len(curated),
        "curatedContributionEnabled": curated_enabled,
        "evidenceManagers": len(evidence),
'''
    coverage_replacement = '''        "curatedManagers": len(curated),
        "curatedContributionEnabled": curated_enabled,
        "provisionalManagers": len(provisional),
        "provisionalContributionEnabled": provisional_enabled,
        "evidenceManagers": len(evidence),
'''
    if coverage_anchor not in text:
        raise RuntimeError("missing market cohort coverage anchor")
    text = text.replace(coverage_anchor, coverage_replacement, 1)

    text = text.replace(
        '''    automated_by_platform = {"sleeper": 0, "ffpc": 0}
    curated_by_platform = {"sleeper": 0, "ffpc": 0}
''',
        '''    automated_by_platform = {"sleeper": 0, "ffpc": 0}
    curated_by_platform = {"sleeper": 0, "ffpc": 0}
    provisional_by_platform = {"sleeper": 0, "ffpc": 0}
''',
        1,
    )
    target_anchor = '''        target = (
            automated_by_platform
            if item.qualification_method == "automated_qualified"
            else curated_by_platform
        )
'''
    target_replacement = '''        if item.qualification_method == "automated_qualified":
            target = automated_by_platform
        elif item.qualification_method == "curated_high_stakes":
            target = curated_by_platform
        else:
            target = provisional_by_platform
'''
    if target_anchor not in text:
        raise RuntimeError("missing source qualification coverage anchor")
    text = text.replace(target_anchor, target_replacement, 1)
    text = text.replace(
        '''        value["curatedManagers"] = curated_by_platform.get(name, 0)
        value["enabled"] = name != "ffpc" or bool(config.get("enabled"))
''',
        '''        value["curatedManagers"] = curated_by_platform.get(name, 0)
        value["provisionalManagers"] = provisional_by_platform.get(name, 0)
        value["enabled"] = name != "ffpc" or bool(config.get("enabled"))
''',
        1,
    )
    path.write_text(text, encoding="utf-8")


def patch_service() -> None:
    path = Path("src/sharp/service.py")
    text = path.read_text(encoding="utf-8")
    if '"provisionalManagers": len(provisional)' in text:
        return
    text = text.replace(
        '''    curated = (
        sharp_market.curated_members(config) if config.get("allowCuratedInCombinedSignals") else []
    )
    status = STATUS_OK if tiers.get("qualifiedManagers", 0) > 0 or curated else STATUS_BUILDING
''',
        '''    curated = (
        sharp_market.curated_members(config) if config.get("allowCuratedInCombinedSignals") else []
    )
    provisional = sharp_market.provisional_members(config)
    status = (
        STATUS_OK
        if tiers.get("qualifiedManagers", 0) > 0 or curated or provisional
        else STATUS_BUILDING
    )
''',
        1,
    )
    text = text.replace(
        '''            "curatedManagers": len(curated),
            "observedLeagues": graph.get("observedLeagues", coverage.get("leagueCount", 0))
''',
        '''            "curatedManagers": len(curated),
            "provisionalManagers": len(provisional),
            "observedLeagues": graph.get("observedLeagues", coverage.get("leagueCount", 0))
''',
        1,
    )
    text = text.replace(
        '''            "curatedContributionEnabled": bool(config.get("allowCuratedInCombinedSignals")),
''',
        '''            "curatedContributionEnabled": bool(config.get("allowCuratedInCombinedSignals")),
            "provisionalContributionEnabled": bool(
                config.get("allowProvisionalPublicInCombinedSignals")
            ),
''',
        1,
    )
    text = text.replace(
        '"FFPC includes only explicitly configured public pages. Curated FFPC members "\n'
        '            "are never represented as Sharp Score v2 qualifiers."',
        '"FFPC includes only explicitly configured public pages. Curated and "\n'
        '            "provisional FFPC members are never represented as Sharp Score v2 qualifiers."',
        1,
    )
    path.write_text(text, encoding="utf-8")


def patch_crawler() -> None:
    path = Path("scripts/crawl_ffpc_sharp.py")
    text = path.read_text(encoding="utf-8")
    if "source_failures: list[dict[str, str]]" in text:
        return
    text = text.replace(
        "    reports = []\n    try:\n",
        "    reports = []\n"
        "    source_failures: list[dict[str, str]] = []\n"
        "    successful_sources = 0\n"
        "    try:\n",
        1,
    )
    block_start = text.index('                page_source = {**source, "publicUrl": url}')
    block_end = text.index("\n\n        # Curated identities", block_start)
    replacement = '''                page_source = {**source, "publicUrl": url}
                try:
                    batch = adapter.fetch_source(
                        page_source,
                        force_refresh=args.force_refresh,
                        fixture_html=fixture_html,
                    )
                    _merge_counters(counters, batch.counters)
                    successful_sources += 1
                    if args.dry_run:
                        reports.append(
                            {
                                "sourceLeagueId": source.get("sourceLeagueId"),
                                "url": url,
                                "managers": len(batch.managers),
                                "transactions": len(batch.transactions),
                                "movements": len(batch.movements),
                                "managerSeasons": len(batch.manager_seasons),
                                "warnings": batch.warnings,
                            }
                        )
                    else:
                        ingest = platform_ledger.ingest_batch(batch)
                        counters["movementsInserted"] = (
                            counters.get("movementsInserted", 0)
                            + ingest.movements_inserted
                        )
                        counters["movementsSkipped"] = (
                            counters.get("movementsSkipped", 0)
                            + ingest.movements_skipped
                        )
                        counters["transactionsDeduplicated"] = counters.get(
                            "transactionsDeduplicated", 0
                        ) + max(0, ingest.transactions_seen - ingest.transactions_inserted)
                        reports.append(
                            {
                                "sourceLeagueId": source.get("sourceLeagueId"),
                                "url": url,
                                "ingest": ingest.to_dict(),
                                "warnings": batch.warnings,
                            }
                        )
                except Exception as source_exc:  # noqa: BLE001
                    counters["parseFailures"] = counters.get("parseFailures", 0) + 1
                    failure = {
                        "sourceLeagueId": str(source.get("sourceLeagueId") or ""),
                        "url": url,
                        "type": type(source_exc).__name__,
                        "message": str(source_exc),
                    }
                    source_failures.append(failure)
                    reports.append({**failure, "status": "failed"})
                    log.exception(
                        "FFPC source failed without aborting remaining sources: %s", url
                    )

        if successful_sources == 0:
            raise RuntimeError("all configured FFPC public sources failed")
'''
    text = text[:block_start] + replacement + text[block_end:]
    text = text.replace(
        '''            curated, _ = sharp_market.cohort_members(
                qualification="curated",
                ffpc_config=config,
            )
''',
        '''            curated, _ = sharp_market.cohort_members(
                qualification="curated",
                ffpc_config=config,
            )
            provisional, _ = sharp_market.cohort_members(
                qualification="provisional",
                ffpc_config=config,
            )
''',
        1,
    )
    text = text.replace(
        '''            counters["curatedFfpcContributors"] = sum(
                1 for member in curated if member.platform == "ffpc"
            )
            platform_ledger.record_ingestion_run(
''',
        '''            counters["curatedFfpcContributors"] = sum(
                1 for member in curated if member.platform == "ffpc"
            )
            counters["provisionalFfpcContributors"] = sum(
                1 for member in provisional if member.platform == "ffpc"
            )
            platform_ledger.record_ingestion_run(
''',
        1,
    )
    text = text.replace(
        '                status="success",\n',
        '                status="partial_success" if source_failures else "success",\n',
        1,
    )
    text = text.replace(
        '            "status": "dry_run" if args.dry_run else "success",\n',
        '''            "status": (
                "dry_run_partial"
                if args.dry_run and source_failures
                else "dry_run"
                if args.dry_run
                else "partial_success"
                if source_failures
                else "success"
            ),
''',
        1,
    )
    text = text.replace(
        '''            "reports": reports,
            "coverage": ({} if args.dry_run else platform_ledger.platform_coverage()),
''',
        '''            "reports": reports,
            "sourceFailures": source_failures,
            "coverage": ({} if args.dry_run else platform_ledger.platform_coverage()),
''',
        1,
    )
    path.write_text(text, encoding="utf-8")


def patch_deploy() -> None:
    installer = Path("deploy/install-systemd-service.sh")
    text = installer.read_text(encoding="utf-8")
    if "FFPC public Sharp ingestion timer" not in text:
        insert_at = text.index(
            "\n  # ── Reception-depth histogram timer",
            text.index("Sharp Tracker season-records timer"),
        )
        ffpc_section = '''

  # ── FFPC public Sharp ingestion timer ───────────────────────────────
  local ffpc_service_template="${APP_DIR}/deploy/systemd/dynasty-ffpc-sharp.service.template"
  local ffpc_timer_template="${APP_DIR}/deploy/systemd/dynasty-ffpc-sharp.timer.template"
  local ffpc_service_name="${SERVICE_NAME}-ffpc-sharp"
  local ffpc_service_path="/etc/systemd/system/${ffpc_service_name}.service"
  local ffpc_timer_path="/etc/systemd/system/${ffpc_service_name}.timer"
  local ffpc_needs_install=false
  local ffpc_enabled=false
  if [[ -f "${APP_DIR}/config/sharp/ffpc_sources.json" ]] && \\
     grep -m1 -Eq '"enabled"[[:space:]]*:[[:space:]]*true' \\
       "${APP_DIR}/config/sharp/ffpc_sources.json"; then
    ffpc_enabled=true
  fi
  if [[ "${ffpc_enabled}" == "true" && -f "${ffpc_service_template}" && -f "${ffpc_timer_template}" ]]; then
    if sudo -n "${SYSTEMCTL_BIN}" cat "${ffpc_service_name}.timer" >/dev/null 2>&1; then
      if [[ "${force_install_on}" == "true" ]]; then
        ffpc_needs_install=true
      fi
    else
      log "Installing FFPC public Sharp ingestion service + timer."
      ffpc_needs_install=true
    fi
    if [[ "${ffpc_needs_install}" == "true" ]]; then
      local tmp_ffpc_service tmp_ffpc_timer
      tmp_ffpc_service="$(mktemp)"
      tmp_ffpc_timer="$(mktemp)"
      sed \\
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \\
        -e "s/__APP_USER__/$(escape_sed_replacement "${APP_USER}")/g" \\
        -e "s/__APP_DIR__/$(escape_sed_replacement "${APP_DIR}")/g" \\
        -e "s/__VENV_DIR__/$(escape_sed_replacement "${VENV_DIR}")/g" \\
        "${ffpc_service_template}" > "${tmp_ffpc_service}"
      sed \\
        -e "s/__SERVICE_NAME__/$(escape_sed_replacement "${SERVICE_NAME}")/g" \\
        "${ffpc_timer_template}" > "${tmp_ffpc_timer}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_ffpc_service}" "${ffpc_service_path}"
      sudo -n "${INSTALL_BIN}" -m 0644 "${tmp_ffpc_timer}" "${ffpc_timer_path}"
      rm -f "${tmp_ffpc_service}" "${tmp_ffpc_timer}"
      log "Installed ${ffpc_service_name}.service + .timer"
    fi
  fi
'''
        text = text[:insert_at] + ffpc_section + text[insert_at:]

    old_condition = (
        '  if [[ "${backend_needs_install}" == "true" || '
        '"${frontend_needs_install}" == "true" || '
        '"${alerts_needs_install}" == "true" || '
        '"${custom_alerts_needs_install}" == "true" || '
        '"${dlf_fetch_needs_install}" == "true" || '
        '"${idpshow_fetch_needs_install}" == "true" ]]; then\n'
    )
    new_condition = (
        '  if [[ "${backend_needs_install}" == "true" || '
        '"${frontend_needs_install}" == "true" || '
        '"${alerts_needs_install}" == "true" || '
        '"${custom_alerts_needs_install}" == "true" || '
        '"${playerctx_needs_install}" == "true" || '
        '"${bdvm_needs_install}" == "true" || '
        '"${sharp_needs_install}" == "true" || '
        '"${sharprec_needs_install}" == "true" || '
        '"${ffpc_needs_install}" == "true" || '
        '"${rd_needs_install}" == "true" || '
        '"${dlf_fetch_needs_install}" == "true" || '
        '"${idpshow_fetch_needs_install}" == "true" ]]; then\n'
    )
    if old_condition in text:
        text = text.replace(old_condition, new_condition, 1)
    elif '"${ffpc_needs_install}"' not in text:
        raise RuntimeError("missing installer daemon-reload condition")

    records_anchor = '''  if [[ "${sharprec_needs_install}" == "true" ]]; then
    # --now arms the daily timer.  No initial kick: the discovery crawl
    # kicked above must populate the sharp-eligible league list first,
    # and the 04:50 slot already sequences this after it.
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${sharprec_service_name}.timer"
    log "Enabled ${sharprec_service_name}.timer"
  fi
'''
    records_replacement = '''  if [[ -f "${sharprec_service_template}" && -f "${sharprec_timer_template}" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${sharprec_service_name}.timer"
    log "Enabled ${sharprec_service_name}.timer"
    sudo -n "${SYSTEMCTL_BIN}" start --no-block "${sharprec_service_name}.service" || \\
      log "Note: initial sharp-records crawl could not be started; the timer will cover it."
  fi
  if [[ "${ffpc_enabled}" == "true" && -f "${ffpc_service_template}" && -f "${ffpc_timer_template}" ]]; then
    sudo -n "${SYSTEMCTL_BIN}" enable --now "${ffpc_service_name}.timer"
    log "Enabled ${ffpc_service_name}.timer"
    sudo -n "${SYSTEMCTL_BIN}" start --no-block "${ffpc_service_name}.service" || \\
      log "Note: initial FFPC public crawl could not be started; the timer will cover it."
  fi
'''
    if records_anchor in text:
        text = text.replace(records_anchor, records_replacement, 1)
    elif "initial FFPC public crawl" not in text:
        raise RuntimeError("missing records timer bootstrap anchor")
    installer.write_text(text, encoding="utf-8")

    deploy = Path("deploy/deploy.sh")
    text = deploy.read_text(encoding="utf-8")
    timer_anchor = '''    if ! sudo -n "${SYSTEMCTL_BIN}" cat "${timer_unit}" >/dev/null 2>&1; then
      missing_timers="${missing_timers} ${timer_unit}"
    fi
'''
    timer_replacement = '''    if ! sudo -n "${SYSTEMCTL_BIN}" cat "${timer_unit}" >/dev/null 2>&1 || \\
       ! sudo -n "${SYSTEMCTL_BIN}" is-enabled "${timer_unit}" >/dev/null 2>&1; then
      missing_timers="${missing_timers} ${timer_unit}"
    fi
'''
    if timer_anchor in text:
        text = text.replace(timer_anchor, timer_replacement, 1)
    deploy.write_text(text, encoding="utf-8")

    service = Path("deploy/systemd/dynasty-sharp-records.service.template")
    text = service.read_text(encoding="utf-8")
    text = text.replace(
        "ExecStart=__VENV_DIR__/bin/python __APP_DIR__/scripts/crawl_sharp_records.py",
        "ExecStart=__VENV_DIR__/bin/python __APP_DIR__/scripts/crawl_sharp_records.py --budget 5000",
        1,
    ).replace("TimeoutStartSec=1800", "TimeoutStartSec=3600", 1)
    service.write_text(text, encoding="utf-8")


def patch_frontend() -> None:
    path = Path("frontend/app/market/sharp-tracker/page.jsx")
    text = path.read_text(encoding="utf-8")
    if '<option value="provisional">' in text:
        return
    text = text.replace(
        '''    if (methods.length > 1) return "Mixed cohort";
    if (methods[0] === "curated_high_stakes") return "Curated FFPC high-stakes cohort";
    return "Automated Sharp Score";
''',
        '''    if (methods.length > 1) return "Mixed cohort";
    if (methods[0] === "curated_high_stakes") return "Curated FFPC high-stakes cohort";
    if (methods[0] === "provisional_public") return "Provisional public FFPC activity";
    return "Automated Sharp Score";
''',
        1,
    )
    text = text.replace(
        '''      <Stat label="Curated" value={cohortStats.curatedManagers ?? market?.cohort?.curatedManagers} note="separately labeled FFPC cohort" />
      <Stat label="Assets" value={assets.length} note={`activity in ${windowName}`} />
''',
        '''      <Stat label="Curated" value={cohortStats.curatedManagers ?? market?.cohort?.curatedManagers} note="verified high-stakes cohort" />
      <Stat label="Provisional" value={cohortStats.provisionalManagers ?? market?.cohort?.provisionalManagers} note="public FFPC activity, not sharp-v2" />
      <Stat label="Assets" value={assets.length} note={`activity in ${windowName}`} />
''',
        1,
    )
    text = text.replace(
        '''<option value="all">Automated + allowed curated</option><option value="automated">Automated only</option><option value="curated">Curated only</option>''',
        '''<option value="all">All allowed methods</option><option value="automated">Automated only</option><option value="curated">Curated only</option><option value="provisional">Provisional FFPC only</option>''',
        1,
    )
    text = text.replace(
        '''Automated managers passed the unchanged Sharp Score v2 evidence gates. Curated FFPC high-stakes managers are a separate method with a configured weight and only contribute when explicitly enabled. Name-only or league-scoped FFPC identities cannot satisfy automated multi-league qualification.''',
        '''Automated managers passed the unchanged Sharp Score v2 evidence gates. Curated FFPC high-stakes managers and provisional public FFPC observations are separately labeled methods with configured weights. Provisional activity can populate the market table, but it is never presented as sharp-v2 qualification. Name-only or league-scoped FFPC identities cannot satisfy automated multi-league qualification.''',
        1,
    )
    path.write_text(text, encoding="utf-8")


def write_tests_and_docs() -> None:
    Path("tests/sharp/test_provisional_ffpc.py").write_text(
        '''from src.intel import platform_ledger
from src.platforms.base import (
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedMovement,
    NormalizedTransaction,
)
from src.sharp import market

NOW = 1_800_000_000_000


def _batch():
    return NormalizedBatch(
        platform="ffpc",
        managers=[NormalizedManager.build("ffpc", "league:L1:team:1")],
        leagues=[NormalizedLeague.build("ffpc", "L1", format_type="dynasty")],
        transactions=[
            NormalizedTransaction.build(
                "ffpc",
                "T1",
                league_key="ffpc:L1",
                season="2026",
                week=1,
                transaction_type="trade",
                status="complete",
                created_ms=NOW - 1000,
            )
        ],
        movements=[
            NormalizedMovement.build(
                "ffpc",
                "M1",
                transaction_key="ffpc:T1",
                league_key="ffpc:L1",
                canonical_asset_id="P1",
                source_asset_id="name:p1",
                source_name="Public Player",
                asset_type="player",
                action="add",
                manager_key="ffpc:league:L1:team:1",
                roster_id="1",
                counterparty_manager_key=None,
                timestamp_ms=NOW - 1000,
            )
        ],
    )


def _config(enabled=True):
    return {
        "enabled": enabled,
        "allowProvisionalPublicInCombinedSignals": True,
        "provisionalPublicWeight": 0.55,
        "seedLeagues": [
            {
                "sourceLeagueId": "L1",
                "enabled": True,
                "allowProvisionalContribution": True,
            }
        ],
    }


def test_public_ffpc_activity_is_usable_but_never_claims_sharp_v2(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(_batch(), path=path)
    selected, coverage = market.cohort_members(
        qualification="provisional",
        ledger_path=path,
        ffpc_config=_config(),
    )
    assert len(selected) == 1
    assert selected[0].qualification_method == "provisional_public"
    assert selected[0].quality == 0.55
    assert coverage["provisionalContributionEnabled"] is True

    payload = market.market_payload(
        window="30d",
        qualification="provisional",
        now_ms=NOW,
        ledger_path=path,
        ffpc_config=_config(),
    )
    assert payload["status"] == "ok"
    assert payload["assets"][0]["windows"]["30d"]["buys"] == 1
    assert payload["cohort"]["qualificationMethods"] == ["provisional_public"]


def test_disabling_ffpc_removes_provisional_members(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(_batch(), path=path)
    selected, coverage = market.cohort_members(
        qualification="provisional",
        ledger_path=path,
        ffpc_config=_config(enabled=False),
    )
    assert selected == []
    assert coverage["provisionalContributionEnabled"] is False
''',
        encoding="utf-8",
    )
    Path("tests/deploy/test_sharp_population_jobs.py").write_text(
        '''from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_normal_deploy_installs_and_kicks_all_sharp_population_jobs():
    installer = (ROOT / "deploy" / "install-systemd-service.sh").read_text()
    deploy = (ROOT / "deploy" / "deploy.sh").read_text()
    assert "sharp_needs_install" in installer.split("daemon-reload", 1)[0]
    assert "sharprec_needs_install" in installer.split("daemon-reload", 1)[0]
    assert "ffpc_needs_install" in installer.split("daemon-reload", 1)[0]
    assert 'start --no-block "${sharprec_service_name}.service"' in installer
    assert 'start --no-block "${ffpc_service_name}.service"' in installer
    assert 'is-enabled "${timer_unit}"' in deploy


def test_ffpc_timer_is_daily_and_records_bootstrap_has_large_budget():
    timer = (
        ROOT / "deploy" / "systemd" / "dynasty-ffpc-sharp.timer.template"
    ).read_text()
    records = (
        ROOT / "deploy" / "systemd" / "dynasty-sharp-records.service.template"
    ).read_text()
    assert "OnCalendar=*-*-* 05:20:00 UTC" in timer
    assert "Persistent=true" in timer
    assert "crawl_sharp_records.py --budget 5000" in records
    assert "TimeoutStartSec=3600" in records
''',
        encoding="utf-8",
    )
    Path("frontend/__tests__/sharp-provisional-market.test.js").write_text(
        '''import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const page = fs.readFileSync(
  path.join(process.cwd(), "app/market/sharp-tracker/page.jsx"),
  "utf8",
);

describe("Sharp Tracker provisional FFPC labeling", () => {
  it("offers a real provisional source filter", () => {
    expect(page).toContain('<option value="provisional">Provisional FFPC only</option>');
  });

  it("does not present public FFPC activity as Sharp Score v2", () => {
    expect(page).toContain("Provisional public FFPC activity");
    expect(page).toContain("it is never presented as sharp-v2 qualification");
  });
});
''',
        encoding="utf-8",
    )
    Path("docs/intel/SHARP_PRODUCTION_INGESTION.md").write_text(
        '''# Sharp Tracker production ingestion

## Operational state

The unified Sharp Tracker uses two independent read-only upstream jobs:

1. Sleeper graph discovery and season-record crawling.
2. Public FFPC dynasty-page ingestion.

Both write to the same platform-scoped ledger. The market endpoint then
aggregates canonical assets into one table while retaining source breakdowns.

## Sleeper population

`dynasty-sharp-discovery.timer` grows the public Sleeper graph. The records
job follows it and collects completed season evidence required by Sharp Score
v2. Production deployment now installs, reloads, enables, and immediately
starts both jobs. The records bootstrap uses a 5,000-call budget and a
one-hour service timeout; later daily runs resume from the persistent fair
queue.

Sleeper managers appear as automated qualifiers only after the unchanged
Sharp Score v2 evidence and scoring gates are satisfied.

## FFPC population

`config/sharp/ffpc_sources.json` contains explicitly selected, unauthenticated
public dynasty `LeagueHome.aspx` pages. The adapter performs GET requests only.
It parses visible standings and transactions, normalizes multi-line action
cells, deduplicates the two team perspectives of one trade, resolves assets
onto canonical Sleeper player IDs, and stores unresolved assets for review.

`dynasty-ffpc-sharp.timer` runs once per day at 05:20 UTC with up to a
15-minute randomized delay. It is persistent, so a missed run fires after the
host returns. Deployment also triggers the first run immediately.

One broken public page produces a partial-success report and does not prevent
other configured leagues from updating.

## Qualification labels

- `automated_qualified`: passed Sharp Score v2.
- `curated_high_stakes`: explicitly verified curated record.
- `provisional_public`: observed trade activity from a configured public FFPC
  dynasty league, but historical evidence is insufficient for Sharp Score v2.

Provisional activity is intentionally usable in the default combined market
view at a conservative configured quality weight. It is never described as an
automated qualification. League-scoped identities still cannot satisfy
multi-league Sharp Score requirements.

## Manual operations

```bash
python scripts/crawl_ffpc_sharp.py --public-only --dry-run --verbose
python scripts/crawl_ffpc_sharp.py --public-only
python scripts/crawl_sharp_records.py --budget 5000
systemctl list-timers --all | grep -E 'sharp|ffpc'
journalctl -u dynasty-sharp-records.service -n 200 --no-pager
journalctl -u dynasty-ffpc-sharp.service -n 200 --no-pager
```
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_parser()
    patch_market()
    patch_service()
    patch_crawler()
    patch_deploy()
    patch_frontend()
    write_tests_and_docs()


if __name__ == "__main__":
    main()
