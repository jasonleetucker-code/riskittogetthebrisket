/*
 * Runtime Module: 10-rankings-and-picks.js
 * Rankings pipeline and pick normalization/value helpers.
 * Extracted from legacy monolithic inline runtime to keep live behavior intact.
 */

  // ── RANKINGS TAB ──
  function normalizeRankingsFilterPos(pos) {
    return RANKINGS_POSITION_FILTER_OPTIONS.includes(pos) ? pos : 'ALL';
  }

  function buildRankingsPositionOptionsHtml() {
    return RANKINGS_POSITION_FILTER_OPTIONS
      .map(key => `<option value="${key}">${RANKINGS_POSITION_FILTER_LABELS[key] || key}</option>`)
      .join('');
  }

  function filterRankingsPos(pos, btn) {
    const normalizedPos = normalizeRankingsFilterPos(pos);
    currentRankingsFilter = normalizedPos;
    const prefs = getMobilePrefs();
    prefs.filterPos = normalizedPos;
    saveMobilePrefs(prefs);
    document.querySelectorAll('.pos-filter-btn').forEach(b => b.classList.remove('active'));
    if (btn && btn.classList) btn.classList.add('active');
    else {
      const target = document.querySelector(`.pos-filter-btn[data-pos="${normalizedPos}"]`);
      if (target) target.classList.add('active');
    }
    buildFullRankings();
  }

  function toggleRankingsSort() {
    rankingsSortAsc = !rankingsSortAsc;
    const prefs = getMobilePrefs();
    prefs.sortAsc = rankingsSortAsc;
    saveMobilePrefs(prefs);
    buildFullRankings();
  }

  function copyRankingsComposites(evt) {
    const tbody = document.getElementById('rookieBody');
    if (!tbody) return;

    const sortBasis = getRankingsSortBasis();
    const showAdjCols = showRankingsLAMColumns();
    const modeLabel = (
      sortBasis === 'raw' ? 'Raw Market' :
      sortBasis === 'scoring' ? 'Scoring Adjusted' :
      sortBasis === 'scarcity' ? 'Scarcity Adjusted' :
      'Fully Adjusted'
    );
    const lines = showAdjCols
      ? ['Rank\tPlayer\tPos\tValue\tRaw\tScoring Mult\tAdjusted\tDelta']
      : [`Rank\tPlayer\tPos\t${modeLabel}`];

    let rank = 0;
    tbody.querySelectorAll('tr').forEach(row => {
      if (row.style.display === 'none' || row.classList.contains('tier-separator')) return;
      const cells = row.querySelectorAll('td');
      if (cells.length < 4) return;
      rank++;
      const name = (cells[1]?.textContent || '').trim();
      const pos = (cells[2]?.textContent || '').trim();
      if (!name) return;

      const raw = Number(row.dataset.rawComposite || 0);
      const scoring = Number(row.dataset.scoringComposite || raw);
      const adjusted = Number(row.dataset.adjustedComposite || 0);
      const value = Number(
        row.dataset.sortValue ||
        (
          sortBasis === 'raw' ? raw :
          sortBasis === 'scoring' ? scoring :
          sortBasis === 'scarcity' ? Number(row.dataset.scarcityComposite || scoring) :
          adjusted
        ) ||
        0
      );

      if (!showAdjCols) {
        lines.push(`${rank}\t${name}\t${pos}\t${Math.round(value)}`);
        return;
      }

      let scoringDebug = null;
      try { scoringDebug = JSON.parse(row.dataset.lamDebug || '{}'); } catch(_) { scoringDebug = null; }
      const scoringMult = Number(scoringDebug?.effectiveMultiplier ?? 1);
      const delta = Math.round(adjusted - raw);
      lines.push([
        rank,
        name,
        pos,
        Math.round(value),
        Math.round(raw),
        scoringMult.toFixed(3),
        Math.round(adjusted),
        delta,
      ].join('\t'));
    });

    const text = lines.join('\n');
    const clickedBtn = evt?.currentTarget || evt?.target?.closest?.('button');
    const btn = clickedBtn || document.querySelector('#tab-rookies button[onclick*="copyRankingsComposites"]');
    const original = btn?.textContent || '📋 Copy Values';
    const setBtnLabel = (label) => {
      if (!btn) return;
      btn.textContent = label;
      setTimeout(() => { btn.textContent = original; }, 2000);
    };

    const fallbackCopy = () => {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        ta.style.top = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, ta.value.length);
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        if (ok) {
          setBtnLabel('\u2713 Copied!');
        } else {
          setBtnLabel('\u26A0 Copy failed');
        }
      } catch (_) {
        setBtnLabel('\u26A0 Copy failed');
      }
    };

    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        setBtnLabel('\u2713 Copied!');
      }).catch(() => {
        fallbackCopy();
      });
      return;
    }

    fallbackCopy();
  }

  function buildRisingFallingSection() {
    const card = document.getElementById('trendCard');
    const content = document.getElementById('trendContent');
    const asOf = document.getElementById('trendAsOf');
    if (!card || !content || !asOf) return;

    if (!loadedData || !loadedData.players) {
      card.style.display = 'none';
      return;
    }

    const mode = getRankingsDataMode();
    if (mode !== 'dynasty') {
      card.style.display = 'none';
      return;
    }
    card.style.display = '';

    const prevDate = localStorage.getItem('dynasty_prev_date') || '';
    const currentDate = loadedData?.date || '';
    asOf.textContent = (prevDate && currentDate && prevDate !== currentDate)
      ? `${prevDate} -> ${currentDate}`
      : 'Need prior snapshot';

    const trendMap = window.playerTrends || {};
    const rows = [];
    for (const [name, pct] of Object.entries(trendMap)) {
      const trend = Number(pct);
      if (!isFinite(trend) || trend === 0) continue;
      if (parsePickToken(name)) continue;

      const result = computeMetaValueForPlayer(name);
      if (!result || !isFinite(result.metaValue) || result.metaValue <= 0) continue;
      const pos = (getPlayerPosition(name) || getRookiePosHint(name) || '').toUpperCase();
      if (isKickerPosition(pos)) continue;
      rows.push({
        name,
        pos: pos || '—',
        trend,
        value: Math.round(Number(result.metaValue) || 0),
      });
    }

    if (!rows.length) {
      content.innerHTML = '<div style="color:var(--subtext);font-size:0.72rem;">No rising/falling data yet. Update values again later to see which players are trending up or down.</div>';
      return;
    }

    const risers = rows.filter(r => r.trend > 0).sort((a, b) => b.trend - a.trend).slice(0, 12);
    const fallers = rows.filter(r => r.trend < 0).sort((a, b) => a.trend - b.trend).slice(0, 12);

    const POS_C = {
      QB: '#e74c3c', RB: '#27ae60', WR: '#3498db', TE: '#e67e22',
      DL: '#9b59b6', DE: '#9b59b6', DT: '#9b59b6', EDGE: '#9b59b6',
      LB: '#8e44ad', DB: '#16a085', CB: '#16a085', S: '#16a085',
    };
    const renderList = (list, isRising) => {
      if (!list.length) {
        return '<div style="color:var(--subtext);font-size:0.68rem;">None</div>';
      }
      return list.map(p => {
        const pct = `${p.trend > 0 ? '+' : ''}${p.trend.toFixed(1)}%`;
        const color = isRising ? 'var(--green)' : 'var(--red)';
        const posColor = POS_C[p.pos] || 'var(--subtext)';
        return `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--border-dim);">
          <span style="width:28px;color:${posColor};font-family:var(--mono);font-size:0.62rem;font-weight:700;">${p.pos}</span>
          <span style="flex:1;font-weight:600;">${p.name}</span>
          <span style="font-family:var(--mono);color:var(--subtext);font-size:0.66rem;width:56px;text-align:right;">${p.value.toLocaleString()}</span>
          <span style="font-family:var(--mono);color:${color};font-size:0.7rem;font-weight:700;width:56px;text-align:right;">${pct}</span>
        </div>`;
      }).join('');
    };

    content.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;">
        <div>
          <div style="font-size:0.72rem;font-weight:700;color:var(--green);margin-bottom:6px;">Top Rising</div>
          ${renderList(risers, true)}
        </div>
        <div>
          <div style="font-size:0.72rem;font-weight:700;color:var(--red);margin-bottom:6px;">Top Falling</div>
          ${renderList(fallers, false)}
        </div>
      </div>
    `;
  }

  function getOrBuildRankingsBaseRows(cfg, canonicalCtx, posMap) {
    const playersRef = loadedData?.players || null;
    if (!playersRef || typeof playersRef !== 'object') return [];
    const cacheKey = getRankingsBaseRowsCacheKey(cfg);
    if (
      rankingsBaseRowsCache.playersRef === playersRef &&
      rankingsBaseRowsCache.key === cacheKey &&
      Array.isArray(rankingsBaseRowsCache.rows) &&
      rankingsBaseRowsCache.rows.length
    ) {
      return rankingsBaseRowsCache.rows;
    }

    const rows = [];
    for (const [name, pData] of Object.entries(playersRef)) {
      const pickInfo = parsePickToken(name);
      let result = null;
      let pos = '';
      let isRookie = false;
      let siteDetails = {};

      if (pickInfo) {
        result = computeMetaValueForPlayer(name, { rawOnly: true });
        if (!result || result.metaValue <= 0) continue;
        pos = 'PICK';
      } else {
        result = computeMetaValueForPlayer(name, { rawOnly: true });
        if (!result || result.metaValue <= 0) continue;
        pos = (posMap[name] || '').toUpperCase();
        if (!pos) pos = getRookiePosHint(name);
        if (isKickerPosition(pos)) continue;
        isRookie = isRookiePlayerName(name, pData);
      }

      const pickValuesCanonical = !!(pickInfo && (result?.siteDetails?.__canonical || pData?.__canonical));
      const playerIsTE = !pickInfo && isPlayerTE(name);
      const playerIsIdp = !pickInfo && ['DL','DE','DT','LB','DB','CB','S','EDGE'].includes(pos);
      const hasBackendCanonicalMap = !!(
        pData &&
        typeof pData._canonicalSiteValues === 'object' &&
        Object.keys(pData._canonicalSiteValues).length
      );
      cfg.forEach(sc => {
        const canonicalStored = Number(pData?._canonicalSiteValues?.[sc.key]);
        if (hasBackendCanonicalMap) {
          // Rankings source columns should mirror backend canonical output when present.
          // Do not synthesize missing keys from raw site data in this path.
          if (Number.isFinite(canonicalStored) && canonicalStored > 0) {
            siteDetails[sc.key] = Math.round(canonicalStored);
          }
          return;
        }
        if (Number.isFinite(canonicalStored) && canonicalStored > 0) {
          siteDetails[sc.key] = Math.round(canonicalStored);
          return;
        }
        const canonicalFromResult = Number(result?.siteDetails?.[sc.key]);
        if (Number.isFinite(canonicalFromResult) && canonicalFromResult > 0) {
          siteDetails[sc.key] = Math.round(canonicalFromResult);
          return;
        }
        const rawStored = pData?.[sc.key];
        if (rawStored == null || !isFinite(rawStored)) return;
        const transformed = getCanonicalSiteValueForSource(sc, rawStored, {
          ctx: canonicalCtx,
          playerName: name,
          playerData: pData,
          playerPos: pickInfo ? 'PICK' : pos,
          playerIsTE,
          playerIsIdp,
          isPick: !!pickInfo,
          pickValuesCanonical,
        });
        if (isFinite(transformed) && transformed > 0) {
          siteDetails[sc.key] = Math.round(transformed);
        }
      });
      if (result?.siteDetails?.__canonical) siteDetails.__canonical = 'yes';

      const backendRaw = Number(!pickInfo ? (pData?._rawComposite ?? pData?._rawMarketValue ?? pData?._composite) : NaN);
      const rawComposite = (
        !pickInfo && Number.isFinite(backendRaw) && backendRaw > 0
      )
        ? clampValue(Math.round(backendRaw), 1, COMPOSITE_SCALE)
        : clampValue(Math.round(Number(result.rawMarketValue ?? result.metaValue) || 0), 1, COMPOSITE_SCALE);
      const backendSiteCount = Number(pData?._sites);
      const adjustment = getPrecomputedAdjustmentBundle(pData, rawComposite, pos, name)
        || computeFinalAdjustedValue(rawComposite, pos, name, { preferPrecomputed: false });
      rows.push({
        name,
        pos,
        composite: rawComposite,
        rawComposite,
        scoringComposite: adjustment.scoringAdjustedValue,
        scarcityComposite: adjustment.scarcityAdjustedValue,
        adjustedComposite: adjustment.finalAdjustedValue,
        adjustment,
        siteCount: (Number.isFinite(backendSiteCount) && backendSiteCount > 0)
          ? Math.round(backendSiteCount)
          : result.siteCount,
        isRookie,
        pData: siteDetails,
        sourceData: pData || {},
        cv: result.cv || 0,
      });
    }

    rankingsBaseRowsCache = {
      playersRef,
      key: cacheKey,
      rows,
    };
    return rows;
  }

  function dedupeRankingsRowsByName(rows = []) {
    const out = [];
    const idxByNorm = new Map();
    for (const row of (rows || [])) {
      if (!row || !row.name) continue;
      // Keep pick rows untouched; dedupe focuses on player-name punctuation variants.
      if (row.pos === 'PICK') {
        out.push(row);
        continue;
      }
      const norm = normalizeForLookup(row.name);
      if (!norm) {
        out.push(row);
        continue;
      }
      const existingIdx = idxByNorm.get(norm);
      if (existingIdx == null) {
        idxByNorm.set(norm, out.length);
        out.push(row);
        continue;
      }
      const cur = out[existingIdx];
      const rowSort = Number(row.sortValue || 0);
      const curSort = Number(cur.sortValue || 0);
      const rowSites = Number(row.siteCount || 0);
      const curSites = Number(cur.siteCount || 0);
      const rowRaw = Number(row.rawComposite || 0);
      const curRaw = Number(cur.rawComposite || 0);
      const keepRow =
        (rowSort > curSort) ||
        (rowSort === curSort && rowSites > curSites) ||
        (rowSort === curSort && rowSites === curSites && rowRaw > curRaw);
      if (keepRow) out[existingIdx] = row;
    }
    return out;
  }

  function getTopKtcBaselineNames(limit = 400) {
    const playersRef = loadedData?.players || null;
    const useLimit = Math.max(1, Math.round(Number(limit) || 400));
    if (!playersRef || typeof playersRef !== 'object') return [];
    if (
      rankingsTopKtcCache.playersRef === playersRef &&
      rankingsTopKtcCache.limit === useLimit &&
      Array.isArray(rankingsTopKtcCache.names) &&
      rankingsTopKtcCache.names.length
    ) {
      return rankingsTopKtcCache.names;
    }
    const names = Object.entries(playersRef)
      .filter(([name, pdata]) => {
        if (parsePickToken(name)) return false;
        const kv = Number(pdata?.ktc);
        return isFinite(kv) && kv > 0;
      })
      .sort((a, b) => Number(b[1].ktc) - Number(a[1].ktc))
      .slice(0, useLimit)
      .map(([name]) => name);
    rankingsTopKtcCache = {
      playersRef,
      limit: useLimit,
      names,
    };
    return names;
  }

  function primeRankingsBaseRowsCache() {
    if (!loadedData?.players) return;
    try {
      const cfg = getSiteConfig().filter(s => s.include);
      const posMap = loadedData.sleeper?.positions || {};
      const canonicalCtx = getCanonicalValueContext();
      getOrBuildRankingsBaseRows(cfg, canonicalCtx, posMap);
    } catch (_) {
      // no-op warmup; buildFullRankings remains source of truth.
    }
  }

  function buildFullRankings() {
    const tbody = document.getElementById('rookieBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    buildRisingFallingSection();

    if (!loadedData || !loadedData.players) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--subtext);padding:24px;">Update values first to see rankings</td></tr>';
      const mobileList = document.getElementById('rankingsMobileList');
      if (mobileList) {
        mobileList.innerHTML = '<div class="mobile-row-card"><div class="mobile-row-name">Update values first to see rankings.</div></div>';
      }
      updateRankingsActiveChips();
      return;
    }

    const cfg = getSiteConfig().filter(s => s.include);
    const hdr = document.getElementById('rookieHeader');
    const dataMode = getRankingsDataMode();
    const dataModeLabel = RANKINGS_DATA_MODE_LABELS[dataMode] || 'Dynasty';
    const titleEl = document.getElementById('rankingsTitle');
    if (titleEl) titleEl.textContent = `${dataModeLabel} Rankings`;
    if (dataMode !== 'dynasty') {
      hdr.innerHTML = '<th style="width:40px">#</th><th>Player</th><th>Pos</th><th>Value</th>';
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--subtext);padding:24px;">${dataModeLabel} mode is isolated from dynasty values. Load a dedicated ${dataModeLabel} dataset to enable these rankings.</td></tr>`;
      const mobileList = document.getElementById('rankingsMobileList');
      if (mobileList) {
        mobileList.innerHTML = `<div class="mobile-row-card"><div class="mobile-row-name">${dataModeLabel} mode needs a dedicated dataset.</div></div>`;
      }
      updateRankingsActiveChips();
      return;
    }

    const sortArrow = rankingsSortAsc ? '\u2191' : '\u2193';
    const sortBasis = getRankingsSortBasis();
    const showAdjCols = showRankingsLAMColumns();
    const showSourceCols = showRankingsSourceColumns();
    const valueColLabel = (
      sortBasis === 'raw' ? 'Value (Raw)' :
      sortBasis === 'scoring' ? 'Value (Scoring)' :
      sortBasis === 'scarcity' ? 'Value (Scarcity)' :
      'Value (Full)'
    );
    hdr.innerHTML = '<th style="width:40px" title="Overall rank">#</th><th title="Player or pick name">Player</th><th title="Position">Pos</th>' +
      `<th style="min-width:85px;cursor:pointer;" title="Click to change sort mode" onclick="toggleRankingsSort()">${valueColLabel} ${sortArrow}</th>` +
      (showAdjCols ? `
        <th style="min-width:78px;" title="Raw market value before scoring and scarcity adjustments">Raw Market</th>
        <th style="min-width:88px;" title="How much your league's scoring format changes this player's value (1.00 = no change)">Scoring Adj</th>
        <th style="min-width:90px;" title="Final value after all league adjustments">Final Value</th>
        <th style="min-width:70px;" title="How much league adjustments changed the value (Final minus Raw)">Change</th>
      ` : '') +
      (showSourceCols ? cfg.map(s => {
        const site = sites.find(x => x.key === s.key);
        const label = site ? site.label : s.key;
        return `<th style="font-size:0.62rem;" title="Value from ${label}">${label}</th>`;
      }).join('') : '') +
      '<th title="Number of sources with data for this player (more sources = higher confidence)">Sources</th>';

    const posMap = loadedData.sleeper?.positions || {};
    const canonicalCtx = getCanonicalValueContext();
    const search = (document.getElementById('rankingsSearch')?.value || '').trim().toLowerCase();
    const rookieOnly = document.getElementById('rankingsRookieToggle')?.checked;
    const myRosterOnly = document.getElementById('rankingsMyRosterToggle')?.checked;

    // Get my team roster — check dropdown first, then localStorage
    let myTeamName = document.getElementById('rosterMyTeam')?.value || '';
    if (!myTeamName) myTeamName = localStorage.getItem('dynasty_my_team') || '';
    const myRosterSet = new Set();
    if (myRosterOnly && myTeamName && sleeperTeams.length) {
      const myTeam = sleeperTeams.find(t => t.name === myTeamName);
      if (myTeam) myTeam.players.forEach(p => myRosterSet.add(p.toLowerCase()));
    }
    // If checkbox is on but no team selected and no roster found, show hint
    if (myRosterOnly && myRosterSet.size === 0) {
      const body = document.getElementById('rookieBody');
      if (body) body.innerHTML = '<tr><td colspan="20" style="text-align:center;padding:30px;color:var(--subtext);">Select your team in the Rosters tab first, then check "My roster only".</td></tr>';
      return;
    }

    // Build once + reuse: heavy per-player canonicalization/adjustment stays cached
    // unless data/settings/source-config changed.
    const baseRows = getOrBuildRankingsBaseRows(cfg, canonicalCtx, posMap);
    let ranked = baseRows.map(r => ({
      ...r,
      sortValue: getValueByRankingMode(r.adjustment, sortBasis),
    }));
    ranked = dedupeRankingsRowsByName(ranked);
    ranked.sort((a, b) => rankingsSortAsc ? a.sortValue - b.sortValue : b.sortValue - a.sortValue);

    // Apply filters before display capping so focused views (like rookies-only)
    // are not truncated by the global top-N list.
    if (currentRankingsFilter !== 'ALL') {
      if (currentRankingsFilter === 'OFF') {
        ranked = ranked.filter(r => OFFENSE_POSITIONS.has(r.pos));
      } else if (currentRankingsFilter === 'IDP') {
        ranked = ranked.filter(r => IDP_POSITIONS.has(r.pos));
      } else if (currentRankingsFilter === 'PICKS') {
        ranked = ranked.filter(r => r.pos === 'PICK');
      } else {
        ranked = ranked.filter(r => r.pos === currentRankingsFilter ||
          (currentRankingsFilter === 'DL' && ['DL','DE','DT','EDGE'].includes(r.pos)) ||
          (currentRankingsFilter === 'DB' && ['DB','CB','S'].includes(r.pos)));
      }
    }
    if (rookieOnly) ranked = ranked.filter(r => r.isRookie);
    if (myRosterOnly && myRosterSet.size > 0) {
      ranked = ranked.filter(r => myRosterSet.has(r.name.toLowerCase()));
    }
    const useExtraMobileFilters = isMobileViewport();
    if (useExtraMobileFilters) {
      if (rankingsExtraFilters.picksOnly) {
        ranked = ranked.filter(r => r.pos === 'PICK');
      }
      if (rankingsExtraFilters.trendingOnly) {
        ranked = ranked.filter(r => Math.abs((window.playerTrends && window.playerTrends[r.name]) || 0) >= 2);
      }
      if (rankingsExtraFilters.ageBucket && rankingsExtraFilters.ageBucket !== 'ALL') {
        ranked = ranked.filter(r => {
          const pdata = loadedData?.players?.[r.name] || {};
          return getPlayerAgeBucket(r.name, pdata) === rankingsExtraFilters.ageBucket;
        });
      }
    }
    if (search) ranked = ranked.filter(r => r.name.toLowerCase().includes(search));

    const shouldApplyDisplayCap = (
      currentRankingsFilter === 'ALL'
      && !rookieOnly
      && !myRosterOnly
      && (!useExtraMobileFilters || !rankingsExtraFilters.picksOnly)
      && (!useExtraMobileFilters || !rankingsExtraFilters.trendingOnly)
      && (!useExtraMobileFilters || !rankingsExtraFilters.ageBucket || rankingsExtraFilters.ageBucket === 'ALL')
      && !search
    );
    if (shouldApplyDisplayCap) {
      const DISPLAY_MIN = 640;
      const DISPLAY_CAP = 750;
      const KTC_BASELINE_COUNT = 400;
      const topKtcNames = getTopKtcBaselineNames(KTC_BASELINE_COUNT);
      const rankedByName = new Map(ranked.map(r => [r.name, r]));
      const displayRows = ranked.slice(0, Math.min(DISPLAY_MIN, ranked.length));
      const displaySet = new Set(displayRows.map(r => r.name));
      topKtcNames.forEach(name => {
        if (displayRows.length >= DISPLAY_CAP) return;
        if (!displaySet.has(name) && rankedByName.has(name)) {
          displayRows.push(rankedByName.get(name));
          displaySet.add(name);
        }
      });
      ranked = displayRows
        .sort((a, b) => rankingsSortAsc ? a.sortValue - b.sortValue : b.sortValue - a.sortValue)
        .slice(0, DISPLAY_CAP);
    }

    // Safety guard: keep only one true canonical ceiling value in the active view.
    ranked = enforceSingleCanonicalTop(ranked, sortBasis);

    // Detect tier breaks using dynamic cliff detection on the active sort column.
    const tierBreaks = computeTierBreakIndexesFromOrderedValues(
      ranked.map(r => Number(r?.sortValue))
    );
    let tierNum = 1;

    let displayRank = 0;
    ranked.forEach((r, idx) => {
      if (tierBreaks.has(idx)) {
        tierNum++;
        const sepTr = document.createElement('tr');
        sepTr.className = 'tier-separator';
        const colSpan = (4 + (showAdjCols ? 4 : 0)) + (showSourceCols ? cfg.length : 0) + 1;
        sepTr.innerHTML = `<td colspan="${colSpan}"><span class="tier-label">\u2500\u2500 Tier ${tierNum} \u2500\u2500</span></td>`;
        tbody.appendChild(sepTr);
      }

      displayRank++;
      const tr = document.createElement('tr');
      const maxDisplayValue = Math.max(1, ranked[0]?.sortValue || 1);
      const barPct = Math.round((r.sortValue / maxDisplayValue) * 100);

      const rookieBadge = r.isRookie ? '<span style="font-size:0.55rem;background:var(--amber);color:#000;padding:1px 4px;border-radius:3px;margin-left:4px;font-weight:700;">R</span>' : '';
      const posStyle = getPosStyle(r.pos);
      const adjustment = r.adjustment || getPrecomputedAdjustmentBundle(r.sourceData, r.rawComposite, r.pos, r.name) || computeFinalAdjustedValue(r.rawComposite, r.pos, r.name);
      const scoring = adjustment.scoring;
      const scarcity = adjustment.scarcity;

      let cells = `
        <td style="text-align:center;font-family:var(--mono);font-size:0.72rem;color:var(--subtext);">${displayRank}</td>
        <td style="font-weight:600;font-size:0.8rem;"><a href="#" onclick="event.preventDefault();openPlayerPopup('${r.name.replace(/'/g,"\\'")}');return false;" style="color:var(--text);text-decoration:none;border-bottom:1px dotted var(--border);" onmouseover="this.style.color='var(--cyan)'" onmouseout="this.style.color='var(--text)'">${r.name}</a>${rookieBadge}</td>
        <td><span class="ac-pos" style="${posStyle}">${r.pos || '?'}</span></td>
        <td style="font-family:var(--mono);font-weight:700;color:var(--cyan);position:relative;">
          <div style="position:absolute;left:0;top:0;bottom:0;width:${barPct}%;background:var(--cyan-soft);border-radius:3px;"></div>
          <span style="position:relative;z-index:1;">${Math.round(r.sortValue).toLocaleString()}</span>
        </td>
      `;
      if (showAdjCols) {
        const diff = adjustment.valueDelta;
        const diffColor = diff > 0 ? 'var(--green)' : diff < 0 ? 'var(--red)' : 'var(--subtext)';
        const diffSign = diff > 0 ? '+' : '';
        cells += `
          <td style="font-family:var(--mono);text-align:right;">${Math.round(r.rawComposite).toLocaleString()}</td>
          <td style="font-family:var(--mono);text-align:center;" title="raw ${Number(scoring.rawLeagueMultiplier || 1).toFixed(3)} · shrunk ${Number(scoring.shrunkLeagueMultiplier || 1).toFixed(3)} · strength ${Number(scoring.adjustmentStrength || 0).toFixed(2)}">${Number(scoring.effectiveMultiplier || 1).toFixed(3)}</td>
          <td style="font-family:var(--mono);font-weight:700;text-align:right;color:var(--green);">${Math.round(r.adjustedComposite).toLocaleString()}</td>
          <td style="font-family:var(--mono);text-align:right;color:${diffColor};">${diffSign}${diff.toLocaleString()}</td>
        `;
      }

      if (showSourceCols) {
        cfg.forEach(sc => {
          const val = Number((r.pData || {})[sc.key]);
          cells += `<td style="font-family:var(--mono);font-size:0.68rem;text-align:center;color:${val != null && Number.isFinite(val) ? 'var(--text)' : 'var(--border)'};">${val != null && Number.isFinite(val) ? Math.round(val).toLocaleString() : '\u2014'}</td>`;
        });
      }

      const sc_ = Number(r.siteCount) || 0;
      const scColor = sc_ >= 5 ? 'var(--green)' : sc_ >= 3 ? 'var(--text)' : sc_ >= 1 ? 'var(--amber)' : 'var(--subtext)';
      const scTip = sc_ >= 5 ? 'Strong coverage' : sc_ >= 3 ? 'Good coverage' : sc_ >= 1 ? 'Limited coverage' : 'No sources';
      cells += `<td style="text-align:center;font-family:var(--mono);font-size:0.72rem;color:${scColor};" title="${scTip}: ${sc_} source${sc_ !== 1 ? 's' : ''}">${sc_}</td>`;

      tr.innerHTML = cells;
      tr.dataset.rawComposite = String(Math.round(r.rawComposite));
      tr.dataset.scoringComposite = String(Math.round(r.scoringComposite));
      tr.dataset.scarcityComposite = String(Math.round(r.scarcityComposite));
      tr.dataset.adjustedComposite = String(Math.round(r.adjustedComposite));
      tr.dataset.sortValue = String(Math.round(r.sortValue));
      tr.dataset.lamBucket = String(scoring.baselineBucket || '');
      tr.dataset.lamDebug = JSON.stringify({
        baselineBucket: scoring.baselineBucket,
        rawCompositeValue: scoring.rawCompositeValue,
        rawLeagueMultiplier: Number(scoring.rawLeagueMultiplier),
        shrunkLeagueMultiplier: Number(scoring.shrunkLeagueMultiplier),
        adjustmentStrength: Number(scoring.adjustmentStrength),
        effectiveMultiplier: Number(scoring.effectiveMultiplier),
        formatFitSource: scoring.formatFitSource || '',
        formatFitConfidence: Number(scoring.formatFitConfidence ?? 0),
        formatFitRaw: Number(scoring.formatFitRaw ?? 0),
        formatFitShrunk: Number(scoring.formatFitShrunk ?? 0),
        formatFitFinal: Number(scoring.formatFitFinal ?? 0),
        formatFitPPGTest: Number(scoring.formatFitPPGTest ?? 0),
        formatFitPPGCustom: Number(scoring.formatFitPPGCustom ?? 0),
        formatFitProductionShare: Number(scoring.formatFitProductionShare ?? 0),
        finalAdjustedValue: Number(adjustment.scoringAdjustedValue),
        valueDelta: Number(adjustment.scoringAdjustedValue - adjustment.rawMarketValue),
      });
      tr.dataset.scarcityDebug = JSON.stringify({
        scarcityBucket: scarcity.scarcityBucket,
        scarcityMultiplierRaw: Number(scarcity.scarcityMultiplierRaw),
        scarcityMultiplierEffective: Number(scarcity.scarcityMultiplierEffective),
        scarcityStrength: Number(scarcity.scarcityStrength),
        replacementRank: Number(scarcity.replacementRank),
        replacementValue: Number(scarcity.replacementValue),
        valueAboveReplacement: Number(scarcity.valueAboveReplacement),
        finalScarcityAdjustedValue: Number(adjustment.scarcityAdjustedValue),
        scarcityDelta: Number(adjustment.scarcityAdjustedValue - adjustment.rawMarketValue),
      });
      tr.dataset.adjustmentDebug = JSON.stringify({
        rawMarketValue: Number(adjustment.rawMarketValue),
        marketReliabilityScore: Number(adjustment.marketReliability?.score ?? 0),
        marketReliabilityLabel: String(adjustment.marketReliability?.label || ''),
        scoringMultiplierEffective: Number(scoring.effectiveMultiplier),
        scoringAdjustedValue: Number(adjustment.scoringAdjustedValue),
        scarcityAdjustedValue: Number(adjustment.scarcityAdjustedValue),
        guardrailMin: Number(adjustment.topEndGuardrail?.minValue ?? 0),
        guardrailMax: Number(adjustment.topEndGuardrail?.maxValue ?? 0),
        guardrailApplied: !!adjustment.topEndGuardrail?.applied,
        finalAdjustedValue: Number(adjustment.finalAdjustedValue),
        valueDelta: Number(adjustment.valueDelta),
      });
      tbody.appendChild(tr);
    });

    const total = ranked.length;
    const offCount = ranked.filter(r => OFFENSE_POSITIONS.has(r.pos)).length;
    const idpCount = ranked.filter(r => IDP_POSITIONS.has(r.pos)).length;
    const rookieCount = ranked.filter(r => r.isRookie).length;
    const title = document.getElementById('rankingsTitle');
    if (title) title.textContent = `${dataModeLabel} Rankings \u2014 ${total} players (${offCount} OFF, ${idpCount} IDP, ${rookieCount} rookies) · sort=${sortBasis}`;
    renderRankingsMobileCards(ranked);
    updateRankingsActiveChips();
  }

  // Keep old name as alias
  function buildRookieRankings() { buildFullRankings(); }

  function getPlayerAgeBucket(name, pdata) {
    const yrs = Number(pdata?._yearsExp);
    if (!isFinite(yrs)) return 'UNK';
    if (yrs <= 0) return 'ROOKIE';
    if (yrs <= 2) return 'YOUNG';
    if (yrs <= 5) return 'PRIME';
    return 'VET';
  }

  function getFreshnessPillForAsset(name, pdata) {
    if (!loadedData?.date) return { cls: 'low', text: 'unknown' };
    const scrapeDate = new Date(loadedData.scrapeTimestamp || loadedData.date);
    const ageHours = Math.max(0, (Date.now() - scrapeDate.getTime()) / 3600000);
    if (ageHours > 72) return { cls: 'stale', text: 'stale' };
    const conf = Number(pdata?._formatFitConfidence ?? pdata?._sites ?? 0);
    if (isFinite(conf) && conf < 0.45) return { cls: 'low', text: 'low conf' };
    return { cls: 'fresh', text: 'fresh' };
  }

  function updateRankingsActiveChips() {
    const el = document.getElementById('rankingsActiveChips');
    if (!el) return;
    const chips = [];
    if (currentRankingsFilter && currentRankingsFilter !== 'ALL') chips.push(currentRankingsFilter);
    if (document.getElementById('rankingsRookieToggle')?.checked) chips.push('Rookies');
    if (document.getElementById('rankingsMyRosterToggle')?.checked) chips.push('My Roster');
    if (rankingsExtraFilters.picksOnly) chips.push('Picks');
    if (rankingsExtraFilters.trendingOnly) chips.push('Trending');
    if (rankingsExtraFilters.ageBucket && rankingsExtraFilters.ageBucket !== 'ALL') chips.push(rankingsExtraFilters.ageBucket);
    chips.push(rankingsSortAsc ? 'Asc' : 'Desc');
    const sortBasis = getRankingsSortBasis();
    chips.push(
      sortBasis === 'raw' ? 'Raw' :
      sortBasis === 'scoring' ? 'Scoring' :
      sortBasis === 'scarcity' ? 'Scarcity' :
      'Full'
    );
    if (showRankingsSourceColumns()) chips.push('Sources');
    chips.push(`Quick+${getRankingsQuickTradeSide()}`);
    el.innerHTML = chips.map(c => `<span class="mobile-pill">${c}</span>`).join('');
  }

  function getRankingsQuickTradeSide() {
    const side = String(rankingsQuickTradeSide || '').toUpperCase();
    return side === 'A' ? 'A' : 'B';
  }

  function updateRankingsQuickTradeSideButtons() {
    const side = getRankingsQuickTradeSide();
    const aBtn = document.getElementById('rankingsQuickSideA');
    const bBtn = document.getElementById('rankingsQuickSideB');
    if (aBtn) {
      aBtn.classList.toggle('primary', side === 'A');
      aBtn.textContent = side === 'A' ? 'Quick +A ✓' : 'Quick +A';
    }
    if (bBtn) {
      bBtn.classList.toggle('primary', side === 'B');
      bBtn.textContent = side === 'B' ? 'Quick +B ✓' : 'Quick +B';
    }
  }

  function setRankingsQuickTradeSide(side, opts = {}) {
    rankingsQuickTradeSide = (String(side || '').toUpperCase() === 'A') ? 'A' : 'B';
    if (opts.persist !== false) {
      try { localStorage.setItem(MOBILE_RANKINGS_QUICK_SIDE_KEY, rankingsQuickTradeSide); } catch (_) {}
    }
    updateRankingsQuickTradeSideButtons();
    updateRankingsActiveChips();
    if (opts.refresh !== false) {
      renderRankingsMobileCards(rankingsMobileRowsCache, { preserveCount: true });
    }
  }

  function getRankingsMobileRenderSignature(rankedRows) {
    const rows = Array.isArray(rankedRows) ? rankedRows : [];
    const first = rows[0]?.name || '';
    const last = rows[rows.length - 1]?.name || '';
    const search = String(document.getElementById('rankingsSearch')?.value || '').trim().toLowerCase();
    const sortBasis = getRankingsSortBasis();
    const dataMode = getRankingsDataMode();
    const rookieOnly = !!document.getElementById('rankingsRookieToggle')?.checked;
    const myRosterOnly = !!document.getElementById('rankingsMyRosterToggle')?.checked;
    return [
      rows.length,
      first,
      last,
      currentRankingsFilter,
      sortBasis,
      rankingsSortAsc ? 'asc' : 'desc',
      dataMode,
      rookieOnly ? 'rookie' : '',
      myRosterOnly ? 'my' : '',
      rankingsExtraFilters.picksOnly ? 'picks' : '',
      rankingsExtraFilters.trendingOnly ? 'trend' : '',
      rankingsExtraFilters.ageBucket || 'ALL',
      search,
    ].join('|');
  }

  function loadMoreRankingsMobileCards() {
    rankingsMobileVisibleCount = Math.min(
      (Array.isArray(rankingsMobileRowsCache) ? rankingsMobileRowsCache.length : rankingsMobileVisibleCount),
      rankingsMobileVisibleCount + RANKINGS_MOBILE_LOAD_STEP
    );
    renderRankingsMobileCards(rankingsMobileRowsCache, { preserveCount: true });
  }

  function renderRankingsMobileCards(rankedRows, opts = {}) {
    const wrap = document.getElementById('rankingsMobileList');
    if (!wrap) return;
    const showSourceCols = showRankingsSourceColumns();
    const sourceCfg = showSourceCols ? getSiteConfig().filter(s => s.include) : [];
    const sourceLabelMap = new Map((sites || []).map(s => [s.key, s.label || s.key]));
    const rows = Array.isArray(rankedRows) ? rankedRows : [];
    rankingsMobileRowsCache = rows;
    const sig = getRankingsMobileRenderSignature(rows);
    if (!opts.preserveCount && sig !== rankingsMobileRenderSignature) {
      rankingsMobileVisibleCount = RANKINGS_MOBILE_INITIAL_ROWS;
    }
    rankingsMobileRenderSignature = sig;
    if (!rankedRows || !rankedRows.length) {
      wrap.innerHTML = '<div class="mobile-row-card"><div class="mobile-row-name">No matching assets.</div></div>';
      return;
    }
    const totalRows = rows.length;
    const visibleRows = Math.max(1, Math.min(totalRows, rankingsMobileVisibleCount));
    const top = rows.slice(0, visibleRows);
    const quickSide = getRankingsQuickTradeSide();
    const cards = top.map((r, idx) => {
      const name = r.name;
      const pos = r.pos || '?';
      const val = Math.round(r.sortValue || 0);
      const trend = (window.playerTrends && window.playerTrends[name]) || 0;
      const trendText = trend ? `${trend > 0 ? '+' : ''}${trend.toFixed(1)}%` : '—';
      const pill = getFreshnessPillForAsset(name, r.sourceData || (loadedData?.players?.[name] || {}));
      const escaped = String(name).replace(/'/g, "\\'");
      const rankLabel = `#${idx + 1}`;
      let sourceBlock = '';
      if (showSourceCols) {
        const sourceCells = sourceCfg.map(sc => {
          const raw = Number((r.pData || {})[sc.key]);
          const hasVal = Number.isFinite(raw) && raw > 0;
          const label = sourceLabelMap.get(sc.key) || sc.key;
          const value = hasVal ? Math.round(raw).toLocaleString() : '—';
          return `
            <div class="mobile-rank-source-cell">
              <span class="mobile-rank-source-label">${label}</span>
              <span class="mobile-rank-source-value ${hasVal ? '' : 'empty'}">${value}</span>
            </div>
          `;
        }).join('');
        sourceBlock = `
          <div class="mobile-rank-sources">
            <div class="mobile-rank-source-grid">${sourceCells}</div>
          </div>
        `;
      }
      return `
        <div class="mobile-row-card">
          <div class="mobile-row-head">
            <div>
              <div class="mobile-row-name">${name}</div>
              <div class="mobile-row-sub">${rankLabel} · ${pos} · trend ${trendText}</div>
            </div>
            <div class="mobile-row-value">${val > 0 ? val.toLocaleString() : '—'}</div>
          </div>
          <div class="mobile-row-actions">
            <span class="mobile-pill ${pill.cls}">${pill.text}</span>
            <button class="mobile-chip-btn primary" onclick="addAssetToTrade('${quickSide}','${escaped}')">+${quickSide}</button>
            <button class="mobile-chip-btn" onclick="openPlayerPopup('${escaped}')">Open</button>
          </div>
          ${sourceBlock}
        </div>
      `;
    }).join('');
    const remaining = Math.max(0, totalRows - visibleRows);
    const footer = `
      <div class="mobile-row-card">
        <div class="mobile-row-head">
          <div>
            <div class="mobile-row-name">Showing ${visibleRows.toLocaleString()} of ${totalRows.toLocaleString()}</div>
            <div class="mobile-row-sub">Mobile keeps first render fast, then lets you expand to full rankings.</div>
          </div>
          <div class="mobile-row-value">${Math.round((visibleRows / Math.max(1, totalRows)) * 100)}%</div>
        </div>
        <div class="mobile-row-actions">
          ${remaining > 0 ? `<button class="mobile-chip-btn primary" onclick="loadMoreRankingsMobileCards()">Load ${Math.min(remaining, RANKINGS_MOBILE_LOAD_STEP).toLocaleString()} More</button>` : '<span class="mobile-pill fresh">All Loaded</span>'}
          <button class="mobile-chip-btn" onclick="buildFullRankings()">Refresh</button>
          <button class="mobile-chip-btn" onclick="openFullMobileWorkspace('rookies')">Full Table</button>
        </div>
      </div>
    `;
    wrap.innerHTML = cards + footer;
  }

  function getMobilePrefs() {
    return readJsonStore(MOBILE_PREFS_KEY, {
      sortBasis: 'full',
      sortAsc: false,
      filterPos: 'ALL',
      picksOnly: false,
      trendingOnly: false,
      ageBucket: 'ALL',
    });
  }

  function saveMobilePrefs(next) {
    writeJsonStore(MOBILE_PREFS_KEY, next || getMobilePrefs());
  }

  function openRankingsFilterSheet() {
    const ov = document.getElementById('rankingsFilterSheetOverlay');
    const grid = document.getElementById('rankingsFilterSheetGrid');
    if (!ov || !grid) return;
    const prefs = getMobilePrefs();
    grid.innerHTML = `
      <label class="sheet-item">Position
        <select id="sheetFilterPos" style="background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:4px 6px;font-size:0.72rem;">
          ${buildRankingsPositionOptionsHtml()}
        </select>
      </label>
      <label class="sheet-item">Rookies only <input id="sheetRookiesOnly" type="checkbox"></label>
      <label class="sheet-item">My roster only <input id="sheetMyRosterOnly" type="checkbox"></label>
      <label class="sheet-item">Trending only <input id="sheetTrendingOnly" type="checkbox"></label>
      <label class="sheet-item">Picks only <input id="sheetPicksOnly" type="checkbox"></label>
      <label class="sheet-item">Detail columns <input id="sheetShowDetailCols" type="checkbox"></label>
      <label class="sheet-item">Source columns <input id="sheetShowSourceCols" type="checkbox"></label>
      <label class="sheet-item">Age bucket
        <select id="sheetAgeBucket" style="background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:4px 6px;font-size:0.72rem;">
          <option value="ALL">All</option>
          <option value="ROOKIE">Rookies</option>
          <option value="YOUNG">Young</option>
          <option value="PRIME">Prime</option>
          <option value="VET">Veteran</option>
        </select>
      </label>
    `;
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
    setVal('sheetFilterPos', normalizeRankingsFilterPos(prefs.filterPos || currentRankingsFilter || 'ALL'));
    setVal('sheetAgeBucket', prefs.ageBucket || rankingsExtraFilters.ageBucket || 'ALL');
    const rook = document.getElementById('sheetRookiesOnly'); if (rook) rook.checked = !!document.getElementById('rankingsRookieToggle')?.checked;
    const myr = document.getElementById('sheetMyRosterOnly'); if (myr) myr.checked = !!document.getElementById('rankingsMyRosterToggle')?.checked;
    const tr = document.getElementById('sheetTrendingOnly'); if (tr) tr.checked = !!prefs.trendingOnly;
    const po = document.getElementById('sheetPicksOnly'); if (po) po.checked = !!prefs.picksOnly;
    const dc = document.getElementById('sheetShowDetailCols'); if (dc) dc.checked = showRankingsLAMColumns();
    const sc = document.getElementById('sheetShowSourceCols'); if (sc) sc.checked = showRankingsSourceColumns();
    ov.classList.add('active');
  }

  function closeRankingsFilterSheet() {
    document.getElementById('rankingsFilterSheetOverlay')?.classList.remove('active');
  }

  function applyRankingsFilterSheet() {
    const pos = normalizeRankingsFilterPos(document.getElementById('sheetFilterPos')?.value || 'ALL');
    currentRankingsFilter = pos;
    document.querySelectorAll('.pos-filter-btn').forEach(b => b.classList.toggle('active', b.dataset.pos === pos));
    const rook = document.getElementById('rankingsRookieToggle');
    if (rook) rook.checked = !!document.getElementById('sheetRookiesOnly')?.checked;
    const myr = document.getElementById('rankingsMyRosterToggle');
    if (myr) myr.checked = !!document.getElementById('sheetMyRosterOnly')?.checked;
    rankingsExtraFilters = {
      picksOnly: !!document.getElementById('sheetPicksOnly')?.checked,
      trendingOnly: !!document.getElementById('sheetTrendingOnly')?.checked,
      ageBucket: document.getElementById('sheetAgeBucket')?.value || 'ALL',
    };
    const showDetail = !!document.getElementById('sheetShowDetailCols')?.checked;
    const showSources = !!document.getElementById('sheetShowSourceCols')?.checked;
    setRankingsDetailColumnsVisible(showDetail, { persist: false, rebuild: false });
    setRankingsSourceColumnsVisible(showSources, { persist: false, rebuild: false, refreshMore: false });
    saveMobilePrefs({
      ...getMobilePrefs(),
      filterPos: currentRankingsFilter,
      ...rankingsExtraFilters,
    });
    persistSettings();
    closeRankingsFilterSheet();
    buildFullRankings();
  }

  function openRankingsSortSheet() {
    const ov = document.getElementById('rankingsSortSheetOverlay');
    const grid = document.getElementById('rankingsSortSheetGrid');
    if (!ov || !grid) return;
    const basis = getRankingsSortBasis();
    grid.innerHTML = `
      <button class="sheet-item" onclick="setRankingsSortBasisFromSheet('full')">Fully Adjusted ${basis==='full'?'✓':''}</button>
      <button class="sheet-item" onclick="setRankingsSortBasisFromSheet('scoring')">Scoring Adjusted ${basis==='scoring'?'✓':''}</button>
      <button class="sheet-item" onclick="setRankingsSortBasisFromSheet('scarcity')">Scarcity Adjusted ${basis==='scarcity'?'✓':''}</button>
      <button class="sheet-item" onclick="setRankingsSortBasisFromSheet('raw')">Raw Market ${basis==='raw'?'✓':''}</button>
      <button class="sheet-item" onclick="setRankingsDirectionFromSheet(false)">Descending ${!rankingsSortAsc?'✓':''}</button>
      <button class="sheet-item" onclick="setRankingsDirectionFromSheet(true)">Ascending ${rankingsSortAsc?'✓':''}</button>
    `;
    ov.classList.add('active');
  }

  function closeRankingsSortSheet() {
    document.getElementById('rankingsSortSheetOverlay')?.classList.remove('active');
  }

  function setRankingsSortBasisFromSheet(mode) {
    handleValueBasisChange(mode, 'rankings');
    const prefs = getMobilePrefs();
    prefs.sortBasis = mode;
    saveMobilePrefs(prefs);
    closeRankingsSortSheet();
  }

  function setRankingsDirectionFromSheet(asc) {
    rankingsSortAsc = !!asc;
    const prefs = getMobilePrefs();
    prefs.sortAsc = rankingsSortAsc;
    saveMobilePrefs(prefs);
    closeRankingsSortSheet();
    buildFullRankings();
  }

  function renderAssetRowCard(name, opts = {}) {
    const canonical = getCanonicalPlayerName(name) || name;
    const result = computeMetaValueForPlayer(canonical);
    const val = result?.metaValue && isFinite(result.metaValue) ? Math.round(result.metaValue) : 0;
    const pos = parsePickToken(canonical) ? 'PICK' : (getPlayerPosition(canonical) || '?');
    const trend = (window.playerTrends && window.playerTrends[canonical]) || 0;
    const t = trend ? `${trend > 0 ? '+' : ''}${trend.toFixed(1)}%` : '—';
    const escaped = String(canonical).replace(/'/g, "\\'");
    return `
      <div class="mobile-row-card">
        <div class="mobile-row-head">
          <div>
            <div class="mobile-row-name">${canonical}</div>
            <div class="mobile-row-sub">${pos} · trend ${t}</div>
          </div>
          <div class="mobile-row-value">${val > 0 ? val.toLocaleString() : '—'}</div>
        </div>
        <div class="mobile-row-actions">
          <button class="mobile-chip-btn primary" onclick="addAssetToTrade('B','${escaped}')">+Trade</button>
          <button class="mobile-chip-btn" onclick="openPlayerPopup('${escaped}')">Open</button>
        </div>
      </div>
    `;
  }

  function buildHomeHub() {
    // ── KPI values ──
    const savedTrades = getSavedTrades();
    const recPlayers = getRecentPlayers().slice(0, 5);
    const draft = readJsonStore(TRADE_DRAFT_KEY, null);
    const countPlayers = Object.keys(loadedData?.players || {}).length;
    const scrapeDate = loadedData ? new Date(loadedData.scrapeTimestamp || loadedData.date || Date.now()) : null;
    const ageHours = scrapeDate ? Math.max(0, (Date.now() - scrapeDate.getTime()) / 3600000) : null;
    const profile = getProfile();

    // ── Hero card ──
    const heroLeague = document.getElementById('homeHeroLeague');
    const heroEyebrow = document.getElementById('homeHeroEyebrow');
    const heroMeta = document.getElementById('heroStatusLabel');
    const heroStatusDot = document.getElementById('heroStatusDot');
    const heroBtn = document.getElementById('heroLeagueBtn');

    if (heroLeague) {
      if (profile?.leagueName) {
        heroLeague.textContent = profile.leagueName;
        if (heroEyebrow) heroEyebrow.textContent = profile.teamName || 'Dynasty League';
        if (heroBtn) { heroBtn.textContent = 'Choose Team'; heroBtn.onclick = () => showOnboarding(); }
      } else {
        heroLeague.textContent = loadedData?.sleeper?.leagueName || HARDCODED_LEAGUE_NAME_FALLBACK;
        if (heroEyebrow) heroEyebrow.textContent = 'Hardcoded Sleeper League';
        if (heroBtn) { heroBtn.textContent = 'Choose Team'; heroBtn.onclick = () => showOnboarding(); }
      }
    }

    if (heroStatusDot && heroMeta) {
      if (!loadedData) {
        heroStatusDot.className = 'home-status-dot none';
        heroMeta.textContent = 'No data — tap Refresh ↑';
      } else if (ageHours != null && ageHours > 48) {
        heroStatusDot.className = 'home-status-dot stale';
        heroMeta.textContent = `Data stale · ${Math.round(ageHours)}h ago`;
      } else if (ageHours != null) {
        heroStatusDot.className = 'home-status-dot fresh';
        heroMeta.textContent = `Live · Updated ${Math.round(ageHours)}h ago`;
      } else {
        heroStatusDot.className = 'home-status-dot none';
        heroMeta.textContent = 'Status unknown';
      }
    }

    // KPIs
    const kpiEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    kpiEl('heroKpiAssets', countPlayers > 0 ? countPlayers.toLocaleString() : '—');
    kpiEl('heroKpiTeam', profile?.teamName ? profile.teamName : '—');
    kpiEl('heroKpiTrades', savedTrades.length > 0 ? savedTrades.length : '—');
    kpiEl('heroKpiFresh', ageHours != null ? (ageHours < 1 ? '<1h' : `${Math.round(ageHours)}h`) : '—');

    // Primary CTA — show "Resume" if draft in progress
    const ctaTrade = document.getElementById('homeCTATrade');
    const ctaLabel = document.getElementById('homeCTATradeLabel');
    const ctaSub = document.getElementById('homeCTATradeSub');
    if (draft && ((draft.sideA || []).length || (draft.sideB || []).length)) {
      if (ctaLabel) ctaLabel.textContent = 'Resume Trade';
      if (ctaSub) ctaSub.textContent = 'Draft in progress';
      if (ctaTrade) ctaTrade.onclick = () => { loadTradeDraftState && loadTradeDraftState(); switchTab('calculator'); };
    } else {
      if (ctaLabel) ctaLabel.textContent = 'Trade Builder';
      if (ctaSub) ctaSub.textContent = 'Open workspace';
      if (ctaTrade) ctaTrade.onclick = () => switchTab('calculator');
    }

    // ── Status / alerts section ──
    const alertsEl = document.getElementById('homeAlertsList');
    if (alertsEl) {
      const rows = [];

      if (!loadedData) {
        rows.push({ type: 'warn', title: 'No player data', sub: 'Tap Refresh to load current values.' });
      } else if (ageHours != null && ageHours > 48) {
        rows.push({ type: 'warn', title: `Data is ${Math.round(ageHours)}h old`, sub: 'Refresh values to improve trade confidence.' });
      } else if (ageHours != null) {
        rows.push({ type: 'ok', title: `Values current`, sub: `${countPlayers.toLocaleString()} assets loaded · ${Math.round(ageHours)}h ago` });
      }

      if (!profile) {
        rows.push({ type: 'info', title: 'League auto-loaded', sub: 'Use Choose Team to set your roster context.' });
      } else {
        rows.push({ type: 'ok', title: profile.leagueName || 'League connected', sub: `${profile.teamName || ''} · Sleeper` });
      }

      alertsEl.innerHTML = rows.map(r => `
        <div class="home-alert-row">
          <div class="home-alert-dot ${r.type}"></div>
          <div>
            <div class="home-alert-text">${r.title}</div>
            <div class="home-alert-sub">${r.sub}</div>
          </div>
        </div>
      `).join('');
    }

    // ── Recent players ──
    const recentCard = document.getElementById('homeRecentCard');
    const recentEl = document.getElementById('homeRecentList');
    if (recentEl && recPlayers.length > 0) {
      recentEl.innerHTML = recPlayers.map(n => renderAssetRowCard(n)).join('');
      if (recentCard) recentCard.style.display = '';
    } else if (recentCard) {
      recentCard.style.display = 'none';
    }
  }

  function renderEdgeCardsInto(containerId, rows, opts = {}) {
    const box = document.getElementById(containerId);
    if (!box) return;
    const emptyText = opts.emptyText || 'No assets match this view.';
    const eligibleRows = Array.isArray(rows) ? rows.filter(isBuysSellsEligibleAsset) : [];
    if (!eligibleRows.length) {
      box.innerHTML = `<div class="mobile-row-card"><div class="mobile-row-name">${emptyText}</div></div>`;
      return;
    }
    const maxRows = Math.max(1, Number(opts.limit) || 20);
    const list = eligibleRows.slice(0, maxRows);
    box.innerHTML = list.map(r => {
      const edge = Number(r.valueEdge || 0);
      const pct = Number(r.edgePct || 0);
      const sign = edge > 0 ? '+' : '';
      const pctSign = pct > 0 ? '+' : '';
      const sigClass = r.signal === 'BUY' ? 'buy' : (r.signal === 'SELL' ? 'sell' : '');
      const escaped = String(r.name || '').replace(/'/g, "\\'");
      return `
        <div class="mobile-row-card edge-mobile-card">
          <div class="mobile-row-head">
            <div>
              <div class="mobile-row-name">${r.name}</div>
              <div class="mobile-row-sub">${r.pos || '?'} · Mkt ${Number(r.actualExternal || 0).toLocaleString()} · Proj ${Number(r.projectedExternal || 0).toLocaleString()}</div>
            </div>
            <div class="value-edge ${sigClass}">${sign}${Math.round(edge).toLocaleString()} (${pctSign}${pct.toFixed(1)}%)</div>
          </div>
          <div class="mobile-row-actions">
            <span class="mobile-pill ${r.isHighConfidence ? 'fresh' : 'low'}">${r.signal || 'HOLD'} · ${r.confidenceLabel || 'LOW'}</span>
            <button class="mobile-chip-btn primary" onclick="addAssetToTrade('B','${escaped}')">+Trade</button>
            <button class="mobile-chip-btn" onclick="openPlayerPopup('${escaped}')">Open</button>
          </div>
        </div>
      `;
    }).join('');
  }

  function buildRosterPlayerMetaMap() {
    const playerMeta = {};
    if (!loadedData?.players) return playerMeta;
    for (const pName of Object.keys(loadedData.players)) {
      const result = computeMetaValueForPlayer(pName);
      if (!result || !isFinite(result.metaValue) || result.metaValue <= 0) continue;
      const pos = getPlayerPosition(pName) || '';
      if (isKickerPosition(pos)) continue;
      playerMeta[pName.toLowerCase()] = {
        name: pName,
        meta: Number(result.metaValue),
        pos,
        group: posGroup(pos),
      };
    }
    return playerMeta;
  }

  function buildTeamValueSnapshot(opts = {}) {
    if (!loadedData?.players) return [];
    if (!Array.isArray(sleeperTeams) || !sleeperTeams.length) return [];

    const allGroups = ['QB','RB','WR','TE','DL','LB','DB','PICKS'];
    const valueMode = getRosterValueMode();
    const groupState = (opts.groupState && typeof opts.groupState === 'object')
      ? { ...opts.groupState }
      : getRosterGroupFilterState();
    if (opts.includePicks != null) groupState.PICKS = !!opts.includePicks;
    let activeGroups = allGroups.filter(g => !!groupState[g]);
    if (!activeGroups.length) {
      activeGroups = ['QB','RB','WR','TE'];
      if (groupState.PICKS !== false) activeGroups.push('PICKS');
    }
    const playerMeta = buildRosterPlayerMetaMap();

    const out = sleeperTeams.map(team => {
      const breakdown = buildTeamValueBreakdown(team, playerMeta, allGroups, valueMode);
      const offenseVals = (Array.isArray(breakdown.playerDetails) ? breakdown.playerDetails : [])
        .filter(p => ['QB', 'RB', 'WR', 'TE'].includes(p.group))
        .map(p => Number(p.meta || 0))
        .filter(v => Number.isFinite(v) && v > 0)
        .sort((a, b) => b - a);
      const starterTotal = offenseVals.slice(0, 10).reduce((s, v) => s + v, 0);
      const byGroup = breakdown.byGroup || {};
      let activeTotal = 0;
      activeGroups.forEach(g => { activeTotal += Number(byGroup[g] || 0); });
      const offTotal = ['QB', 'RB', 'WR', 'TE'].reduce((s, g) => s + Number(byGroup[g] || 0), 0);
      const idpTotal = ['DL', 'LB', 'DB'].reduce((s, g) => s + Number(byGroup[g] || 0), 0);
      const pickTotal = Number(byGroup.PICKS || 0);
      return {
        name: team?.name || 'Team',
        total: Number(breakdown.total || 0),
        activeTotal,
        starterTotal,
        offTotal,
        idpTotal,
        pickTotal,
        byGroup,
      };
    });

    return out.sort((a, b) =>
      Number(b.activeTotal || 0) - Number(a.activeTotal || 0)
      || Number(b.total || 0) - Number(a.total || 0)
      || String(a.name || '').localeCompare(String(b.name || ''))
    );
  }

  function selectMyTeamFromMore(teamName) {
    if (!teamName) return;
    syncGlobalTeam(teamName);
    buildRosterDashboard();
    buildEdgeTable();
    buildHomeHub();
    buildMoreHub();
  }

  function openTeamBreakdownFromMore(teamName) {
    const team = String(teamName || '').trim();
    if (!team) return;
    setMobileLeagueSubPreference('breakdown');
    const breakdownTeam = document.getElementById('breakdownTeamSelect');
    if (breakdownTeam) breakdownTeam.value = team;
    if (isMobileViewport()) {
      setMobileMoreSection('league', { persist: true, refresh: false });
      if (getMobilePowerModeEnabled()) {
        switchTab('league', { allowLegacyMobile: true });
      } else {
        switchTab('more');
      }
      setTimeout(() => {
        try {
          switchLeagueSub('breakdown');
          const moreBreakdownTeam = document.getElementById('moreLeagueBreakdownTeam');
          if (moreBreakdownTeam) moreBreakdownTeam.value = team;
          applyMobileMoreLeagueControls(false);
        } catch (_) {}
      }, 0);
      return;
    }
    switchTab('league');
    setTimeout(() => {
      try {
        switchLeagueSub('breakdown');
        buildTeamBreakdown();
      } catch (_) {}
    }, 0);
  }

  function openTeamComparisonFromMore(teamName) {
    const targetTeam = String(teamName || '').trim();
    if (!targetTeam) return;
    const myTeam = String(document.getElementById('rosterMyTeam')?.value || localStorage.getItem('dynasty_my_team') || '').trim();
    const fallback = (sleeperTeams || []).find(t => String(t?.name || '').trim() && String(t?.name || '').trim() !== targetTeam)?.name || targetTeam;
    const compareA = myTeam || fallback;
    const compareB = (compareA === targetTeam) ? fallback : targetTeam;

    setMobileLeagueSubPreference('compare');
    const aEl = document.getElementById('compareTeamA');
    const bEl = document.getElementById('compareTeamB');
    if (aEl) aEl.value = compareA;
    if (bEl) bEl.value = compareB;

    if (isMobileViewport()) {
      setMobileMoreSection('league', { persist: true, refresh: false });
      if (getMobilePowerModeEnabled()) {
        switchTab('league', { allowLegacyMobile: true });
      } else {
        switchTab('more');
      }
      setTimeout(() => {
        try {
          switchLeagueSub('compare');
          const moreView = document.getElementById('moreLeagueViewSelect');
          const moreA = document.getElementById('moreLeagueCompareA');
          const moreB = document.getElementById('moreLeagueCompareB');
          if (moreView) moreView.value = 'compare';
          if (moreA) moreA.value = compareA;
          if (moreB) moreB.value = compareB;
          applyMobileMoreLeagueControls(false);
        } catch (_) {}
      }, 0);
      return;
    }

    switchTab('league');
    setTimeout(() => {
      try {
        switchLeagueSub('compare');
        buildTeamComparison();
      } catch (_) {}
    }, 0);
  }

  function renderMobileMoreSection() {
    const body = document.getElementById('moreSectionBody');
    const title = document.getElementById('moreSectionTitle');
    if (!body || !title) return;

    const section = normalizeMobileMoreSection(mobileMoreSection);
    const setTitle = (txt) => { title.textContent = txt; };

    if (section === 'edge') {
      setTitle('Market Edge');
      computeSiteStats();
      const projection = ensureEdgeProjectionLayer();
      if (!projection) {
        body.innerHTML = '<div class="mobile-row-card"><div class="mobile-row-name">Load values to compute edge targets.</div></div>';
        return;
      }
      const myTeamName = document.getElementById('rosterMyTeam')?.value || localStorage.getItem('dynasty_my_team') || '';
      const myTeam = sleeperTeams.find(t => t.name === myTeamName);
      const myAssets = new Set();
      if (myTeam) {
        (myTeam.players || []).forEach(p => myAssets.add(String(p).toLowerCase()));
        (myTeam.picks || []).forEach(p => myAssets.add(String(p).toLowerCase()));
      }
      const rows = projection.rows.filter(r =>
        r.comparable
        && isBuysSellsEligibleAsset(r)
        && (r.signal === 'BUY' || r.signal === 'SELL')
      );
      const topBuys = rows
        .filter(r => r.signal === 'BUY' && (!myAssets.size || !myAssets.has(r.name.toLowerCase())))
        .sort((a, b) => Number(b.valueEdge || 0) - Number(a.valueEdge || 0))
        .slice(0, 12);
      const topSells = rows
        .filter(r => r.signal === 'SELL' && (!myAssets.size || myAssets.has(r.name.toLowerCase())))
        .sort((a, b) => Number(a.valueEdge || 0) - Number(b.valueEdge || 0))
        .slice(0, 12);

      body.innerHTML = `
        <div class="mobile-row-card">
          <div class="mobile-row-name">Advanced Edge Workspace</div>
          <div class="mobile-row-sub">Open the full edge table, filters, and league map on mobile.</div>
          <div class="mobile-row-actions">
            <button class="mobile-chip-btn primary" onclick="openFullMobileWorkspace('edge')">Open Full Edge</button>
          </div>
        </div>
        <div class="mobile-inline-grid">
          <div class="mobile-inline-stat"><div class="label">Team Context</div><div class="value">${myTeamName || 'Not Set'}</div></div>
          <div class="mobile-inline-stat"><div class="label">Coverage</div><div class="value">${rows.length.toLocaleString()} assets</div></div>
        </div>
        <div class="mobile-row-card">
          <div class="mobile-row-name">Top Buys</div>
          <div class="mobile-row-sub">Model > market. Good targets to acquire.</div>
          <div id="moreEdgeBuys" class="mobile-list" style="margin-top:8px;"></div>
        </div>
        <div class="mobile-row-card">
          <div class="mobile-row-name">Top Sells</div>
          <div class="mobile-row-sub">Market > model. Consider moving if return is strong.</div>
          <div id="moreEdgeSells" class="mobile-list" style="margin-top:8px;"></div>
        </div>
      `;
      renderEdgeCardsInto('moreEdgeBuys', topBuys, { limit: 8, emptyText: 'No buy signals met thresholds.' });
      renderEdgeCardsInto('moreEdgeSells', topSells, { limit: 8, emptyText: 'No sell signals met thresholds.' });
      return;
    }

    if (section === 'rosters') {
      setTitle('Team Value Board');
      try { buildRosterDashboard(); } catch (_) {}
      const esc = (v) => String(v ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
      const myTeam = document.getElementById('rosterMyTeam')?.value || localStorage.getItem('dynasty_my_team') || '';
      const rosterValueMode = getRosterValueMode();
      const valueBasis = getCalculatorValueBasis();
      const groupState = getMobileMoreRosterGroupState();
      const rosterSubview = normalizeMobileMoreRosterSubview(mobileMoreRosterView);
      let activeGroupList = ROSTER_GROUP_KEYS.filter((g) => !!groupState[g]);
      if (!activeGroupList.length) activeGroupList = ['QB', 'RB', 'WR', 'TE', 'PICKS'];
      const includePicks = !!groupState.PICKS;
      const snapshot = buildTeamValueSnapshot({ groupState, includePicks });
      if (!snapshot.length) {
        body.innerHTML = '<div class="mobile-row-card"><div class="mobile-row-name">No roster data available.</div></div>';
        return;
      }
      const teamOptions = sleeperTeams.map((t) => {
        const name = String(t?.name || '');
        const selected = myTeam && name === myTeam ? 'selected' : '';
        return `<option value="${esc(name)}" ${selected}>${esc(name)}</option>`;
      }).join('');
      const rosterGroupControls = ROSTER_POSITION_GROUP_KEYS.map((g) => {
        const color = POS_GROUP_COLORS[g] || 'var(--subtext)';
        const checked = groupState[g] ? 'checked' : '';
        return `<label style="display:inline-flex;align-items:center;gap:6px;font-size:0.68rem;font-weight:700;color:${color};padding:4px 8px;border:1px solid var(--border-dim);border-radius:999px;background:var(--bg-card);">
          <input type="checkbox" id="moreRosterFilter_${g}" ${checked} onchange="applyMobileMoreRosterControls(true)" style="width:13px;height:13px;accent-color:${color};"> ${g}
        </label>`;
      }).join('');
      const picksChecked = includePicks ? 'checked' : '';
      const topTeam = snapshot[0];
      const myTeamRow = snapshot.find((t) => t.name === myTeam) || null;
      const compositionRows = snapshot.map((t, idx) => {
        const activeTotal = Number(t.activeTotal || 0);
        const stackBars = activeGroupList.map((g) => {
          const gVal = Number(t?.byGroup?.[g] || 0);
          if (!Number.isFinite(gVal) || gVal <= 0) return '';
          const pct = Math.max(2, Math.min(100, (gVal / Math.max(1, activeTotal)) * 100));
          const color = POS_GROUP_COLORS[g] || 'var(--subtext)';
          return `<span title="${g}: ${Math.round(gVal).toLocaleString()}" style="display:block;height:100%;width:${pct}%;background:${color};"></span>`;
        }).join('') || '<span style="display:block;height:100%;width:100%;background:var(--border-dim);"></span>';
        const groupPills = activeGroupList.map((g) => {
          const v = Number(t?.byGroup?.[g] || 0);
          if (!Number.isFinite(v) || v <= 0) return '';
          const color = POS_GROUP_COLORS[g] || 'var(--subtext)';
          return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:999px;border:1px solid ${color}55;color:${color};font-size:0.62rem;font-family:var(--mono);font-weight:700;">${g} ${Math.round(v).toLocaleString()}</span>`;
        }).join('');
        return `
          <div class="mobile-row-card" style="padding:10px 12px;${myTeam && myTeam === t.name ? 'border-color:var(--cyan-border);background:var(--cyan-soft);' : ''}">
            <div class="mobile-row-head">
              <div>
                <div class="mobile-row-name">#${idx + 1} ${t.name}${myTeam && myTeam === t.name ? ' ★' : ''}</div>
                <div class="mobile-row-sub">Filtered ${Math.round(activeTotal).toLocaleString()} · Full ${Math.round(t.total || 0).toLocaleString()}</div>
              </div>
              <div class="mobile-row-value">${Math.round(activeTotal).toLocaleString()}</div>
            </div>
            <div style="height:10px;border-radius:999px;overflow:hidden;background:var(--bg-soft);display:flex;margin-top:8px;">${stackBars}</div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">
              ${groupPills || '<span style="font-size:0.64rem;color:var(--subtext);">No value in selected groups.</span>'}
            </div>
          </div>
        `;
      }).join('');
      const rosterBoardCards = rosterSubview === 'board'
        ? snapshot.map((t, idx) => {
            const activeTotal = Number(t.activeTotal || 0);
            const stackBars = activeGroupList.map((g) => {
              const gVal = Number(t?.byGroup?.[g] || 0);
              if (!Number.isFinite(gVal) || gVal <= 0) return '';
              const pct = Math.max(2, Math.min(100, (gVal / Math.max(1, activeTotal)) * 100));
              const color = POS_GROUP_COLORS[g] || 'var(--subtext)';
              return `<span title="${g}: ${Math.round(gVal).toLocaleString()}" style="display:block;height:100%;width:${pct}%;background:${color};"></span>`;
            }).join('') || '<span style="display:block;height:100%;width:100%;background:var(--border-dim);"></span>';
            const escapedName = String(t.name || '').replace(/'/g, "\\'");
            return `
        <div class="mobile-row-card">
          <div class="mobile-row-head">
            <div>
              <div class="mobile-row-name">#${idx + 1} ${t.name}${myTeam && t.name === myTeam ? ' ★' : ''}</div>
              <div class="mobile-row-sub">Active ${Math.round(activeTotal).toLocaleString()} · Total ${Math.round(t.total || 0).toLocaleString()} · Starters ${Math.round(t.starterTotal || 0).toLocaleString()} · Picks ${Math.round(t.pickTotal || 0).toLocaleString()} · IDP ${Math.round(t.idpTotal || 0).toLocaleString()}</div>
              <div style="display:flex;align-items:center;gap:6px;margin-top:6px;">
                <span style="font-size:0.62rem;color:var(--subtext);font-weight:700;letter-spacing:0.04em;">${activeGroupList.join('/')}</span>
                <div style="flex:1;height:9px;border-radius:999px;overflow:hidden;background:var(--bg-soft);display:flex;min-width:100px;">${stackBars}</div>
              </div>
            </div>
            <div class="mobile-row-value">${Math.round(activeTotal).toLocaleString()}</div>
          </div>
          <div class="mobile-row-actions">
            <button class="mobile-chip-btn ${myTeam && t.name === myTeam ? 'primary' : ''}" onclick="selectMyTeamFromMore('${escapedName}')">${myTeam && t.name === myTeam ? 'My Team' : 'Set My Team'}</button>
            <button class="mobile-chip-btn" onclick="openTeamBreakdownFromMore('${escapedName}')">Breakdown</button>
            <button class="mobile-chip-btn" onclick="openTeamComparisonFromMore('${escapedName}')">Compare</button>
            <button class="mobile-chip-btn" onclick="switchTab('calculator')">Trade</button>
          </div>
        </div>`;
          }).join('')
        : '';

      body.innerHTML = `
        <div class="mobile-row-card">
          <div class="mobile-row-name">Roster Controls</div>
          <div class="mobile-row-sub">Filter the exact positions and picks that count toward roster totals.</div>
          <div class="mobile-row-actions">
            <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
              Team
              <select id="moreRosterTeamSelect" onchange="applyMobileMoreRosterControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;min-width:120px;">
                ${teamOptions}
              </select>
            </label>
            <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
              Value
              <select id="moreRosterValueModeSelect" onchange="applyMobileMoreRosterControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;">
                <option value="full" ${rosterValueMode === 'full' ? 'selected' : ''}>Players + Picks</option>
                <option value="players" ${rosterValueMode === 'players' ? 'selected' : ''}>Players only</option>
                <option value="starters" ${rosterValueMode === 'starters' ? 'selected' : ''}>Starters only</option>
              </select>
            </label>
            <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
              Basis
              <select id="moreRosterValueBasisSelect" onchange="applyMobileMoreRosterControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;">
                <option value="full" ${valueBasis === 'full' ? 'selected' : ''}>Full</option>
                <option value="scoring" ${valueBasis === 'scoring' ? 'selected' : ''}>Scoring</option>
                <option value="scarcity" ${valueBasis === 'scarcity' ? 'selected' : ''}>Scarcity</option>
                <option value="raw" ${valueBasis === 'raw' ? 'selected' : ''}>Raw</option>
              </select>
            </label>
          </div>
          <div class="mobile-inline-grid" style="margin-top:8px;">
            <div class="mobile-inline-stat"><div class="label">My Team (Filtered)</div><div class="value">${Math.round(Number(myTeamRow?.activeTotal || 0)).toLocaleString()}</div></div>
            <div class="mobile-inline-stat"><div class="label">League Leader</div><div class="value">${esc(topTeam?.name || '—')} · ${Math.round(Number(topTeam?.activeTotal || 0)).toLocaleString()}</div></div>
          </div>
          <div class="mobile-row-actions" style="margin-top:8px;">
            <button class="mobile-chip-btn" onclick="setMobileMoreRosterGroupPreset('offense')">Offense</button>
            <button class="mobile-chip-btn" onclick="setMobileMoreRosterGroupPreset('idp')">IDP</button>
            <button class="mobile-chip-btn" onclick="setMobileMoreRosterGroupPreset('all')">All</button>
            <button class="mobile-chip-btn" onclick="setMobileMoreRosterGroupPreset('none')">Reset</button>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">
            ${rosterGroupControls}
          </div>
          <label style="display:inline-flex;align-items:center;gap:8px;font-size:0.7rem;font-weight:700;color:${POS_GROUP_COLORS.PICKS || 'var(--amber)'};padding:6px 10px;border:1px solid var(--border-dim);border-radius:999px;background:var(--bg-card);margin-top:8px;">
            <input type="checkbox" id="moreRosterIncludePicks" ${picksChecked} onchange="applyMobileMoreRosterControls(true)" style="width:14px;height:14px;accent-color:${POS_GROUP_COLORS.PICKS || 'var(--amber)'};">
            Include Picks in Total
          </label>
          <div class="mobile-row-actions" style="margin-top:10px;">
            <button class="mobile-chip-btn primary" onclick="applyMobileMoreRosterControls()">Apply Roster Controls</button>
            <button class="mobile-chip-btn" onclick="openFullMobileWorkspace('rosters')">Open Full Rosters</button>
          </div>
        </div>
        <div class="mobile-row-card">
          <div class="mobile-row-name">Team Composition Breakdown</div>
          <div class="mobile-row-sub">Every team’s filtered total split by ${activeGroupList.join('/')}.</div>
          <div style="display:grid;gap:8px;margin-top:8px;">
            ${compositionRows}
          </div>
        </div>
        <div class="mobile-row-card">
          <div class="mobile-row-name">Roster Insights</div>
          <div class="mobile-row-sub">Use the same desktop modules directly in mobile.</div>
          <div class="mobile-segment mobile-subsegment">
            <button class="mobile-segment-btn ${rosterSubview === 'board' ? 'active' : ''}" onclick="setMobileMoreRosterSubview('board')">Board</button>
            <button class="mobile-segment-btn ${rosterSubview === 'targets' ? 'active' : ''}" onclick="setMobileMoreRosterSubview('targets')">Targets</button>
            <button class="mobile-segment-btn ${rosterSubview === 'grades' ? 'active' : ''}" onclick="setMobileMoreRosterSubview('grades')">Grades</button>
            <button class="mobile-segment-btn ${rosterSubview === 'waivers' ? 'active' : ''}" onclick="setMobileMoreRosterSubview('waivers')">Waivers</button>
            <button class="mobile-segment-btn ${rosterSubview === 'tendencies' ? 'active' : ''}" onclick="setMobileMoreRosterSubview('tendencies')">Tendencies</button>
          </div>
          <div id="moreRosterSubviewBody" style="margin-top:10px;"></div>
        </div>
        <div class="mobile-row-card">
          <div class="mobile-row-name">Advanced Rosters Workspace</div>
          <div class="mobile-row-sub">Open the full roster dashboard, targets, grades, waivers, and tendencies.</div>
          <div class="mobile-row-actions">
            <button class="mobile-chip-btn primary" onclick="openFullMobileWorkspace('rosters')">Open Full Rosters</button>
          </div>
        </div>
        ${rosterBoardCards}
      `;

      const subviewBody = document.getElementById('moreRosterSubviewBody');
      if (subviewBody) {
        const targetsHtml = document.getElementById('tradeTargets')?.innerHTML || '';
        const gradesHtml = document.getElementById('tradeGrades')?.innerHTML || '';
        const waiversHtml = document.getElementById('waiverWire')?.innerHTML || '';
        const tendenciesHtml = document.getElementById('tendenciesBody')?.innerHTML || '';
        if (rosterSubview === 'targets') {
          subviewBody.innerHTML = targetsHtml
            ? `<div class="mobile-embedded-panel">${targetsHtml}</div>`
            : '<div class="mobile-preview-note">No target recommendations for current filters. Try another team or value lens.</div>';
        } else if (rosterSubview === 'grades') {
          subviewBody.innerHTML = gradesHtml
            ? `<div class="mobile-embedded-panel">${gradesHtml}</div>`
            : '<div class="mobile-preview-note">No trade grades available yet.</div>';
        } else if (rosterSubview === 'waivers') {
          subviewBody.innerHTML = waiversHtml
            ? `<div class="mobile-embedded-panel">${waiversHtml}</div>`
            : '<div class="mobile-preview-note">No waiver recommendations available with current data.</div>';
        } else if (rosterSubview === 'tendencies') {
          subviewBody.innerHTML = tendenciesHtml
            ? `<div class="mobile-embedded-panel">${tendenciesHtml}</div>`
            : `<div class="mobile-preview-note">Run trade tendency analysis to populate this view.</div>
               <div class="mobile-row-actions" style="margin-top:8px;">
                 <button class="mobile-chip-btn primary" onclick="refreshMobileMoreTendencies()">Analyze Trades</button>
               </div>`;
        } else {
          subviewBody.innerHTML = '<div class="mobile-preview-note">Board mode shows the full team value table below with your current roster controls applied.</div>';
        }
      }
      return;
    }

    if (section === 'league') {
      setTitle('League Snapshot');
      const tiers = getTeamTier(sleeperTeams || []);
      if (!tiers.length) {
        body.innerHTML = '<div class="mobile-row-card"><div class="mobile-row-name">No league overview available.</div></div>';
        return;
      }
      initLeagueTab();
      const esc = (v) => String(v ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
      const leagueView = getMobileLeagueSubPreference();
      const valueBasis = getCalculatorValueBasis();
      const myTeam = String(document.getElementById('rosterMyTeam')?.value || localStorage.getItem('dynasty_my_team') || '');
      const breakdownTeam = String(document.getElementById('breakdownTeamSelect')?.value || localStorage.getItem('dynasty_my_team') || sleeperTeams?.[0]?.name || '');
      const breakdownMode = String(document.getElementById('breakdownViewMode')?.value || 'grouped');
      const compareA = String(document.getElementById('compareTeamA')?.value || sleeperTeams?.[0]?.name || '');
      const compareB = String(document.getElementById('compareTeamB')?.value || sleeperTeams?.[1]?.name || sleeperTeams?.[0]?.name || '');
      const tradeSearch = String(document.getElementById('ktcTradeSearch')?.value || '');
      const waiverSearch = String(document.getElementById('ktcWaiverSearch')?.value || '');
      const teamOptions = sleeperTeams.map((t) => {
        const name = String(t?.name || '');
        return `<option value="${esc(name)}">${esc(name)}</option>`;
      }).join('');
      body.innerHTML = `
        <div class="mobile-row-card">
          <div class="mobile-row-name">League View Controls</div>
          <div class="mobile-row-sub">Match desktop heatmap, breakdown, and comparison controls from mobile.</div>
          <div class="mobile-row-actions">
            <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
              View
              <select id="moreLeagueViewSelect" onchange="applyMobileMoreLeagueControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;min-width:118px;">
                <option value="heatmap" ${leagueView === 'heatmap' ? 'selected' : ''}>Power Rankings</option>
                <option value="breakdown" ${leagueView === 'breakdown' ? 'selected' : ''}>Team Breakdown</option>
                <option value="compare" ${leagueView === 'compare' ? 'selected' : ''}>Comparison</option>
                <option value="ktcTrades" ${leagueView === 'ktcTrades' ? 'selected' : ''}>Trade DB</option>
                <option value="ktcWaivers" ${leagueView === 'ktcWaivers' ? 'selected' : ''}>Waiver DB</option>
              </select>
            </label>
            <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
              Basis
              <select id="moreLeagueValueBasisSelect" onchange="applyMobileMoreLeagueControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;">
                <option value="full" ${valueBasis === 'full' ? 'selected' : ''}>Full</option>
                <option value="scoring" ${valueBasis === 'scoring' ? 'selected' : ''}>Scoring</option>
                <option value="scarcity" ${valueBasis === 'scarcity' ? 'selected' : ''}>Scarcity</option>
                <option value="raw" ${valueBasis === 'raw' ? 'selected' : ''}>Raw</option>
              </select>
            </label>
          </div>
          ${leagueView === 'breakdown' ? `
            <div class="mobile-row-actions" style="margin-top:8px;">
              <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
                Team
                <select id="moreLeagueBreakdownTeam" onchange="applyMobileMoreLeagueControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;min-width:120px;">
                  ${teamOptions}
                </select>
              </label>
              <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
                Mode
                <select id="moreLeagueBreakdownMode" onchange="applyMobileMoreLeagueControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;">
                  <option value="grouped" ${breakdownMode === 'grouped' ? 'selected' : ''}>By position</option>
                  <option value="value" ${breakdownMode === 'value' ? 'selected' : ''}>By value</option>
                </select>
              </label>
            </div>
          ` : ''}
          ${leagueView === 'compare' ? `
            <div class="mobile-row-actions" style="margin-top:8px;">
              <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
                Team A
                <select id="moreLeagueCompareA" onchange="applyMobileMoreLeagueControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;min-width:120px;">
                  ${teamOptions}
                </select>
              </label>
              <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
                Team B
                <select id="moreLeagueCompareB" onchange="applyMobileMoreLeagueControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;min-width:120px;">
                  ${teamOptions}
                </select>
              </label>
            </div>
          ` : ''}
          ${leagueView === 'ktcTrades' ? `
            <div class="mobile-row-actions" style="margin-top:8px;">
              <input id="moreLeagueTradeSearch" type="text" value="${esc(tradeSearch)}" placeholder="Search trade DB..." oninput="applyMobileLeagueSearch('trades', this.value)" style="font-size:0.72rem;padding:7px 9px;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:8px;min-width:0;flex:1;">
            </div>
          ` : ''}
          ${leagueView === 'ktcWaivers' ? `
            <div class="mobile-row-actions" style="margin-top:8px;">
              <input id="moreLeagueWaiverSearch" type="text" value="${esc(waiverSearch)}" placeholder="Search waiver DB..." oninput="applyMobileLeagueSearch('waivers', this.value)" style="font-size:0.72rem;padding:7px 9px;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:8px;min-width:0;flex:1;">
            </div>
          ` : ''}
          <div class="mobile-row-actions" style="margin-top:10px;">
            <button class="mobile-chip-btn primary" onclick="applyMobileMoreLeagueControls()">Apply League View</button>
            <button class="mobile-chip-btn" onclick="openFullMobileWorkspace('league')">Open Full League</button>
          </div>
        </div>
        <div class="mobile-row-card">
          <div class="mobile-row-name">League View Preview</div>
          <div class="mobile-row-sub">Live output of the selected desktop league module.</div>
          <div id="moreLeaguePreview"></div>
        </div>
        <div class="mobile-row-card">
          <div class="mobile-row-name">Advanced League Workspace</div>
          <div class="mobile-row-sub">Open full power rankings, team breakdown, comparison, trade DB, and waiver DB.</div>
          <div class="mobile-row-actions">
            <button class="mobile-chip-btn primary" onclick="openFullMobileWorkspace('league')">Open Full League</button>
          </div>
        </div>
        <div class="mobile-inline-grid">
          <div class="mobile-inline-stat"><div class="label">Contenders</div><div class="value">${tiers.filter(t => t.tier === 'contender').length}</div></div>
          <div class="mobile-inline-stat"><div class="label">Rebuilders</div><div class="value">${tiers.filter(t => t.tier === 'rebuilder').length}</div></div>
        </div>
        ${tiers.map(t => `
          <div class="mobile-row-card">
            <div class="mobile-row-head">
              <div>
                <div class="mobile-row-name">#${t.rank} ${t.name}${myTeam && t.name === myTeam ? ' ★' : ''}</div>
                <div class="mobile-row-sub">${t.tierLabel} · starters ${Math.round(t.starterValue || 0).toLocaleString()} · depth ${Math.round(t.depthValue || 0).toLocaleString()}</div>
              </div>
              <div class="mobile-row-value">${Math.round(t.totalValue || 0).toLocaleString()}</div>
            </div>
            <div class="mobile-row-actions">
              <button class="mobile-chip-btn ${myTeam && t.name === myTeam ? 'primary' : ''}" onclick="selectMyTeamFromMore('${String(t.name).replace(/'/g, "\\'")}')">${myTeam && t.name === myTeam ? 'My Team' : 'Set My Team'}</button>
              <button class="mobile-chip-btn" onclick="openTeamBreakdownFromMore('${String(t.name).replace(/'/g, "\\'")}')">Breakdown</button>
              <button class="mobile-chip-btn" onclick="openTeamComparisonFromMore('${String(t.name).replace(/'/g, "\\'")}')">Compare</button>
              <button class="mobile-chip-btn" onclick="switchTab('calculator')">Trade</button>
            </div>
          </div>
        `).join('')}
      `;
      const breakdownEl = document.getElementById('moreLeagueBreakdownTeam');
      if (breakdownEl && breakdownTeam) breakdownEl.value = breakdownTeam;
      const compareAEl = document.getElementById('moreLeagueCompareA');
      if (compareAEl && compareA) compareAEl.value = compareA;
      const compareBEl = document.getElementById('moreLeagueCompareB');
      if (compareBEl && compareB) compareBEl.value = compareB;
      renderMobileMoreLeaguePreview(leagueView);
      return;
    }

    if (section === 'trades') {
      setTitle('Trade Activity');
      buildTradeHistoryPage();
      const trades = Array.isArray(loadedData?.sleeper?.trades) ? loadedData.sleeper.trades : [];
      if (!trades.length) {
        body.innerHTML = '<div class="mobile-row-card"><div class="mobile-row-name">No league trade data loaded.</div></div>';
        return;
      }
      const rows = filterTradesToRollingWindow([...trades]).slice(0, 16);
      const windowDays = getTradeHistoryWindowDays();
      if (!rows.length) {
        body.innerHTML = `<div class="mobile-row-card"><div class="mobile-row-name">No league trades in the last ${windowDays} days.</div></div>`;
        return;
      }
      const teamFilterSel = document.getElementById('tradeTeamFilter');
      const selectedFilter = String(teamFilterSel?.value || '');
      const filterOptions = teamFilterSel
        ? Array.from(teamFilterSel.options).map((opt) => {
            const val = String(opt.value || '');
            const sel = val === selectedFilter ? 'selected' : '';
            return `<option value="${val.replace(/"/g, '&quot;')}" ${sel}>${String(opt.textContent || val)}</option>`;
          }).join('')
        : '<option value="">All trades</option>';
      const tradesSubview = normalizeMobileMoreTradesSubview(mobileMoreTradesView);
      body.innerHTML = `
        <div class="mobile-row-card">
          <div class="mobile-row-name">Trade Controls</div>
          <div class="mobile-row-sub">Match desktop trade history filters and analytics from mobile.</div>
          <div class="mobile-row-actions">
            <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
              Team
              <select id="moreTradeTeamFilter" onchange="applyMobileMoreTradeControls(true)" style="font-size:0.72rem;padding:4px 8px;background:transparent;color:var(--text);border:none;outline:none;min-width:120px;">
                ${filterOptions}
              </select>
            </label>
            <button class="mobile-chip-btn primary" onclick="applyMobileMoreTradeControls()">Apply</button>
          </div>
          <div class="mobile-segment mobile-subsegment">
            <button class="mobile-segment-btn ${tradesSubview === 'history' ? 'active' : ''}" onclick="setMobileMoreTradesSubview('history')">History</button>
            <button class="mobile-segment-btn ${tradesSubview === 'stats' ? 'active' : ''}" onclick="setMobileMoreTradesSubview('stats')">Winners</button>
          </div>
          <div id="moreTradesPreview" style="margin-top:10px;"></div>
        </div>
        <div class="mobile-row-card">
          <div class="mobile-row-name">Advanced Trades Workspace</div>
          <div class="mobile-row-sub">Open full trade history analytics and team filters.</div>
          <div class="mobile-row-actions">
            <button class="mobile-chip-btn primary" onclick="openFullMobileWorkspace('trades')">Open Full Trades</button>
          </div>
        </div>
      `;
      renderMobileMoreTradesPreview();
      return;
    }

    if (section === 'finder') {
      setTitle('Trade Finder');
      const myTeam = document.getElementById('rosterMyTeam')?.value || localStorage.getItem('dynasty_my_team') || '';
      body.innerHTML = `
        <div class="mobile-row-card">
          <div class="mobile-row-name">Trade Finder</div>
          <div class="mobile-row-sub">Find trades where our model favors your side, but KTC makes it fair for the opponent.</div>
          <div class="mobile-row-actions">
            <button class="mobile-chip-btn primary" onclick="openFullMobileWorkspace('finder')">Open Trade Finder</button>
          </div>
        </div>
        <div class="mobile-row-card">
          <div class="mobile-row-name">Your Team</div>
          <div class="mobile-row-sub">${myTeam || 'Not selected — set team above'}</div>
        </div>
      `;
      return;
    }

    setTitle('Mobile Settings');
    const valueMode = getCalculatorValueBasis();
    const rankMode = getRankingsSortBasis();
    const dataMode = getRankingsDataMode();
    const lamStrength = Number(document.getElementById('lamStrengthInput')?.value || 1);
    const alpha = Number(document.getElementById('alphaInput')?.value || DEFAULT_ALPHA);
    const scarcityStrength = Number(document.getElementById('scarcityStrengthInput')?.value || 0.35);
    const tepMultiplier = Number(document.getElementById('tepMultiplierInput')?.value || 1.15);
    const zBlend = !!document.getElementById('zScoreToggle')?.checked;
    const showCols = !!document.getElementById('rankingsShowLamCols')?.checked;
    const showSiteCols = !!document.getElementById('rankingsShowSiteCols')?.checked;
    const mobilePower = getMobilePowerModeEnabled();
    const siteCfg = getSiteConfig();
    const includedSiteCount = siteCfg.filter((s) => !!s.include).length;
    const activeSiteCount = siteCfg.filter((s) => {
      const row = document.querySelector(`#siteConfigBody tr[data-site-key="${s.key}"]`);
      return !row || row.style.display !== 'none';
    }).length;
    body.innerHTML = `
      <div class="mobile-row-card">
        <div class="mobile-row-name">Default Value Basis</div>
        <div class="mobile-row-sub">Controls rankings and calculator value lens.</div>
        <div class="mobile-row-actions">
          <select onchange="handleValueBasisChange(this.value, 'mobileMoreSettings')" style="font-size:0.74rem;padding:6px 8px;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;">
            <option value="full" ${valueMode === 'full' ? 'selected' : ''}>Fully Adjusted</option>
            <option value="scoring" ${valueMode === 'scoring' ? 'selected' : ''}>Scoring Adjusted</option>
            <option value="scarcity" ${valueMode === 'scarcity' ? 'selected' : ''}>Scarcity Adjusted</option>
            <option value="raw" ${valueMode === 'raw' ? 'selected' : ''}>Raw Market</option>
          </select>
        </div>
      </div>
      <div class="mobile-row-card">
        <div class="mobile-row-name">Ranking View</div>
        <div class="mobile-row-actions">
          <select onchange="setRankingsDataMode(this.value, {persist:true, refresh:true})" style="font-size:0.74rem;padding:6px 8px;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;">
            <option value="dynasty" ${dataMode === 'dynasty' ? 'selected' : ''}>Dynasty</option>
            <option value="redraft" ${dataMode === 'redraft' ? 'selected' : ''}>Redraft</option>
            <option value="ros" ${dataMode === 'ros' ? 'selected' : ''}>ROS</option>
          </select>
          <select onchange="handleValueBasisChange(this.value, 'mobileMoreSettings')" style="font-size:0.74rem;padding:6px 8px;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;">
            <option value="full" ${rankMode === 'full' ? 'selected' : ''}>Full</option>
            <option value="scoring" ${rankMode === 'scoring' ? 'selected' : ''}>Scoring</option>
            <option value="scarcity" ${rankMode === 'scarcity' ? 'selected' : ''}>Scarcity</option>
            <option value="raw" ${rankMode === 'raw' ? 'selected' : ''}>Raw</option>
          </select>
        </div>
      </div>
      <div class="mobile-row-card">
        <div class="mobile-row-name">Adjustment Visibility</div>
        <div class="mobile-row-actions">
          <label class="mobile-chip-btn ${showCols ? 'primary' : ''}" style="display:inline-flex;align-items:center;gap:6px;">
            <input type="checkbox" ${showCols ? 'checked' : ''} onchange="setRankingsDetailColumnsVisible(this.checked); buildMoreHub();" style="width:14px;height:14px;"> Show Breakdown Columns
          </label>
          <label class="mobile-chip-btn ${showSiteCols ? 'primary' : ''}" style="display:inline-flex;align-items:center;gap:6px;">
            <input type="checkbox" ${showSiteCols ? 'checked' : ''} onchange="setRankingsSourceColumnsVisible(this.checked);" style="width:14px;height:14px;"> Show Source Columns
          </label>
          <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
            LAM Strength
            <input type="number" min="0" max="1" step="0.05" value="${lamStrength.toFixed(2)}" onchange="const el=document.getElementById('lamStrengthInput'); if(el){el.value=this.value;} persistSettings(); recalculate(); buildFullRankings(); buildMoreHub();" style="width:66px;background:transparent;color:var(--text);border:none;outline:none;font-family:var(--mono);font-size:0.72rem;">
          </label>
        </div>
      </div>
      <div class="mobile-row-card">
        <div class="mobile-row-name">Mobile Power Mode</div>
        <div class="mobile-row-sub">Unlock full desktop workflows while staying in mobile navigation.</div>
        <div class="mobile-row-actions">
          <label class="mobile-chip-btn ${mobilePower ? 'primary' : ''}" style="display:inline-flex;align-items:center;gap:6px;">
            <input type="checkbox" id="mobilePowerModeToggleMore" ${mobilePower ? 'checked' : ''} onchange="setMobilePowerMode(this.checked);" style="width:14px;height:14px;"> Enable Full Workspaces
          </label>
          <button class="mobile-chip-btn" onclick="openFullMobileWorkspace('settings')">Open Full Settings</button>
        </div>
      </div>
      <div class="mobile-row-card">
        <div class="mobile-row-name">Site Weight Matrix</div>
        <div class="mobile-row-sub">Touch editor for include/max/weight/TEP source controls.</div>
        <div class="mobile-inline-grid" style="margin-top:8px;">
          <div class="mobile-inline-stat"><div class="label">Included</div><div class="value">${includedSiteCount}</div></div>
          <div class="mobile-inline-stat"><div class="label">Active Sources</div><div class="value">${activeSiteCount}</div></div>
        </div>
        <div class="mobile-row-actions" style="margin-top:10px;">
          <button class="mobile-chip-btn primary" onclick="openMobileSiteMatrixEditor()">Edit Site Matrix</button>
        </div>
      </div>
      <div class="mobile-row-card">
        <div class="mobile-row-name">Advanced Value Controls</div>
        <div class="mobile-row-sub">Tune the same key settings used in desktop trade and ranking calculations.</div>
        <div class="mobile-row-actions">
          <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
            Alpha
            <input id="moreSettingsAlphaInput" type="number" min="1" max="3" step="0.01" value="${alpha.toFixed(3)}" style="width:64px;background:transparent;color:var(--text);border:none;outline:none;font-family:var(--mono);font-size:0.72rem;">
          </label>
          <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
            LAM
            <input id="moreSettingsLamInput" type="number" min="0" max="1" step="0.05" value="${lamStrength.toFixed(2)}" style="width:58px;background:transparent;color:var(--text);border:none;outline:none;font-family:var(--mono);font-size:0.72rem;">
          </label>
          <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
            Scarcity
            <input id="moreSettingsScarcityInput" type="number" min="0" max="1" step="0.05" value="${scarcityStrength.toFixed(2)}" style="width:58px;background:transparent;color:var(--text);border:none;outline:none;font-family:var(--mono);font-size:0.72rem;">
          </label>
          <label class="mobile-chip-btn" style="display:inline-flex;align-items:center;gap:6px;">
            TEP
            <input id="moreSettingsTepInput" type="number" min="1" max="2" step="0.01" value="${tepMultiplier.toFixed(2)}" style="width:58px;background:transparent;color:var(--text);border:none;outline:none;font-family:var(--mono);font-size:0.72rem;">
          </label>
          <label class="mobile-chip-btn ${zBlend ? 'primary' : ''}" style="display:inline-flex;align-items:center;gap:6px;">
            <input type="checkbox" id="moreSettingsZBlendToggle" ${zBlend ? 'checked' : ''} style="width:14px;height:14px;"> Z-Blend
          </label>
          <button class="mobile-chip-btn primary" onclick="applyMobileMoreAdvancedSettings()">Apply Advanced</button>
        </div>
      </div>
    `;
  }

  function setMobileMoreSection(section, opts = {}) {
    mobileMoreSection = normalizeMobileMoreSection(section);
    document.querySelectorAll('[data-more-section]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.moreSection === mobileMoreSection);
    });
    if (activeTabId === 'more') updateMobileChrome('more');
    if (opts.persist !== false) {
      try { localStorage.setItem(MOBILE_MORE_SECTION_KEY, mobileMoreSection); } catch (_) {}
    }
    if (opts.refresh !== false) {
      renderMobileMoreSection();
    }
  }

  function buildMoreHub() {
    const box = document.getElementById('moreSavedTrades');
    if (box) {
      const trades = getSavedTrades();
      box.innerHTML = trades.length
        ? trades.slice(0, 10).map((t, i) => `
            <div class="mobile-row-card">
              <div class="mobile-row-name">${t.label || `Trade ${i+1}`}</div>
              <div class="mobile-row-sub">${t.verdict || ''} · ${t.pct || ''}</div>
              <div class="mobile-row-actions">
                <button class="mobile-chip-btn primary" onclick="loadSavedTrade('${i}');switchTab('calculator')">Load</button>
              </div>
            </div>
          `).join('')
        : '<div class="mobile-row-card"><div class="mobile-row-name">No saved trades.</div></div>';
    }

    setMobileMoreSection(mobileMoreSection, { persist: false, refresh: true });
  }

  function setAlpha(v) { document.getElementById('alphaInput').value = v; }

  // ── PICK PARSING ──
  function normalizeKey(s) { return (s||'').trim().replace(/\s+/g,' '); }

  // ── AUTO-GENERATE PICK DOLLARS FROM ROOKIE META VALUES ──
  function generatePickDollarsFromRookies() {
    if (!loadedData || !loadedData.players) {
      alert('Tap Refresh Values to load player data first.');
      return;
    }
    const proxy = build2026RookiePickProxyValues();
    if (!proxy || !proxy.slotValues) {
      alert('No usable rookie values found for 2026 pick proxy.');
      return;
    }

    // Take top 72 (6 rounds × 12 teams), pad with minimum if fewer
    const TOTAL_PICKS = 72;
    const BUDGET = 1200;
    const picks = [];
    for (let i = 0; i < TOTAL_PICKS; i++) {
      const round = Math.floor(i / 12) + 1;
      const slot = (i % 12) + 1;
      const key = `${round}.${String(slot).padStart(2, '0')}`;
      const val = Number(proxy.slotValues[key]);
      picks.push(isFinite(val) && val > 0 ? val : 1);
    }

    // Compute γ from coefficient of variation of top 6
    const top6 = picks.slice(0, 6);
    const avg6 = top6.reduce((a, b) => a + b, 0) / 6;
    const std6 = Math.sqrt(top6.reduce((a, v) => a + (v - avg6) ** 2, 0) / 5);
    const cv = avg6 > 0 ? std6 / avg6 : 0;
    const gamma = Math.max(1.12, 1 + Math.min(0.35, 0.9 * cv));

    // Apply formula: value^γ × exp(-0.046 × position)
    const decay = 0.046;
    const transformed = picks.map((v, i) => Math.pow(v, gamma) * Math.exp(-decay * i));
    const totalTransformed = transformed.reduce((a, b) => a + b, 0);

    // Normalize to $1,200 with $1 floor
    const raw = transformed.map(t => 1 + (BUDGET - TOTAL_PICKS) * t / totalTransformed);

    // Largest-remainder rounding to exactly $1,200
    const floored = raw.map(v => Math.floor(v));
    let leftover = BUDGET - floored.reduce((a, b) => a + b, 0);
    const decimals = raw.map((v, i) => ({ i, dec: v - Math.floor(v) }));
    decimals.sort((a, b) => b.dec - a.dec);
    for (let j = 0; j < leftover; j++) {
      floored[decimals[j].i] += 1;
    }

    // Build pick slot labels and dollar map text
    const lines = [];
    for (let i = 0; i < TOTAL_PICKS; i++) {
      const round = Math.floor(i / 12) + 1;
      const slot = (i % 12) + 1;
      const key = `${round}.${String(slot).padStart(2, '0')}`;
      lines.push(`${key}=${floored[i]}`);
    }

    const mapText = lines.join('\n');
    document.getElementById('pickDollarMap').value = mapText;

    // Show summary
    const r1 = floored.slice(0, 12).reduce((a, b) => a + b, 0);
    const r2 = floored.slice(12, 24).reduce((a, b) => a + b, 0);
    const total = floored.reduce((a, b) => a + b, 0);
    console.log(`Pick $ generated: γ=${gamma.toFixed(3)}, CV=${cv.toFixed(3)}, R1=$${r1}, R2=$${r2}, Total=$${total}`);
    const topPreview = (proxy.ranked || []).slice(0, 6).map(r => `${r.name} (${Math.round(r.fullyAdjusted)})`).join(', ');
    console.log(`Top rookies: ${topPreview}`);

    persistSettings();
    scheduleRecalc();
  }

  // ── PICK VALUES (KTC-scale) — from league auction data ──
  // These are direct consensus values for each pick slot, used when
  // no site data is manually entered for a pick.
  const PICK_KTC_VALUES = {
    '1.01':6674, '1.02':6109, '1.03':5861, '1.04':5598, '1.05':5314, '1.06':5139,
    '1.07':4786, '1.08':4716, '1.09':4598, '1.10':4488, '1.11':4322, '1.12':4113,
    '2.01':3916, '2.02':3846, '2.03':3600, '2.04':3471, '2.05':3391, '2.06':3251,
    '2.07':3170, '2.08':3138, '2.09':3038, '2.10':3004, '2.11':2886, '2.12':2755,
    '3.01':2627, '3.02':2490, '3.03':2381, '3.04':2341, '3.05':2327, '3.06':2298,
    '3.07':2269, '3.08':2247, '3.09':2187, '3.10':2166, '3.11':2121, '3.12':2076,
    '4.01':1990, '4.02':1930, '4.03':1878, '4.04':1836, '4.05':1795, '4.06':1753,
    '4.07':1715, '4.08':1682, '4.09':1649, '4.10':1616, '4.11':1582, '4.12':1549,
    '5.01':1525, '5.02':1496, '5.03':1468, '5.04':1440, '5.05':1414, '5.06':1388,
    '5.07':1363, '5.08':1339, '5.09':1315, '5.10':1292, '5.11':1270, '5.12':1248,
    '6.01':1227, '6.02':1207, '6.03':1187, '6.04':1168, '6.05':1149, '6.06':1131,
    '6.07':1113, '6.08':1095, '6.09':1078, '6.10':1062, '6.11':1046, '6.12':1030,
  };

  function normalizePickKey(s) {
    const t = (s||'').trim().toUpperCase();
    const m = t.match(/^([1-6])\.(\d{1,2})$/);
    if (!m) return null;
    const r = parseInt(m[1]), p = parseInt(m[2]);
    if (!(r>=1&&r<=6&&p>=1&&p<=12)) return null;
    return `${r}.${String(p).padStart(2,'0')}`;
  }

  function pickTierSlotRange(tier, leagueSize) {
    const slotsPerTier = Math.ceil((leagueSize || 12) / 3);
    if (tier === 'early') return { start: 1, end: slotsPerTier };
    if (tier === 'mid') return { start: slotsPerTier + 1, end: Math.min((slotsPerTier * 2), leagueSize || 12) };
    return { start: (slotsPerTier * 2) + 1, end: leagueSize || 12 };
  }

  function pickSlotToTier(slot, leagueSize) {
    const rangeEarly = pickTierSlotRange('early', leagueSize);
    const rangeMid = pickTierSlotRange('mid', leagueSize);
    if (slot >= rangeEarly.start && slot <= rangeEarly.end) return 'early';
    if (slot >= rangeMid.start && slot <= rangeMid.end) return 'mid';
    return 'late';
  }

  function pickTierRepresentativeSlot(tier, leagueSize) {
    const range = pickTierSlotRange(tier, leagueSize);
    if (tier === 'early') return Math.min(range.end, range.start + 2);
    if (tier === 'mid') return Math.floor((range.start + range.end) / 2);
    return Math.max(range.start, range.end - 2);
  }

  function parseAnchorPickName(raw) {
    if (!raw) return null;
    let s = normalizeKey(raw).toUpperCase().trim();
    // Ignore display decorations like "(from Team Name)".
    s = s.replace(/\s*\([^)]*\)\s*$/, '').trim();
    s = s
      .replace(/[-\u2010-\u2015\u2212]/g, ' ')  // hyphen + dash variants
      .replace(/_+/g, ' ')                      // URL/slug separators
      .replace(/[,;:/\\|]+/g, ' ')
      .replace(/\bMIDDLE\b/g, 'MID')
      .replace(/\bFIRST\b/g, '1ST')
      .replace(/\bSECOND\b/g, '2ND')
      .replace(/\bTHIRD\b/g, '3RD')
      .replace(/\bFOURTH\b/g, '4TH')
      .replace(/\bFIFTH\b/g, '5TH')
      .replace(/\bSIXTH\b/g, '6TH')
      .replace(/\b(PICK|ROUND|RD|DRAFT|OVERALL)\b/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim();

    let m = s.match(/^(\d{4})\s+([1-6])\.(0?[1-9]|1[0-2])$/);
    if (m) {
      return {
        kind: 'slot',
        year: parseInt(m[1], 10),
        round: parseInt(m[2], 10),
        slot: parseInt(m[3], 10),
      };
    }

    m = s.match(/^([1-6])\.(0?[1-9]|1[0-2])$/);
    if (m) {
      return {
        kind: 'slot',
        year: null,
        round: parseInt(m[1], 10),
        slot: parseInt(m[2], 10),
      };
    }

    m = s.match(/^(\d{4})\s+(EARLY|MID|LATE)\s+([1-6])(?:\s*(ST|ND|RD|TH))?$/);
    if (m) {
      return {
        kind: 'tier',
        year: parseInt(m[1], 10),
        tier: m[2].toLowerCase(),
        round: parseInt(m[3], 10),
      };
    }

    m = s.match(/^(EARLY|MID|LATE)\s+([1-6])(?:\s*(ST|ND|RD|TH))?$/);
    if (m) {
      return {
        kind: 'tier',
        year: null,
        tier: m[1].toLowerCase(),
        round: parseInt(m[2], 10),
      };
    }

    m = s.match(/^(\d{4})\s+([1-6])(?:\s*(ST|ND|RD|TH))?\s*(EARLY|MID|LATE)?$/);
    if (m) {
      return {
        kind: 'tier',
        year: parseInt(m[1], 10),
        tier: m[4] ? m[4].toLowerCase() : 'mid',
        round: parseInt(m[2], 10),
      };
    }

    m = s.match(/^([1-6])(?:\s*(ST|ND|RD|TH))?\s*(EARLY|MID|LATE)?$/);
    if (m) {
      return {
        kind: 'tier',
        year: null,
        tier: m[3] ? m[3].toLowerCase() : 'mid',
        round: parseInt(m[1], 10),
      };
    }

    m = s.match(/^(\d{4})\s+([1-6])$/);
    if (m) {
      return {
        kind: 'tier',
        year: parseInt(m[1], 10),
        tier: 'mid',
        round: parseInt(m[2], 10),
      };
    }

    m = s.match(/^([1-6])$/);
    if (m) {
      return {
        kind: 'tier',
        year: null,
        tier: 'mid',
        round: parseInt(m[1], 10),
      };
    }
    return null;
  }

  const pickTokenParseCache = new Map();

  function parsePickToken(raw) {
    const currentYear = parseInt(document.getElementById('pickCurrentYear')?.value) || 2026;
    const cacheKey = `${currentYear}|${String(raw || '').trim()}`;
    if (pickTokenParseCache.has(cacheKey)) {
      return pickTokenParseCache.get(cacheKey);
    }
    const parsed = parseAnchorPickName(raw);
    if (!parsed) {
      if (pickTokenParseCache.size > 8192) pickTokenParseCache.clear();
      pickTokenParseCache.set(cacheKey, null);
      return null;
    }

    if (parsed.kind === 'slot') {
      const out = {
        kind: 'slot',
        year: Number.isFinite(parsed.year) ? parsed.year : null,
        round: parsed.round,
        slot: parsed.slot,
        key: `${parsed.round}.${String(parsed.slot).padStart(2, '0')}`,
      };
      if (pickTokenParseCache.size > 8192) pickTokenParseCache.clear();
      pickTokenParseCache.set(cacheKey, out);
      return out;
    }

    const yr = Number.isFinite(parsed.year) ? parsed.year : currentYear;

    const out = {
      kind: 'tier',
      year: yr,
      tier: parsed.tier || 'mid',
      round: parsed.round,
    };
    if (pickTokenParseCache.size > 8192) pickTokenParseCache.clear();
    pickTokenParseCache.set(cacheKey, out);
    return out;
  }

  function pickRoundSuffix(roundNum) {
    const n = Number(roundNum);
    if (!isFinite(n)) return 'th';
    const v = Math.abs(Math.trunc(n));
    if (v % 100 >= 11 && v % 100 <= 13) return 'th';
    if (v % 10 === 1) return 'st';
    if (v % 10 === 2) return 'nd';
    if (v % 10 === 3) return 'rd';
    return 'th';
  }

  function getCanonicalPickLookupLabels(pickInfo) {
    if (!pickInfo) return [];
    const currentYear = parseInt(document.getElementById('pickCurrentYear')?.value) || 2026;
    const out = [];
    const pushUnique = (label) => {
      const s = String(label || '').trim();
      if (!s) return;
      if (!out.some(x => normalizeForLookup(x) === normalizeForLookup(s))) out.push(s);
    };
    const yr = Number.isFinite(pickInfo.year) ? pickInfo.year : currentYear;

    if (pickInfo.kind === 'slot') {
      const r = Number(pickInfo.round);
      const s = Number(pickInfo.slot);
      if (!isFinite(r) || !isFinite(s)) return out;
      const slot2 = String(s).padStart(2, '0');
      // Canonical scraper pick labels first.
      pushUnique(`${yr} Pick ${r}.${slot2}`);
      // Secondary aliases.
      pushUnique(`${yr} ${r}.${slot2}`);
      pushUnique(`${yr} ${r}.${s}`);
      pushUnique(`${r}.${slot2}`);
      pushUnique(`${r}.${s}`);
      return out;
    }

    if (pickInfo.kind === 'tier') {
      const r = Number(pickInfo.round);
      const tier = String(pickInfo.tier || 'mid').toLowerCase();
      const tierLabel = tier.charAt(0).toUpperCase() + tier.slice(1);
      const suffix = pickRoundSuffix(r);
      // Canonical scraper labels for tier picks.
      pushUnique(`${yr} ${tierLabel} ${r}${suffix}`);
      // Secondary aliases.
      pushUnique(`${yr} ${tierLabel} ${r}`);
      pushUnique(`${tierLabel} ${r}${suffix}`);
      pushUnique(`${tierLabel} ${r}`);
    }
    return out;
  }

  let rookiePickProxyCache = { key: '', data: null };

  function buildSyntheticPickSiteMapFromMeta(metaValue) {
    const target = Number(metaValue);
    if (!isFinite(target) || target <= 0) return null;
    const canonicalTarget = Math.max(1, Math.min(COMPOSITE_SCALE, Math.round(target)));
    const out = {};
    // Synthetic fallback is intentionally single-source. Do NOT stamp one modeled
    // number into every site column (that creates fake cross-site agreement).
    out.ktc = canonicalTarget;
    out.__modeledValue = canonicalTarget;
    out.__sourceType = '2026_rookie_proxy';
    out.__canonical = 'yes';
    return out;
  }

  function build2026RookiePickProxyValues() {
    if (!loadedData || !loadedData.players) return null;
    const cfg = getSiteConfig();
    const cfgKey = cfg.map(s => `${s.key}:${s.include ? 1 : 0}:${s.max}:${s.weight}:${s.tep === false ? 0 : 1}`).join('|');
    const key = [
      loadedData.scrapeTimestamp || loadedData.date || '',
      cfgKey,
      getLAMStrength().toFixed(3),
      getScarcityStrength().toFixed(3),
      document.getElementById('zScoreToggle')?.checked ? '1' : '0',
      document.getElementById('zFloorInput')?.value || '',
      document.getElementById('zCeilingInput')?.value || '',
      document.getElementById('flockOffsetInput')?.value || '',
      document.getElementById('flockDivisorInput')?.value || '',
      document.getElementById('flockExponentInput')?.value || '',
      document.getElementById('idpAnchorInput')?.value || '',
      document.getElementById('idpRankOffsetInput')?.value || '',
      document.getElementById('idpRankDivisorInput')?.value || '',
      document.getElementById('idpRankExponentInput')?.value || '',
      document.getElementById('tepMultiplierInput')?.value || '',
    ].join('||');
    if (rookiePickProxyCache.key === key && rookiePickProxyCache.data) return rookiePickProxyCache.data;

    const candidates = [];
    for (const [name, pData] of Object.entries(loadedData.players || {})) {
      if (parsePickToken(name)) continue;
      if (!isRookiePlayerName(name, pData)) continue;
      if (!hasAnyRankingSiteValue(pData)) continue;
      const base = computeMetaValueForPlayer(name, { rawOnly: true });
      if (!base) continue;
      const raw = Number(base.rawMarketValue ?? base.metaValue);
      if (!isFinite(raw) || raw <= 0) continue;
      const pos = (getPlayerPosition(name) || getRookiePosHint(name) || '').toUpperCase();
      const full = Number(computeFinalAdjustedValue(raw, pos, name).finalAdjustedValue || 0);
      if (!isFinite(full) || full <= 0) continue;
      candidates.push({
        name,
        pos,
        rawMarket: Math.round(raw),
        fullyAdjusted: Math.round(full),
      });
    }
    candidates.sort((a, b) => b.fullyAdjusted - a.fullyAdjusted);

    const TOTAL = 72;
    const slotValues = {};
    for (let i = 0; i < TOTAL; i++) {
      const round = Math.floor(i / 12) + 1;
      const slot = (i % 12) + 1;
      const keySlot = `${round}.${String(slot).padStart(2, '0')}`;
      let v = 0;
      if (i < candidates.length) v = Number(candidates[i].fullyAdjusted);
      if (!isFinite(v) || v <= 0) {
        const prevSlot = i > 0 ? `${Math.floor((i - 1) / 12) + 1}.${String(((i - 1) % 12) + 1).padStart(2, '0')}` : '';
        const prevVal = Number(slotValues[prevSlot] || 1200);
        v = Math.max(1, Math.round(prevVal * 0.94));
      }
      slotValues[keySlot] = Math.max(1, Math.round(v));
    }

    const tierRanges = { early: [1, 4], mid: [5, 8], late: [9, 12] };
    const tierValues = {};
    for (let round = 1; round <= 6; round++) {
      for (const [tier, [a, b]] of Object.entries(tierRanges)) {
        let sum = 0;
        let count = 0;
        for (let slot = a; slot <= b; slot++) {
          const sv = Number(slotValues[`${round}.${String(slot).padStart(2, '0')}`] || 0);
          if (!isFinite(sv) || sv <= 0) continue;
          sum += sv;
          count++;
        }
        if (count > 0) tierValues[`${round}.${tier}`] = Math.round(sum / count);
      }
    }

    const data = {
      ranked: candidates,
      slotValues,
      tierValues,
      usedCount: Math.min(TOTAL, candidates.length),
      candidateCount: candidates.length,
    };
    rookiePickProxyCache = { key, data };
    return data;
  }

  function get2026RookieProxyForPick(pickInfo) {
    if (!pickInfo) return null;
    const currentYear = parseInt(document.getElementById('pickCurrentYear')?.value) || 2026;
    const year = Number.isFinite(pickInfo.year) ? pickInfo.year : currentYear;
    if (year !== 2026) return null;
    const round = Number(pickInfo.round);
    if (!isFinite(round) || round < 1 || round > 6) return null;

    const proxy = build2026RookiePickProxyValues();
    if (!proxy) return null;

    if (pickInfo.kind === 'slot') {
      const slot = Number(pickInfo.slot);
      if (!isFinite(slot) || slot < 1 || slot > 12) return null;
      const k = `${round}.${String(slot).padStart(2, '0')}`;
      const v = Number(proxy.slotValues?.[k]);
      if (isFinite(v) && v > 0) return { value: Math.round(v), source: '2026_rookie_proxy' };
      return null;
    }

    if (pickInfo.kind === 'tier') {
      const tier = String(pickInfo.tier || 'mid').toLowerCase();
      const v = Number(proxy.tierValues?.[`${round}.${tier}`]);
      if (isFinite(v) && v > 0) return { value: Math.round(v), source: '2026_rookie_proxy' };
    }
    return null;
  }

  // ── NEW PICK RESOLUTION SYSTEM ──
  // Picks are treated like players - look them up directly in loaded data
  function resolvePickSiteValues(pickInfo) {
    if (!loadedData || !pickInfo) return null;
    const currentYear = parseInt(document.getElementById('pickCurrentYear')?.value) || 2026;
    const leagueSize = parseInt(document.getElementById('pickLeagueSize')?.value) || 12;
    const siteKeySet = new Set((sites || []).map(s => s.key));

    const yearDisc1 = parseFloat(document.getElementById('pickYearDisc1')?.value) || 0.85;
    const yearDisc2 = parseFloat(document.getElementById('pickYearDisc2')?.value) || 0.72;

    function applyYearDiscount(value, year) {
      if (!isFinite(value) || value <= 0) return null;
      const y = Number.isFinite(year) ? year : currentYear;
      const diff = y - currentYear;
      if (diff <= 0) return value;
      if (diff === 1) return value * yearDisc1;
      if (diff === 2) return value * yearDisc2;
      return value * Math.pow(yearDisc2, diff / 2);
    }

    function toNumericSiteMap(obj) {
      if (!obj || typeof obj !== 'object') return null;
      const out = {};
      for (const [k, v] of Object.entries(obj)) {
        if (!siteKeySet.has(k)) continue;
        const n = Number(v);
        if (isFinite(n) && n > 0) out[k] = Math.round(n);
      }
      return Object.keys(out).length ? out : null;
    }

    function mergeSiteMaps(...maps) {
      const out = {};
      for (const m of maps) {
        const nm = toNumericSiteMap(m);
        if (!nm) continue;
        for (const [k, v] of Object.entries(nm)) out[k] = v;
      }
      return Object.keys(out).length ? out : null;
    }

    function mergeSiteMapsPreferFirst(...maps) {
      const out = {};
      for (const m of maps) {
        const nm = toNumericSiteMap(m);
        if (!nm) continue;
        for (const [k, v] of Object.entries(nm)) {
          if (!(k in out)) out[k] = v;
        }
      }
      return Object.keys(out).length ? out : null;
    }

    // Helper: search loaded players for a pick name (fuzzy)
    function findPickData(searchTerms) {
      if (loadedData.players) {
        for (const term of searchTerms) {
          const norm = term.toLowerCase().replace(/\s+/g, ' ').trim();
          for (const [pn, pd] of Object.entries(loadedData.players)) {
            const pnorm = pn.toLowerCase().replace(/\s+/g, ' ').trim();
            if (pnorm === norm) return pd;
          }
        }
      }
      return null;
    }

    function selectByYear(entries, targetYear, matcher) {
      const matched = entries.filter(matcher);
      if (!matched.length) return [];

      const exact = matched.filter(e => Number.isFinite(e.year) && e.year === targetYear);
      if (exact.length) return exact;

      const yearless = matched.filter(e => e.year == null);
      if (yearless.length) return yearless;

      const dated = matched.filter(e => Number.isFinite(e.year));
      if (!dated.length) return [];

      let minDiff = Infinity;
      dated.forEach(e => { minDiff = Math.min(minDiff, Math.abs(e.year - targetYear)); });
      return dated.filter(e => Math.abs(e.year - targetYear) === minDiff);
    }

    function averageValues(entries) {
      if (!entries || !entries.length) return null;
      const sum = entries.reduce((acc, e) => acc + e.value, 0);
      return Math.round(sum / entries.length);
    }

    // Helper: build synthetic site data from pickAnchors for a pick/year
    function findPickFromAnchors(target) {
      if (!loadedData.pickAnchors) return null;
      const synthData = {};

      for (const [siteKey, pickMap] of Object.entries(loadedData.pickAnchors)) {
        const entries = [];
        for (const [pickName, val] of Object.entries(pickMap)) {
          const n = Number(val);
          if (!isFinite(n) || n <= 0) continue;
          const parsed = parseAnchorPickName(pickName);
          if (!parsed) continue;
          entries.push({ ...parsed, value: n });
        }

        if (!entries.length) continue;
        const targetYear = Number.isFinite(target.year) ? target.year : currentYear;
        let siteVal = null;

        if (target.kind === 'slot') {
          const direct = selectByYear(
            entries, targetYear,
            e => e.kind === 'slot' && e.round === target.round && e.slot === target.slot
          );
          siteVal = averageValues(direct);

          if (!isFinite(siteVal)) {
            const tier = pickSlotToTier(target.slot, leagueSize);
            const fromTier = selectByYear(
              entries, targetYear,
              e => e.kind === 'tier' && e.round === target.round && e.tier === tier
            );
            siteVal = averageValues(fromTier);
          }
        } else if (target.kind === 'tier') {
          const direct = selectByYear(
            entries, targetYear,
            e => e.kind === 'tier' && e.round === target.round && e.tier === target.tier
          );
          siteVal = averageValues(direct);

          if (!isFinite(siteVal)) {
            const range = pickTierSlotRange(target.tier, leagueSize);
            const fromSlots = selectByYear(
              entries, targetYear,
              e => e.kind === 'slot'
                && e.round === target.round
                && e.slot >= range.start
                && e.slot <= range.end
            );
            siteVal = averageValues(fromSlots);
          }
        }

        if (isFinite(siteVal) && siteVal > 0) synthData[siteKey] = Math.round(siteVal);
      }

      return Object.keys(synthData).length > 0 ? synthData : null;
    }

    function getKtcSlotFallback(pickKey, year) {
      const base = PICK_KTC_VALUES[pickKey];
      if (!isFinite(base) || base <= 0) return null;
      const discounted = applyYearDiscount(base, year);
      if (!isFinite(discounted) || discounted <= 0) return null;
      return { ktc: Math.round(discounted) };
    }

    function getKtcTierFallback(round, tier, year) {
      const range = pickTierSlotRange(tier, leagueSize);
      let total = 0;
      let count = 0;
      for (let s = range.start; s <= range.end; s++) {
        const key = `${round}.${String(s).padStart(2, '0')}`;
        const kv = PICK_KTC_VALUES[key];
        if (isFinite(kv) && kv > 0) {
          total += kv;
          count++;
        }
      }
      if (!count) return null;
      const baseAvg = total / count;
      const discounted = applyYearDiscount(baseAvg, year);
      if (!isFinite(discounted) || discounted <= 0) return null;
      return { ktc: Math.round(discounted) };
    }

    function averagePickSlotsFromPlayers(year, round, tier) {
      const range = pickTierSlotRange(tier, leagueSize);
      const sums = {};
      let slotCount = 0;

      for (let s = range.start; s <= range.end; s++) {
        const key = `${round}.${String(s).padStart(2, '0')}`;
        const slotData = findPickData([
          `${year} ${key}`,
          `${year} ${round}.${s}`,
          key,
          `${round}.${s}`,
        ]);
        const numeric = toNumericSiteMap(slotData);
        if (!numeric) continue;
        for (const [sk, sv] of Object.entries(numeric)) {
          sums[sk] = (sums[sk] || 0) + sv;
        }
        slotCount++;
      }

      if (!slotCount) return null;
      const out = {};
      for (const [sk, sv] of Object.entries(sums)) {
        out[sk] = Math.round(sv / slotCount);
      }
      return Object.keys(out).length ? out : null;
    }

    const ordSuffix = r => r === 1 ? 'st' : r === 2 ? 'nd' : r === 3 ? 'rd' : 'th';

    if (pickInfo.kind === 'slot') {
      // Resolution priority (real first):
      // 1) canonical loaded pick rows, 2) pickAnchors, 3) tier-fill, 4) KTC slot fallback, 5) modeled rookie proxy.
      const r = pickInfo.round;
      const s = pickInfo.slot;
      const yr = Number.isFinite(pickInfo.year) ? pickInfo.year : currentYear;
      const key = `${r}.${String(s).padStart(2, '0')}`;
      const keyShort = `${r}.${s}`;

      const playerData = findPickData([
        `${yr} ${key}`,
        `${yr} ${keyShort}`,
        `${yr} pick ${key}`,
        `${yr} round ${r} pick ${s}`,
        key,
        keyShort,
      ]);

      const anchorData = findPickFromAnchors({ kind: 'slot', year: yr, round: r, slot: s });
      const tier = pickSlotToTier(s, leagueSize);
      const tierData = resolvePickSiteValues({ kind: 'tier', year: yr, tier, round: r });
      // Prefer exact slot values; tier values should only fill missing sites.
      const merged = mergeSiteMapsPreferFirst(playerData, anchorData, tierData);
      if (merged && Object.keys(merged).length) return merged;

      const ktcFallback = getKtcSlotFallback(key, yr);
      if (ktcFallback) return ktcFallback;

      // Last resort only: modeled 2026 rookie proxy, represented as synthetic fallback.
      const rookieProxy = get2026RookieProxyForPick(pickInfo);
      if (rookieProxy && rookieProxy.value > 0) {
        return buildSyntheticPickSiteMapFromMeta(rookieProxy.value);
      }
      return null;
    }

    if (pickInfo.kind === 'tier') {
      // Resolution priority (real first):
      // 1) canonical loaded pick rows, 2) pickAnchors, 3) slot-average, 4) KTC tier fallback, 5) extrapolation, 6) modeled rookie proxy.
      const yr = Number.isFinite(pickInfo.year) ? pickInfo.year : currentYear;
      const r = pickInfo.round;
      const tier = pickInfo.tier;
      const ord = ordSuffix(r);

      const playerData = findPickData([
        `${yr} ${tier} ${r}${ord}`,
        `${yr} ${tier} round ${r}`,
        `${yr} ${r}${ord} ${tier}`,
        `${tier} ${r}${ord} ${yr}`,
        `${tier} ${r}${ord}`,
      ]);

      const anchorData = findPickFromAnchors({ kind: 'tier', year: yr, round: r, tier });
      const slotAvgData = averagePickSlotsFromPlayers(yr, r, tier);
      const merged = mergeSiteMaps(playerData, anchorData, slotAvgData);
      if (merged && Object.keys(merged).length) return merged;

      const ktcTierFallback = getKtcTierFallback(r, tier, yr);
      if (ktcTierFallback) return ktcTierFallback;

      const extrapolated = extrapolatePickRound(yr, r, tier, leagueSize);
      if (extrapolated && Object.keys(extrapolated).length) return extrapolated;

      const rookieProxy = get2026RookieProxyForPick(pickInfo);
      if (rookieProxy && rookieProxy.value > 0) {
        return buildSyntheticPickSiteMapFromMeta(rookieProxy.value);
      }
      return null;
    }
    return null;
  }

  function extrapolatePickRound(year, round, tier, leagueSize) {
    // Build a curve from known round data, then extrapolate
    if (!loadedData || !loadedData.players) return null;
    const currentYear = parseInt(document.getElementById('pickCurrentYear')?.value) || 2026;

    // Collect average composite per round for rounds we have data on
    const roundAvgs = {};
    for (let r = 1; r <= 6; r++) {
      let total = 0, count = 0;
      for (let s = 1; s <= leagueSize; s++) {
        const key = `${r}.${String(s).padStart(2, '0')}`;
        for (const [pn, pd] of Object.entries(loadedData.players)) {
          const pnorm = pn.toLowerCase().trim();
          if (pnorm === key || pnorm === `${r}.${s}` || pnorm === `${year} ${key}`) {
            // Get average of big-scale sites for this pick
            let pickTotal = 0, pickCount = 0;
            for (const [sk, sv] of Object.entries(pd)) {
              if (typeof sv === 'number' && sv > 100) {
                pickTotal += sv; pickCount++;
              }
            }
            if (pickCount > 0) {
              total += pickTotal / pickCount;
              count++;
            }
            break;
          }
        }
      }
      if (count > 0) roundAvgs[r] = total / count;
    }

    const knownRounds = Object.keys(roundAvgs).map(Number).sort((a, b) => a - b);
    if (knownRounds.length < 2) return null;

    // Fit power curve: value = A * round^B
    // Using last two known rounds to extrapolate
    const r1 = knownRounds[knownRounds.length - 2], v1 = roundAvgs[r1];
    const r2 = knownRounds[knownRounds.length - 1], v2 = roundAvgs[r2];
    if (v1 <= 0 || v2 <= 0) return null;

    const B = Math.log(v2 / v1) / Math.log(r2 / r1);
    const A = v1 / Math.pow(r1, B);

    let estimated = A * Math.pow(round, B);
    estimated = Math.max(1, estimated);

    // Clamp: extrapolated value should be 50-120% of last known round (avoid wild curves)
    const lastKnownVal = roundAvgs[knownRounds[knownRounds.length - 1]];
    if (lastKnownVal > 0) {
      estimated = Math.max(lastKnownVal * 0.3, Math.min(lastKnownVal * 1.2, estimated));
    }

    // Apply tier adjustment (early=+15%, mid=0, late=-15%)
    const tierMult = tier === 'early' ? 1.15 : tier === 'late' ? 0.85 : 1.0;
    estimated = Math.round(estimated * tierMult);

    // Build a fake site data object with estimated values proportional to each site's scale
    // Use the last known round's site breakdown as the template
    const templateRound = knownRounds[knownRounds.length - 1];
    const templateAvg = roundAvgs[templateRound];
    if (!templateAvg || templateAvg <= 0) return null;

    const ratio = estimated / templateAvg;
    // Find a sample pick from the template round
    for (let s = 1; s <= leagueSize; s++) {
      const key = `${templateRound}.${String(s).padStart(2, '0')}`;
      for (const [pn, pd] of Object.entries(loadedData.players)) {
        const pnorm = pn.toLowerCase().trim();
        if (pnorm === key || pnorm === `${templateRound}.${s}`) {
          const result = {};
          for (const [sk, sv] of Object.entries(pd)) {
            if (typeof sv === 'number' && sv > 0) {
              result[sk] = Math.max(1, Math.round(sv * ratio));
            }
          }
          return result;
        }
      }
    }
    return null;
  }


  function parsePickDollarMap(text) {
    const map = {};
    (text||'').split('\n').forEach(line => {
      const t = line.trim(); if (!t||t.startsWith('#')) return;
      const p = t.split('='); if (p.length!==2) return;
      const k = normalizePickKey(normalizeKey(p[0]).toUpperCase()), v = parseFloat(p[1]);
      if (!k||!isFinite(v)) return;
      map[k] = v;
    });
    return map;
  }

  function yearDiscount(year, s) {
    if (!year||!s.currentYear) return 1;
    const d = year - s.currentYear;
    if (d<=0) return 1;
    if (d===1) return s.yearDisc1;
    if (d===2) return s.yearDisc2;
    return Math.pow(s.yearDisc2, d/2);
  }

  function getTierSlot(tier, s) {
    return tier==='early'?s.tierEarlySlot : tier==='mid'?s.tierMidSlot : s.tierLateSlot;
  }

  function resolvePickDollars(info, map, s) {
    if (!info) return null;
    if (info.kind==='slot') {
      const k = normalizePickKey(`${info.round}.${info.slot}`);
      const d = k?map[k]:null; return isFinite(d)?d:null;
    }
    if (info.kind==='tier') {
      const base = parsePickToken(getTierSlot(info.tier, s));
      if (!base||base.kind!=='slot') return null;
      const k = normalizePickKey(`${info.round}.${base.slot}`);
      const d = k?map[k]:null; if (!isFinite(d)) return null;
      return d * yearDiscount(info.year, s);
    }
    return null;
  }
