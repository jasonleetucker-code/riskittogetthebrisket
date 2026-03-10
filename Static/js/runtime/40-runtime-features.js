/*
 * Runtime Module: 40-runtime-features.js
 * Server integration, popup/views, settings, LAM/scarcity, and advanced utilities.
 * Extracted from legacy monolithic inline runtime to keep live behavior intact.
 */

  // ── SERVER INTEGRATION ──
  let serverMode = false;  // true when served from server.py
  let embeddedDataScriptPromise = null;
  const EMBEDDED_DATA_SCRIPT_PATHS = ['../dynasty_data.js', '/dynasty_data.js', './dynasty_data.js'];
  const SERVER_STARTUP_DATA_FETCH_TIMEOUT_MS = 4500;
  const SERVER_FULL_DATA_FETCH_TIMEOUT_MS = 12000;
  let deferredFullHydrationPromise = null;
  let fullServerDataHydrated = false;

  const startupPerf = {
    marks: {},
    measures: {},
    meta: {},
  };
  window.__startupPerf = startupPerf;
  window.getStartupPerfSnapshot = () => JSON.parse(JSON.stringify(startupPerf));

  function perfNow() {
    return (window.performance && typeof window.performance.now === 'function')
      ? window.performance.now()
      : Date.now();
  }

  function perfMark(name) {
    startupPerf.marks[name] = perfNow();
  }

  function perfMeasure(name, startMark, endMark = null) {
    const start = Number(startupPerf.marks[startMark]);
    const end = endMark != null ? Number(startupPerf.marks[endMark]) : perfNow();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
    const ms = Math.round((end - start) * 100) / 100;
    startupPerf.measures[name] = ms;
    return ms;
  }

  async function fetchWithTimeout(url, options = {}, timeoutMs = 12000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error('timeout')), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  async function ensureEmbeddedDataLoaded() {
    if (window.DYNASTY_DATA && window.DYNASTY_DATA.players) return true;
    if (embeddedDataScriptPromise) return embeddedDataScriptPromise;

    embeddedDataScriptPromise = (async () => {
      for (const src of EMBEDDED_DATA_SCRIPT_PATHS) {
        const ok = await new Promise(resolve => {
          const tag = document.createElement('script');
          tag.async = true;
          tag.src = src;
          tag.onload = () => resolve(true);
          tag.onerror = () => {
            try { tag.remove(); } catch (_) {}
            resolve(false);
          };
          document.head.appendChild(tag);
        });
        if (ok && window.DYNASTY_DATA && window.DYNASTY_DATA.players) return true;
      }
      return false;
    })();

    const loaded = await embeddedDataScriptPromise;
    if (!loaded) embeddedDataScriptPromise = null;
    return loaded;
  }

  async function fetchServerDataView(view = 'app', timeoutMs = SERVER_FULL_DATA_FETCH_TIMEOUT_MS) {
    const resp = await fetchWithTimeout(`/api/data?view=${encodeURIComponent(view)}`, {
      headers: { 'Accept': 'application/json' }
    }, timeoutMs);
    if (!resp.ok) return null;
    const data = await resp.json();
    return (data && data.players) ? data : null;
  }

  function scheduleDeferredFullServerHydration() {
    if (!serverMode || fullServerDataHydrated || deferredFullHydrationPromise) {
      return deferredFullHydrationPromise || Promise.resolve(!!fullServerDataHydrated);
    }
    const run = async () => {
      try {
        perfMark('deferred_full_fetch_begin');
        const fullData = await fetchServerDataView('app', SERVER_FULL_DATA_FETCH_TIMEOUT_MS);
        perfMark('deferred_full_fetch_end');
        perfMeasure('deferred_full_fetch_ms', 'deferred_full_fetch_begin', 'deferred_full_fetch_end');
        if (!fullData) return false;
        const loaded = loadJsonData(fullData, {
          phase: 'full',
          skipTradeDraftRestore: true,
          deferWarmups: false,
          deferAnchorFill: false,
          skipSecondaryHubWarm: false,
        });
        if (loaded) {
          fullServerDataHydrated = true;
          startupPerf.meta.fullHydrated = true;
          startupPerf.meta.fullHydratedAt = Date.now();
        }
        return loaded;
      } catch (_) {
        return false;
      } finally {
        deferredFullHydrationPromise = null;
      }
    };
    deferredFullHydrationPromise = new Promise((resolve) => {
      const invoke = () => run().then(resolve);
      if (typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(invoke, { timeout: 1200 });
      } else {
        setTimeout(invoke, 120);
      }
    });
    return deferredFullHydrationPromise;
  }

  async function fetchFromServer() {
    try {
      perfMark('server_fetch_begin');
      let data = await fetchServerDataView('startup', SERVER_STARTUP_DATA_FETCH_TIMEOUT_MS);
      let phase = 'startup';

      // Fallback for older servers that do not expose startup view.
      if (!data) {
        data = await fetchServerDataView('app', SERVER_FULL_DATA_FETCH_TIMEOUT_MS);
        phase = 'full';
      }
      perfMark('server_fetch_end');
      perfMeasure('server_fetch_ms', 'server_fetch_begin', 'server_fetch_end');

      if (data && data.players) {
        const loaded = loadJsonData(data, {
          phase,
          skipTradeDraftRestore: false,
          deferWarmups: phase === 'startup',
          deferAnchorFill: phase === 'startup',
          skipSecondaryHubWarm: phase === 'startup',
        });
        if (loaded) {
          serverMode = true;
          fullServerDataHydrated = phase !== 'startup';
          startupPerf.meta.initialPayloadView = String(data.payloadView || phase || '');
          startupPerf.meta.serverMode = true;
          const btn = document.getElementById('loadDataBtn');
          if (btn) btn.textContent = fullServerDataHydrated ? '✓ Live' : '✓ Live (startup)';
          updateServerStatus();
          if (!fullServerDataHydrated) {
            scheduleDeferredFullServerHydration();
          }
          return true;
        }
      }
    } catch(e) {
      // Not running on server — standalone mode, no problem
    }
    return false;
  }

  async function updateServerStatus() {
    if (!serverMode) return;
    try {
      const resp = await fetch('/api/status');
      if (!resp.ok) return;
      const s = await resp.json();
      const st = document.getElementById('dataStatus');
      if (!st) return;
      let txt = `✓ ${s.player_count} players`;
      if (s.data_date) txt += ` · updated ${s.data_date}`;
      if (s.is_running) txt += ' · 🔄 updating now...';
      else if (s.next_scrape) {
        const next = new Date(s.next_scrape);
        const hrs = Math.max(0, (next - Date.now()) / 3600000);
        txt += ` · next update in ${hrs.toFixed(1)}h`;
      }
      if (s.last_error) txt += ' · ⚠ last update had issues';
      st.textContent = txt;
      st.style.color = s.is_running ? 'var(--amber)' : 'var(--green)';
    } catch(e) {}
  }

  async function triggerScrape() {
    if (!serverMode) return;
    try {
      const resp = await fetch('/api/scrape', { method: 'POST' });
      const data = await resp.json();
      if (resp.ok) {
        const st = document.getElementById('dataStatus');
        if (st) { st.textContent = '🔄 Refreshing values...'; st.style.color = 'var(--amber)'; }
        // Poll for completion
        const poll = setInterval(async () => {
          await updateServerStatus();
          try {
            const sr = await fetch('/api/status');
            const ss = await sr.json();
            if (!ss.is_running) {
              clearInterval(poll);
              // Reload data
              await fetchFromServer();
              recalculate();
            }
          } catch(e) { clearInterval(poll); }
        }, 5000);
      } else {
        alert(data.error || 'Refresh failed to start');
      }
    } catch(e) {
      alert('Could not reach the server');
    }
  }

  // ── PLAYER DETAIL POPUP ──
  function openPlayerPopup(playerName) {
    const overlay = document.getElementById('playerPopup');
    const content = document.getElementById('playerPopupContent');
    if (!overlay || !content || !loadedData) return;

    const result = computeMetaValueForPlayer(playerName, { rawOnly: true });
    if (!result) { content.innerHTML = '<p>No data available.</p>'; overlay.classList.add('active'); return; }
    addRecentPlayer(playerName);

    const posMap = loadedData.sleeper?.positions || {};
    let pos = (posMap[playerName] || '').toUpperCase();
    if (!pos) pos = getRookiePosHint(playerName);
    const isRookie = isRookiePlayerName(playerName, loadedData.players?.[playerName]);
    const posStyle = getPosStyle(pos);
    const popupRaw = clampValue(Math.round(Number(result.rawMarketValue ?? result.metaValue) || 0), 1, COMPOSITE_SCALE);
    const adjustmentInfo = computeFinalAdjustedValue(popupRaw, pos, playerName);

    // Build site breakdown bars
    const cfg = getSiteConfig().filter(s => s.include);
    let siteBars = '';
    const siteVals = [];
    cfg.forEach(sc => {
      const site = sites.find(x => x.key === sc.key);
      const raw = result.siteDetails[sc.key];
      if (raw == null) {
        siteBars += `<div class="pp-site-row stale-site"><span class="pp-site-label">${site?.label||sc.key}</span><span class="pp-site-bar-wrap"><div class="pp-site-bar" style="width:0;"></div></span><span class="pp-site-val">—</span></div>`;
        return;
      }
      siteVals.push({ label: site?.label || sc.key, raw, max: sc.max || 9999 });
    });

    // Normalize to percentage of highest raw value
    const maxRaw = Math.max(...siteVals.map(s => s.raw), 1);
    siteVals.forEach(sv => {
      const pct = Math.round((sv.raw / maxRaw) * 100);
      const color = sv.raw >= maxRaw * 0.9 ? 'var(--green)' : sv.raw <= maxRaw * 0.5 ? 'var(--red)' : 'var(--cyan)';
      siteBars += `<div class="pp-site-row"><span class="pp-site-label">${sv.label}</span><span class="pp-site-bar-wrap"><div class="pp-site-bar" style="width:${pct}%;background:${color};"></div></span><span class="pp-site-val">${typeof sv.raw === 'number' ? sv.raw.toLocaleString() : sv.raw}</span></div>`;
    });

    // Generate narrative
    const highSites = siteVals.filter(s => s.raw >= maxRaw * 0.9).map(s => s.label);
    const lowSites = siteVals.filter(s => s.raw <= maxRaw * 0.5).map(s => s.label);
    let narrative = '';
    if (siteVals.length >= 3) {
      if (result.cv < 0.15) {
        narrative = `Strong consensus across ${siteVals.length} sources. Sites agree closely on this valuation.`;
      } else if (result.cv < 0.30) {
        narrative = `Moderate agreement across ${siteVals.length} sources.`;
        if (highSites.length) narrative += ` Valued highest by ${highSites.join(', ')}.`;
        if (lowSites.length) narrative += ` Lowest on ${lowSites.join(', ')}.`;
      } else {
        narrative = `Sites disagree significantly (CV: ${(result.cv * 100).toFixed(0)}%).`;
        if (highSites.length) narrative += ` ${highSites.join(', ')} bullish.`;
        if (lowSites.length) narrative += ` ${lowSites.join(', ')} bearish.`;
        narrative += ' Trade value is uncertain — use this to your advantage.';
      }
    } else if (siteVals.length === 1) {
      narrative = `Only found on 1 source — value is speculative. 15% confidence discount applied.`;
    } else {
      narrative = `Limited data (${siteVals.length} sources). Value may be less reliable.`;
    }

    // Market edge
    let edgeHtml = '';
    if (loadedData) {
      const edge = getPlayerEdge(playerName);
      if (edge && Math.abs(edge.edgePct) >= MIN_EDGE_PCT && (edge.signal === 'BUY' || edge.signal === 'SELL')) {
        const label = edge.signal;
        const color = label === 'SELL' ? 'var(--red)' : 'var(--green)';
        const sign = edge.edgePct > 0 ? '+' : '';
        const src = edge.externalSource || 'Market';
        edgeHtml = `<div style="margin-top:8px;font-size:0.82rem;"><span style="font-weight:700;color:${color};">${label}</span> <span style="font-family:var(--mono);">${src} ${sign}${edge.edgePct.toFixed(1)}% vs projected curve</span></div>`;
      }
    }

    // Trade proposals
    let proposalHtml = '';
    const myTeamName = document.getElementById('rosterMyTeam')?.value;
    if (myTeamName) {
      const pkgs = generateTradePackages(playerName);
      if (pkgs.length) {
        proposalHtml = '<div class="pp-proposals"><h4>Trade packages from your roster:</h4>';
        pkgs.forEach(pkg => {
          const names = pkg.players.join(' + ');
          const basis = Math.max(1, Number(adjustmentInfo.finalAdjustedValue || result.metaValue));
          const diff = ((pkg.total - basis) / basis * 100);
          const diffStr = diff >= 0 ? `+${diff.toFixed(1)}%` : `${diff.toFixed(1)}%`;
          proposalHtml += `<div class="pp-pkg" onclick="closePlayerPopup()">${names} <span style="color:var(--subtext);font-size:0.66rem;">(${pkg.total.toLocaleString()} · ${diffStr})</span></div>`;
        });
        proposalHtml += '</div>';
      }
    }

    content.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
        <h2>${playerName}</h2>
        <span class="ac-pos" style="${posStyle}">${pos || '?'}</span>
        ${isRookie ? '<span style="font-size:0.6rem;background:var(--amber);color:#000;padding:2px 6px;border-radius:4px;font-weight:700;">ROOKIE</span>' : ''}
      </div>
      <div class="mobile-row-actions" style="margin:4px 0 10px;">
        <button class="mobile-chip-btn primary" onclick="addAssetToTrade('B','${playerName.replace(/'/g,"\\'")}');closePlayerPopup()">Add to Trade</button>
        <button class="mobile-chip-btn" onclick="addCompareCandidate('${playerName.replace(/'/g,"\\'")}');closePlayerPopup()">Compare</button>
        <button class="mobile-chip-btn" onclick="shareAssetFromPopup('${playerName.replace(/'/g,"\\'")}')">Share</button>
      </div>
      <div class="pp-composite">${adjustmentInfo.finalAdjustedValue.toLocaleString()}</div>
      ${adjustmentInfo ? `
        <div style="font-size:0.75rem;font-family:var(--mono);margin-top:-8px;margin-bottom:12px;color:var(--subtext);display:flex;flex-wrap:wrap;gap:10px;row-gap:4px;">
          <span>Raw ${adjustmentInfo.rawMarketValue.toLocaleString()}</span>
          <span title="raw ${Number(adjustmentInfo.scoring.rawLeagueMultiplier || 1).toFixed(3)} · shrunk ${Number(adjustmentInfo.scoring.shrunkLeagueMultiplier || 1).toFixed(3)} · strength ${Number(adjustmentInfo.scoring.adjustmentStrength || 0).toFixed(2)}">Scoring ${Number(adjustmentInfo.scoring.effectiveMultiplier || 1).toFixed(3)}</span>
          <span style="color:var(--green);font-weight:700;">Final ${adjustmentInfo.finalAdjustedValue.toLocaleString()}</span>
          <span style="color:${adjustmentInfo.valueDelta > 0 ? 'var(--green)' : adjustmentInfo.valueDelta < 0 ? 'var(--red)' : 'var(--subtext)'};">Δ ${adjustmentInfo.valueDelta > 0 ? '+' : ''}${adjustmentInfo.valueDelta.toLocaleString()}</span>
        </div>
      ` : ''}
      ${edgeHtml}
      <div style="margin-top:12px;">${siteBars}</div>
      <div class="pp-narrative">${narrative}</div>
      ${proposalHtml}
    `;
    overlay.classList.add('active');
  }

  function closePlayerPopup() {
    document.getElementById('playerPopup')?.classList.remove('active');
  }

  function shareAssetFromPopup(playerName) {
    const result = computeMetaValueForPlayer(playerName);
    const val = result?.metaValue && isFinite(result.metaValue) ? Math.round(result.metaValue).toLocaleString() : '—';
    const pos = parsePickToken(playerName) ? 'PICK' : (getPlayerPosition(playerName) || '?');
    const txt = `${playerName} (${pos}) · Value ${val}`;
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(txt).catch(() => {});
    }
  }

  // Close on Escape
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePlayerPopup(); });

  // ── EDGE TAB GATE ──
  function checkEdgeGate() {
    const gate = document.getElementById('edgeGate');
    const content = document.getElementById('edgeContent');
    const myTeam = document.getElementById('rosterMyTeam')?.value;
    if (gate && content) {
      if (myTeam) {
        gate.style.display = 'none';
        content.style.display = '';
      } else {
        gate.style.display = '';
        content.style.display = 'none';
      }
    }
  }

  // ── CONTENDER / REBUILDER SCORING ──
  function scoreTeamWindow(team) {
    if (!loadedData || !loadedData.players) return { score: 0, label: 'Unknown', tier: 'middle' };
    const posMap = loadedData.sleeper?.positions || {};
    let totalValue = 0, topPlayers = [], pickValue = 0;
    const teamPlayers = Array.isArray(team.players) ? team.players : [];
    const teamPicks = Array.isArray(team.picks) ? team.picks : [];
    const hasExplicitPicks = teamPicks.length > 0;

    teamPlayers.forEach(p => {
      const result = computeMetaValueForPlayer(p);
      if (!result) return;
      const val = result.metaValue;
      totalValue += val;
      const pos = (posMap[p] || '').toUpperCase();
      if (['QB', 'RB', 'WR', 'TE'].includes(pos)) {
        topPlayers.push(val);
      }
      // Backward-compat for payloads with picks inside players[].
      if (!hasExplicitPicks && parsePickToken && parsePickToken(p)) {
        pickValue += val;
      }
    });

    if (hasExplicitPicks) {
      teamPicks.forEach(pickName => {
        const result = computeMetaValueForPlayer(pickName);
        if (!result) return;
        const val = result.metaValue;
        totalValue += val;
        pickValue += val;
      });
    }

    topPlayers.sort((a, b) => b - a);
    // Starter value = top 10 offensive players (QB, 2RB, 3WR, TE, 3FLEX)
    const starterValue = topPlayers.slice(0, 10).reduce((s, v) => s + v, 0);
    // Depth = total - starters
    const depthValue = totalValue - starterValue;

    // Score: starters weighted heavily, picks weighted as rebuild signal
    const score = starterValue * 0.7 + depthValue * 0.2 + (pickValue > 0 ? -pickValue * 0.1 : 0);

    return { score, totalValue, starterValue, depthValue, pickValue };
  }

  function getTeamTier(teams) {
    // Score all teams, return tiers
    const scored = teams.map(t => ({ ...t, ...scoreTeamWindow(t) }));
    scored.sort((a, b) => b.score - a.score);
    const top = Math.ceil(teams.length / 3);
    const bot = teams.length - top;
    return scored.map((t, i) => ({
      ...t,
      tier: i < top ? 'contender' : i >= bot ? 'rebuilder' : 'middle',
      tierLabel: i < top ? 'Contender' : i >= bot ? 'Rebuilder' : 'Mid-Tier',
      rank: i + 1,
    }));
  }

  // ── SETTINGS LOCK FOR SHARED MODE ──
  const SHARED_MODE = new URLSearchParams(window.location.search).has('shared');
  if (SHARED_MODE) {
    // Hide settings tab
    document.addEventListener('DOMContentLoaded', () => {
      const settingsBtn = document.querySelector('[data-tab="settings"]');
      if (settingsBtn) settingsBtn.style.display = 'none';
    });
  }

  // ── LEAGUE ADJUSTMENT MULTIPLIER (LAM) ──
  // Computes how your league's scoring shifts positional value vs standard PPR
  // Baseline: PPR (1.0/rec), 4pt passing TD, 1pt/25yd passing, standard IDP Big 3
  const LAM_CAP = 0.25; // max ±25% adjustment
  const LAM_MIN_MULT = 1 - LAM_CAP;
  const LAM_MAX_MULT = 1 + LAM_CAP;
  const SCARCITY_ENABLED = true; // bounded scarcity layer is active in final valuation
  const SCARCITY_CAP = 0.16; // max ±16% scarcity adjustment before strength/confidence damping
  const SCARCITY_MIN_MULT = 1 - SCARCITY_CAP;
  const SCARCITY_MAX_MULT = 1 + SCARCITY_CAP;
  const SCARCITY_SENSITIVITY = 0.70;
  const FULL_ADJ_MIN_MULT = 0.70;
  const FULL_ADJ_MAX_MULT = 1.35;
  const MARKET_CONF_MIN = 0.20;
  const MARKET_CONF_MAX = 1.00;
  // User preference: if IDP Trade Calculator has a value, treat as high-confidence baseline.
  const IDP_CONF_FLOOR_WITH_IDP_TC = 0.74;
  const OFF_SCORING_DEVIATION_CAP = 0.16;
  const IDP_SCORING_DEVIATION_CAP = 0.10;
  const OFF_SCARCITY_SHIFT_CAP = 0.12;
  const IDP_SCARCITY_SHIFT_CAP = 0.08;
  const ELITE_RAW_THRESHOLD = 8500;
  const HIGH_TIER_RAW_THRESHOLD = 7000;
  const MID_TIER_RAW_THRESHOLD = 5000;

  function computeLAM(scoringSettings, rosterPositions) {
    if (!scoringSettings || !Object.keys(scoringSettings).length) return null;

    const s = scoringSettings;

    // ── BASELINE: Standard PPR + 4pt pass TD + 1pt/25yd ──
    const BASE = {
      rec: 1.0, pass_yd: 0.04, pass_td: 4, pass_int: -2, rush_yd: 0.1,
      rush_td: 6, rec_yd: 0.1, rec_td: 6, bonus_rec_te: 0.5, // TEP baseline
      pass_cmp: 0, pass_inc: 0, pass_sacked: 0, rush_att: 0,
      fum_lost: -2, bonus_fd_rb: 0, bonus_fd_wr: 0, bonus_fd_te: 0, bonus_fd_qb: 0,
      // IDP baseline (Big 3)
      idp_solo: 1.0, idp_assist: 0.5, idp_sack: 4.0, idp_int: 3.0,
      idp_ff: 2.0, idp_fr: 2.0, idp_tfl: 1.5, idp_pd: 1.0,
      idp_qb_hit: 0.5, idp_td: 6.0, idp_sack_yd: 0,
    };

    // ── YOUR LEAGUE ──
    const LEAGUE = {
      rec: s.rec ?? BASE.rec,
      pass_yd: s.pass_yd ?? BASE.pass_yd,
      pass_td: s.pass_td ?? BASE.pass_td,
      pass_int: s.pass_int ?? BASE.pass_int,
      rush_yd: s.rush_yd ?? BASE.rush_yd,
      rush_td: s.rush_td ?? BASE.rush_td,
      rec_yd: s.rec_yd ?? BASE.rec_yd,
      rec_td: s.rec_td ?? BASE.rec_td,
      bonus_rec_te: s.bonus_rec_te ?? 0,
      pass_cmp: s.pass_cmp ?? 0,
      pass_inc: s.pass_inc ?? 0,
      pass_sacked: s.pass_sacked ?? 0,
      rush_att: s.rush_att ?? 0,
      fum_lost: s.fum_lost ?? BASE.fum_lost,
      bonus_fd_rb: s.bonus_rush_fd ?? s.bonus_fd_rb ?? 0,
      bonus_fd_wr: s.bonus_rec_fd ?? s.bonus_fd_wr ?? 0,
      bonus_fd_te: s.bonus_rec_fd_te ?? s.bonus_fd_te ?? 0,
      bonus_fd_qb: s.bonus_pass_fd ?? s.bonus_fd_qb ?? 0,
      // Tiered reception bonuses
      rec_0_4: s.bonus_rec_yd_0_4 ?? s.rec_0_4 ?? 0,
      rec_5_9: s.bonus_rec_yd_5_9 ?? s.rec_5_9 ?? 0,
      rec_10_19: s.bonus_rec_yd_10_19 ?? s.rec_10_19 ?? 0,
      rec_20_29: s.bonus_rec_yd_20_29 ?? s.rec_20_29 ?? 0,
      rec_30_39: s.bonus_rec_yd_30_39 ?? s.rec_30_39 ?? 0,
      rec_40p: s.bonus_rec_yd_40p ?? s.rec_40p ?? 0,
      // IDP
      // Prefer Sleeper's idp_tkl_* / idp_fum_rec keys first, then legacy aliases.
      idp_solo: s.idp_tkl_solo ?? s.idp_solo ?? s.tkl_solo ?? BASE.idp_solo,
      idp_assist: s.idp_tkl_ast ?? s.idp_ast ?? s.idp_assist ?? s.tkl_ast ?? BASE.idp_assist,
      idp_sack: s.idp_sack ?? s.sack ?? BASE.idp_sack,
      idp_int: s.idp_int ?? s['int'] ?? BASE.idp_int,
      idp_ff: s.idp_ff ?? s.ff ?? BASE.idp_ff,
      idp_fr: s.idp_fum_rec ?? s.idp_fr ?? s.fum_rec ?? BASE.idp_fr,
      idp_tfl: s.idp_tkl_loss ?? s.idp_tfl ?? s.tkl_loss ?? BASE.idp_tfl,
      idp_pd: s.idp_pass_def ?? s.idp_pd ?? s.pass_def ?? BASE.idp_pd,
      idp_qb_hit: s.idp_qb_hit ?? s.qb_hit ?? BASE.idp_qb_hit,
      idp_td: s.idp_def_td ?? s.idp_td ?? s.def_td ?? BASE.idp_td,
      idp_sack_yd: s.idp_sack_yd ?? s.sack_yd ?? 0,
    };

    // ── Estimate avg per-game stats by position archetype ──
    // Typical starter stat lines (per game)
    const archetypes = {
      QB: { pass_att: 34, pass_cmp: 22, pass_yd: 250, pass_td: 1.75, pass_int: 0.6,
            rush_att: 3, rush_yd: 15, rush_td: 0.15, sacked: 1.8, first_downs_pass: 3 },
      RB: { rush_att: 16, rush_yd: 70, rush_td: 0.5, rec: 3.2, rec_yd: 25, rec_td: 0.12,
            avg_rec_yd: 7.8, first_downs: 5 },
      WR: { rec: 5.5, rec_yd: 65, rec_td: 0.38, rush_att: 0.3, rush_yd: 3, avg_rec_yd: 11.8,
            first_downs: 3.5 },
      TE: { rec: 3.8, rec_yd: 40, rec_td: 0.25, avg_rec_yd: 10.5, first_downs: 2.5 },
      LB: { solo: 4.5, assist: 3.0, sack: 0.15, tfl: 0.4, ff: 0.05, fr: 0.03, pd: 0.2,
            qb_hit: 0.1, int_: 0.03, td: 0.01 },
      DL: { solo: 2.0, assist: 1.5, sack: 0.35, tfl: 0.5, ff: 0.08, fr: 0.04, pd: 0.15,
            qb_hit: 0.5, int_: 0.01, td: 0.01 },
      DB: { solo: 3.0, assist: 1.5, sack: 0.02, tfl: 0.15, ff: 0.04, fr: 0.02, pd: 0.8,
            qb_hit: 0.01, int_: 0.08, td: 0.02 },
    };

    // Compute tiered reception bonus average for a given avg yards per catch
    function tieredBonus(avgYards, L) {
      // Distribute receptions across yardage buckets based on avg
      // Simplified: weight toward the bucket containing the average
      if (avgYards <= 4) return L.rec_0_4;
      if (avgYards <= 9) return L.rec_0_4 * 0.15 + L.rec_5_9 * 0.6 + L.rec_10_19 * 0.25;
      if (avgYards <= 14) return L.rec_5_9 * 0.15 + L.rec_10_19 * 0.55 + L.rec_20_29 * 0.2 + L.rec_30_39 * 0.1;
      if (avgYards <= 19) return L.rec_10_19 * 0.3 + L.rec_20_29 * 0.35 + L.rec_30_39 * 0.2 + L.rec_40p * 0.15;
      return L.rec_20_29 * 0.2 + L.rec_30_39 * 0.3 + L.rec_40p * 0.5;
    }

    function scoreOffense(pos, settings) {
      const a = archetypes[pos];
      if (!a) return 0;
      let pts = 0;

      if (pos === 'QB') {
        pts += a.pass_yd * settings.pass_yd;
        pts += a.pass_td * settings.pass_td;
        pts += a.pass_int * settings.pass_int;
        pts += a.pass_cmp * (settings.pass_cmp || 0);
        pts += (a.pass_att - a.pass_cmp) * (settings.pass_inc || 0);
        pts += a.sacked * (settings.pass_sacked || 0);
        pts += a.rush_att * (settings.rush_att || 0);
        pts += a.rush_yd * settings.rush_yd;
        pts += a.rush_td * settings.rush_td;
        pts += a.first_downs_pass * (settings.bonus_fd_qb || 0);
      } else if (pos === 'RB') {
        pts += a.rush_att * (settings.rush_att || 0);
        pts += a.rush_yd * settings.rush_yd;
        pts += a.rush_td * settings.rush_td;
        pts += a.rec * (settings.rec || 0);
        pts += a.rec * tieredBonus(a.avg_rec_yd, settings);
        pts += a.rec_yd * settings.rec_yd;
        pts += a.rec_td * settings.rec_td;
        pts += a.first_downs * (settings.bonus_fd_rb || 0);
      } else if (pos === 'WR') {
        pts += a.rec * (settings.rec || 0);
        pts += a.rec * tieredBonus(a.avg_rec_yd, settings);
        pts += a.rec_yd * settings.rec_yd;
        pts += a.rec_td * settings.rec_td;
        pts += a.rush_att * (settings.rush_att || 0);
        pts += a.rush_yd * settings.rush_yd;
        pts += a.first_downs * (settings.bonus_fd_wr || 0);
      } else if (pos === 'TE') {
        pts += a.rec * ((settings.rec || 0) + (settings.bonus_rec_te || 0));
        pts += a.rec * tieredBonus(a.avg_rec_yd, settings);
        pts += a.rec_yd * settings.rec_yd;
        pts += a.rec_td * settings.rec_td;
        pts += a.first_downs * (settings.bonus_fd_te || 0);
      }
      return pts;
    }

    function scoreIDP(pos, settings) {
      const a = archetypes[pos];
      if (!a) return 0;
      return a.solo * settings.idp_solo + a.assist * settings.idp_assist +
             a.sack * settings.idp_sack + a.tfl * settings.idp_tfl +
             a.ff * settings.idp_ff + a.fr * settings.idp_fr +
             a.pd * settings.idp_pd + a.qb_hit * settings.idp_qb_hit +
             a.int_ * settings.idp_int + a.td * settings.idp_td;
    }

    // Convert BASE to same structure for tiered bonus calculation
    const BASE_WITH_TIERS = { ...BASE, rec_0_4:0, rec_5_9:0, rec_10_19:0, rec_20_29:0, rec_30_39:0, rec_40p:0 };

    const multipliers = {};
    ['QB', 'RB', 'WR', 'TE'].forEach(pos => {
      const basePts = scoreOffense(pos, BASE_WITH_TIERS);
      const leaguePts = scoreOffense(pos, LEAGUE);
      const raw = basePts > 0 ? leaguePts / basePts : 1;
      multipliers[pos] = Math.max(1 - LAM_CAP, Math.min(1 + LAM_CAP, raw));
    });

    ['LB', 'DL', 'DB'].forEach(pos => {
      const basePts = scoreIDP(pos, BASE);
      const leaguePts = scoreIDP(pos, LEAGUE);
      const raw = basePts > 0 ? leaguePts / basePts : 1;
      multipliers[pos] = Math.max(1 - LAM_CAP, Math.min(1 + LAM_CAP, raw));
    });

    // Map sub-positions to main groups
    multipliers['EDGE'] = multipliers['DL'];
    multipliers['DE'] = multipliers['DL'];
    multipliers['DT'] = multipliers['DL'];
    multipliers['CB'] = multipliers['DB'];
    multipliers['S'] = multipliers['DB'];

    return multipliers;
  }

  // Global LAM cache
  let lamMultipliers = null;
  let lamPositionDebug = {};

  function getLAMBucket(position) {
    const p = (position || '').toUpperCase();
    if (['DE','DT','EDGE','NT'].includes(p)) return 'DL';
    if (['CB','S','FS','SS'].includes(p)) return 'DB';
    if (['OLB','ILB'].includes(p)) return 'LB';
    return p;
  }

  function clampValue(n, lo, hi) {
    const v = Number(n);
    if (!Number.isFinite(v)) return lo;
    return Math.max(lo, Math.min(hi, v));
  }

  function getAssetClass(position, playerName = '') {
    if (parsePickToken(playerName) || String(position || '').toUpperCase() === 'PICK') return 'pick';
    const p = String(position || '').toUpperCase();
    if (IDP_POSITIONS.has(p)) return 'idp';
    return 'offense';
  }

  function tierDampenForAsset(rawValue, assetClass) {
    const raw = Math.max(1, Number(rawValue) || 1);
    let damp = 1.0;
    if (raw >= ELITE_RAW_THRESHOLD) damp = 0.45;
    else if (raw >= HIGH_TIER_RAW_THRESHOLD) damp = 0.65;
    else if (raw >= MID_TIER_RAW_THRESHOLD) damp = 0.82;
    if (assetClass === 'idp') damp *= 0.90;
    if (assetClass === 'pick') damp = 0.0;
    return clampValue(damp, 0, 1);
  }

  function directionalGuardrailCaps(rawValue, assetClass, reliabilityScore) {
    const raw = Math.max(1, Number(rawValue) || 1);
    const rel = clampValue(reliabilityScore, MARKET_CONF_MIN, MARKET_CONF_MAX);
    let upCap = assetClass === 'idp' ? 0.10 : 0.16;
    let downCap = assetClass === 'idp' ? 0.14 : 0.20;

    if (raw >= ELITE_RAW_THRESHOLD) {
      upCap *= 0.40;
      downCap *= 0.55;
    } else if (raw >= HIGH_TIER_RAW_THRESHOLD) {
      upCap *= 0.60;
      downCap *= 0.75;
    } else if (raw >= MID_TIER_RAW_THRESHOLD) {
      upCap *= 0.82;
      downCap *= 0.88;
    }

    // Lower confidence means tighter upside and tighter downside movement.
    upCap *= (0.65 + (0.35 * rel));
    downCap *= (0.70 + (0.30 * rel));

    if (assetClass === 'pick') {
      upCap = 0;
      downCap = 0;
    }

    return {
      upCap: Math.max(0, upCap),
      downCap: Math.max(0, downCap),
    };
  }

  function computeMarketReliability(rawComposite, position, playerName = '', context = {}) {
    const assetClass = context.assetClass || getAssetClass(position, playerName);
    const pData = playerName ? getPlayerDataByName(playerName) : null;
    const explicit = Number(pData?._marketConfidence);
    const siteCountRaw = Math.max(
      0,
      Number(context.siteCount ?? pData?._sites ?? pData?._marketSourceCount ?? 0) || 0
    );
    const idpSourceKeys = ['idpTradeCalc', 'pffIdp', 'fantasyProsIdp'];
    const idpSiteCount = idpSourceKeys.reduce((n, k) => {
      const v = Number((context.siteDetails || {})[k] ?? pData?.[k]);
      return n + ((Number.isFinite(v) && v > 0) ? 1 : 0);
    }, 0);
    const hasIdpTradeCalc = (() => {
      const v = Number((context.siteDetails || {}).idpTradeCalc ?? pData?.idpTradeCalc);
      return Number.isFinite(v) && v > 0;
    })();
    const siteCount = assetClass === 'idp'
      ? Math.max(0, idpSiteCount || Math.min(siteCountRaw, 3))
      : siteCountRaw;
    const cv = Number(context.cv ?? pData?._marketDispersionCV);
    const hasFallback = !!(context.isFallbackOnly ?? pData?._fallbackValue);
    const expectedSites = assetClass === 'idp' ? 3 : assetClass === 'pick' ? 2 : 8;
    const siteScore = clampValue(siteCount / Math.max(1, expectedSites), 0.20, 1.00);
    const cvScore = Number.isFinite(cv)
      ? clampValue(1 - (Math.abs(cv) / 0.35), 0.20, 1.00)
      : 0.55;

    let score;
    if (Number.isFinite(explicit) && explicit > 0) {
      score = (clampValue(explicit, MARKET_CONF_MIN, MARKET_CONF_MAX) * 0.70)
            + (siteScore * 0.20)
            + (cvScore * 0.10);
    } else {
      score = (siteScore * 0.60) + (cvScore * 0.40);
    }

    if (assetClass === 'pick') score = Math.max(score, 0.70);
    if (hasFallback) score -= 0.15;
    score = clampValue(score, MARKET_CONF_MIN, MARKET_CONF_MAX);
    if (assetClass === 'idp' && hasIdpTradeCalc) {
      score = Math.max(score, IDP_CONF_FLOOR_WITH_IDP_TC);
    }

    return {
      assetClass,
      score,
      label: score >= 0.72 ? 'HIGH' : (score >= 0.52 ? 'MED' : 'LOW'),
      siteCount,
      idpSiteCount: assetClass === 'idp' ? idpSiteCount : null,
      hasIdpTradeCalc: assetClass === 'idp' ? hasIdpTradeCalc : false,
      cv: Number.isFinite(cv) ? cv : null,
      hasFallback,
      expectedSites,
    };
  }

  function getLAMStrength() {
    const v = parseFloat(document.getElementById('lamStrengthInput')?.value);
    if (!isFinite(v)) return 1.0;
    return Math.max(0, Math.min(1, v));
  }

  function normalizeValueBasis(value) {
    const v = String(value || '').toLowerCase();
    if (v === 'raw') return 'raw';
    if (v === 'scoring') return 'scoring';
    if (v === 'scarcity') return 'scarcity';
    if (v === 'adjusted') return 'full';
    return 'full';
  }

  function getValueBasisLabel(mode) {
    if (mode === 'raw') return 'Raw';
    if (mode === 'scoring') return 'Scoring';
    if (mode === 'scarcity') return 'Scarcity';
    return 'Full';
  }

  function getRankingsSortBasis() {
    return normalizeValueBasis(document.getElementById('rankingsSortBasis')?.value || 'full');
  }

  function getCalculatorValueBasis() {
    const calcVal = document.getElementById('calculatorValueBasis')?.value;
    if (calcVal) return normalizeValueBasis(calcVal);
    return getRankingsSortBasis();
  }

  function updateCalculatorValueHeader() {
    const mode = getCalculatorValueBasis();
    const label = `Value (${getValueBasisLabel(mode)})`;
    const h1 = document.querySelector('#playersHeader th:last-child');
    if (h1) h1.textContent = label;
    const h2 = document.querySelector('#playersHeaderClone th:last-child');
    if (h2) h2.textContent = label;
    const h3 = document.querySelector('#playersHeaderCloneC th:last-child');
    if (h3) h3.textContent = label;
  }

  function syncValueBasisControls(mode) {
    const normalized = normalizeValueBasis(mode);
    const rankingsEl = document.getElementById('rankingsSortBasis');
    if (rankingsEl && rankingsEl.value !== normalized) rankingsEl.value = normalized;
    const calcEl = document.getElementById('calculatorValueBasis');
    if (calcEl && calcEl.value !== normalized) calcEl.value = normalized;
    updateCalculatorValueHeader();
    return normalized;
  }

  function handleValueBasisChange(mode, source = '') {
    syncValueBasisControls(mode);
    persistSettings();
    recalculate();
    buildFullRankings();
  }

  function showRankingsLAMColumns() {
    return !!document.getElementById('rankingsShowLamCols')?.checked;
  }

  function setRankingsDetailColumnsVisible(enabled, opts = {}) {
    const on = !!enabled;
    const main = document.getElementById('rankingsShowLamCols');
    if (main) main.checked = on;
    if (opts.persist !== false) persistSettings();
    if (opts.rebuild !== false) buildFullRankings();
  }

  function showRankingsSourceColumns() {
    const main = document.getElementById('rankingsShowSiteCols');
    if (main) return !!main.checked;
    const quick = document.getElementById('rankingsShowSiteColsQuick');
    return !!quick?.checked;
  }

  function syncRankingsSourceColumnToggles() {
    const main = document.getElementById('rankingsShowSiteCols');
    const quick = document.getElementById('rankingsShowSiteColsQuick');
    const on = !!main?.checked;
    if (quick) quick.checked = on;
  }

  function setRankingsSourceColumnsVisible(enabled, opts = {}) {
    const on = !!enabled;
    const main = document.getElementById('rankingsShowSiteCols');
    const quick = document.getElementById('rankingsShowSiteColsQuick');
    if (main) main.checked = on;
    if (quick) quick.checked = on;
    if (opts.persist !== false) persistSettings();
    if (opts.rebuild !== false) buildFullRankings();
    if (opts.refreshMore !== false && typeof buildMoreHub === 'function') {
      try { buildMoreHub(); } catch(_) {}
    }
  }

  function getLAM(position) {
    if (!lamMultipliers) return 1.0;
    const bucket = getLAMBucket(position);
    return lamMultipliers[bucket] || 1.0;
  }

  function getLAMPositionDebug(position) {
    const bucket = getLAMBucket(position);
    return lamPositionDebug?.[bucket] || null;
  }

  // ── LINEUP SCARCITY ADJUSTMENT ──
  let scarcityModelCache = null;
  let scarcityModelKey = '';

  function getScarcityStrength() {
    if (!SCARCITY_ENABLED) return 0;
    const v = parseFloat(document.getElementById('scarcityStrengthInput')?.value);
    if (!isFinite(v)) return 0.35;
    return Math.max(0, Math.min(1, v));
  }

  function getLeagueTeamCount() {
    const fromSettings = Number(loadedData?.sleeper?.leagueSettings?.num_teams);
    if (Number.isFinite(fromSettings) && fromSettings > 0) return fromSettings;
    if (Array.isArray(sleeperTeams) && sleeperTeams.length > 0) return sleeperTeams.length;
    return 12;
  }

  function getScarcityBucket(position) {
    const bucket = getLAMBucket(position);
    if (['QB','RB','WR','TE','DL','LB','DB'].includes(bucket)) return bucket;
    return null;
  }

  function computeStarterSlotWeights() {
    const slots = Array.isArray(loadedData?.sleeper?.rosterPositions) ? loadedData.sleeper.rosterPositions : [];
    const weights = { QB: 0, RB: 0, WR: 0, TE: 0, DL: 0, LB: 0, DB: 0 };
    if (!slots.length) return { ...weights, QB: 2, RB: 2, WR: 3, TE: 1, DL: 2, LB: 2, DB: 2 };

    const skipSlots = new Set([
      'BN','BENCH','IR','RESERVE','RES','NA','TAXI','EMPTY','K','PK','DEF','DST','DLT'
    ]);

    // First pass: explicit IDP slots for smarter IDP_FLEX allocation.
    const explicitIdp = { DL: 0, LB: 0, DB: 0 };
    slots.forEach(rawSlot => {
      const slot = String(rawSlot || '').trim().toUpperCase().replace(/\s+/g, '_');
      if (!slot || skipSlots.has(slot)) return;
      const bucket = getScarcityBucket(slot);
      if (bucket === 'DL' || bucket === 'LB' || bucket === 'DB') explicitIdp[bucket] += 1;
      if (['DE','DT','EDGE','NT'].includes(slot)) explicitIdp.DL += 1;
      if (['OLB','ILB'].includes(slot)) explicitIdp.LB += 1;
      if (['CB','S','FS','SS'].includes(slot)) explicitIdp.DB += 1;
    });
    const explicitIdpTotal = explicitIdp.DL + explicitIdp.LB + explicitIdp.DB;
    const idpFlexWeights = explicitIdpTotal > 0
      ? {
          DL: explicitIdp.DL / explicitIdpTotal,
          LB: explicitIdp.LB / explicitIdpTotal,
          DB: explicitIdp.DB / explicitIdpTotal,
        }
      : { DL: 1 / 3, LB: 1 / 3, DB: 1 / 3 };

    const flexWeights = {
      FLEX: { RB: 0.40, WR: 0.40, TE: 0.20 },
      WRRB_FLEX: { RB: 0.45, WR: 0.55 },
      RBWR_FLEX: { RB: 0.45, WR: 0.55 },
      REC_FLEX: { RB: 0.30, WR: 0.50, TE: 0.20 },
      WRTE_FLEX: { WR: 0.65, TE: 0.35 },
      TEWR_FLEX: { WR: 0.65, TE: 0.35 },
      WRT_FLEX: { RB: 0.35, WR: 0.45, TE: 0.20 },
      SUPER_FLEX: { QB: 0.70, RB: 0.15, WR: 0.10, TE: 0.05 },
      OP: { QB: 0.70, RB: 0.15, WR: 0.10, TE: 0.05 },
      IDP_FLEX: idpFlexWeights,
      IDP: idpFlexWeights,
      DL_LB_FLEX: { DL: 0.50, LB: 0.50 },
      LB_DB_FLEX: { LB: 0.50, DB: 0.50 },
      DB_DL_FLEX: { DB: 0.50, DL: 0.50 },
    };

    const addWeight = (bucket, amount) => {
      if (!bucket || !Number.isFinite(amount) || amount <= 0) return;
      if (weights[bucket] == null) return;
      weights[bucket] += amount;
    };

    slots.forEach(rawSlot => {
      const slot = String(rawSlot || '').trim().toUpperCase().replace(/\s+/g, '_');
      if (!slot || skipSlots.has(slot)) return;

      if (flexWeights[slot]) {
        Object.entries(flexWeights[slot]).forEach(([bucket, w]) => addWeight(bucket, w));
        return;
      }

      if (['DE','DT','EDGE','NT'].includes(slot)) {
        addWeight('DL', 1);
        return;
      }
      if (['OLB','ILB'].includes(slot)) {
        addWeight('LB', 1);
        return;
      }
      if (['CB','S','FS','SS'].includes(slot)) {
        addWeight('DB', 1);
        return;
      }

      const bucket = getScarcityBucket(slot);
      if (bucket) addWeight(bucket, 1);
    });

    return weights;
  }

  function getLeagueStarterRequirements() {
    const weights = computeStarterSlotWeights();
    const out = {};
    Object.entries(weights || {}).forEach(([bucket, v]) => {
      const n = Number(v);
      if (Number.isFinite(n) && n > 0) out[bucket] = Number(n.toFixed(3));
    });
    return out;
  }

  function buildScarcityModelKey() {
    if (!loadedData || !loadedData.players) return '';
    const cfg = getSiteConfig()
      .map(s => `${s.key}:${s.include ? 1 : 0}:${s.max}:${s.weight}:${s.tep ? 1 : 0}`)
      .join('|');
    const inputs = [
      document.getElementById('zScoreToggle')?.checked ? 'z1' : 'z0',
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
    ].join('|');
    const slots = JSON.stringify(loadedData?.sleeper?.rosterPositions || []);
    return [
      loadedData?.date || '',
      Object.keys(loadedData.players).length,
      getLeagueTeamCount(),
      slots,
      cfg,
      inputs,
    ].join('||');
  }

  function buildScarcityModel() {
    if (!loadedData || !loadedData.players) return null;

    const startersPerTeam = computeStarterSlotWeights();
    const teamCount = getLeagueTeamCount();
    const buckets = { QB: [], RB: [], WR: [], TE: [], DL: [], LB: [], DB: [] };

    for (const name of Object.keys(loadedData.players)) {
      if (parsePickToken(name)) continue;
      const rawResult = computeMetaValueForPlayer(name, { rawOnly: true });
      if (!rawResult || !Number.isFinite(rawResult.metaValue) || rawResult.metaValue <= 0) continue;
      let pos = getPlayerPosition(name) || '';
      if (!pos) pos = getRookiePosHint(name);
      const bucket = getScarcityBucket(pos);
      if (!bucket || !buckets[bucket]) continue;
      buckets[bucket].push(Math.round(rawResult.metaValue));
    }

    const positions = {};
    Object.entries(buckets).forEach(([bucket, values]) => {
      const sorted = values.filter(v => Number.isFinite(v) && v > 0).sort((a, b) => b - a);
      const poolSize = sorted.length;
      const startersPerTeamForPos = Number(startersPerTeam[bucket] || 0);
      const totalStarters = startersPerTeamForPos * teamCount;
      const replacementRank = poolSize > 0
        ? Math.max(1, Math.min(poolSize, Math.ceil(totalStarters > 0 ? totalStarters : 1)))
        : 0;
      const replacementValue = replacementRank > 0 ? sorted[replacementRank - 1] : 1;
      const topValue = poolSize > 0 ? sorted[0] : replacementValue;
      const span = Math.max(1, topValue - replacementValue);
      const pressure = poolSize > 0 ? Math.max(0, Math.min(1.5, totalStarters / poolSize)) : 0;

      positions[bucket] = {
        bucket,
        startersPerTeam: Number(startersPerTeamForPos.toFixed(3)),
        totalStarters: Number(totalStarters.toFixed(3)),
        poolSize,
        replacementRank,
        replacementValue: Number(replacementValue || 1),
        topValue: Number(topValue || replacementValue || 1),
        span,
        pressure: Number(pressure.toFixed(4)),
      };
    });

    return {
      teamCount,
      startersPerTeam,
      positions,
    };
  }

  function ensureScarcityModel() {
    const key = buildScarcityModelKey();
    if (!key) {
      scarcityModelCache = null;
      scarcityModelKey = '';
      return null;
    }
    if (scarcityModelCache && scarcityModelKey === key) return scarcityModelCache;
    scarcityModelCache = buildScarcityModel();
    scarcityModelKey = key;

    if (scarcityModelCache?.positions) {
      const pos = scarcityModelCache.positions;
      console.log(
        `[Scarcity] teamCount=${scarcityModelCache.teamCount} ` +
        `QB rep#${pos.QB?.replacementRank || 0}=${Math.round(pos.QB?.replacementValue || 0)} ` +
        `RB rep#${pos.RB?.replacementRank || 0}=${Math.round(pos.RB?.replacementValue || 0)} ` +
        `WR rep#${pos.WR?.replacementRank || 0}=${Math.round(pos.WR?.replacementValue || 0)} ` +
        `TE rep#${pos.TE?.replacementRank || 0}=${Math.round(pos.TE?.replacementValue || 0)} ` +
        `DL rep#${pos.DL?.replacementRank || 0}=${Math.round(pos.DL?.replacementValue || 0)} ` +
        `LB rep#${pos.LB?.replacementRank || 0}=${Math.round(pos.LB?.replacementValue || 0)} ` +
        `DB rep#${pos.DB?.replacementRank || 0}=${Math.round(pos.DB?.replacementValue || 0)}`
      );
    }
    return scarcityModelCache;
  }

  function computeScarcityAdjustedValue(rawComposite, position, playerName = '', context = {}) {
    const raw = clampValue(Math.round(Number(rawComposite) || 0), 1, COMPOSITE_SCALE);
    const bucket = getScarcityBucket(position);
    const assetClass = context.assetClass || getAssetClass(position, playerName);
    const reliability = context.marketReliability || computeMarketReliability(raw, position, playerName, context);
    const scarcityStrength = getScarcityStrength();

    if (!SCARCITY_ENABLED || !bucket || assetClass === 'pick' || scarcityStrength <= 0) {
      return {
        scarcityBucket: bucket || null,
        rawCompositeValue: raw,
        scarcityMultiplierRaw: 1.0,
        scarcityMultiplierEffective: 1.0,
        scarcityStrength: 0,
        replacementRank: 0,
        replacementValue: 0,
        valueAboveReplacement: 0,
        normalizedVor: 0,
        pressure: 0,
        finalScarcityAdjustedValue: raw,
        scarcityDelta: 0,
        starterDemand: 0,
        poolSize: 0,
        marketReliabilityScore: reliability.score,
      };
    }

    const scarcityModel = ensureScarcityModel();
    const p = scarcityModel?.positions?.[bucket];
    if (!p) {
      return {
        scarcityBucket: bucket || null,
        rawCompositeValue: raw,
        scarcityMultiplierRaw: 1.0,
        scarcityMultiplierEffective: 1.0,
        scarcityStrength,
        replacementRank: 0,
        replacementValue: 0,
        valueAboveReplacement: 0,
        normalizedVor: 0,
        pressure: 0,
        finalScarcityAdjustedValue: raw,
        scarcityDelta: 0,
        starterDemand: 0,
        poolSize: 0,
        marketReliabilityScore: reliability.score,
      };
    }

    const replacementValue = Math.max(1, Number(p.replacementValue || 1));
    const valueAboveReplacement = raw - replacementValue;
    const span = Math.max(1, Number(p.span || (Number(p.topValue || raw) - replacementValue) || 1));
    const normalizedVor = clampValue(valueAboveReplacement / span, -1.25, 1.25);
    const pressure = clampValue(Number(p.pressure || 0), 0, 1.5);
    const starterDemand = clampValue(
      Number(p.totalStarters || 0) / Math.max(1, Number(p.poolSize || 1)),
      0,
      1.6
    );
    const tierDampen = tierDampenForAsset(raw, assetClass);
    const shiftCap = assetClass === 'idp' ? IDP_SCARCITY_SHIFT_CAP : OFF_SCARCITY_SHIFT_CAP;
    const rawShift = normalizedVor * pressure * starterDemand * SCARCITY_SENSITIVITY;
    const clippedShift = clampValue(rawShift, -1, 1);
    const scarcityMultiplierRaw = clampValue(1 + (clippedShift * shiftCap), SCARCITY_MIN_MULT, SCARCITY_MAX_MULT);

    const blend = clampValue(scarcityStrength * reliability.score * tierDampen, 0, 1);
    const scarcityMultiplierEffective = clampValue(
      1 + ((scarcityMultiplierRaw - 1) * blend),
      SCARCITY_MIN_MULT,
      SCARCITY_MAX_MULT
    );
    const finalScarcityAdjustedValue = clampValue(
      Math.round(raw * scarcityMultiplierEffective),
      1,
      COMPOSITE_SCALE
    );

    return {
      scarcityBucket: bucket,
      rawCompositeValue: raw,
      scarcityMultiplierRaw,
      scarcityMultiplierEffective,
      scarcityStrength,
      replacementRank: Number(p.replacementRank || 0),
      replacementValue,
      valueAboveReplacement,
      normalizedVor,
      pressure,
      finalScarcityAdjustedValue,
      scarcityDelta: finalScarcityAdjustedValue - raw,
      starterDemand,
      poolSize: Number(p.poolSize || 0),
      marketReliabilityScore: reliability.score,
      tierDampen,
      shiftCap,
    };
  }

  function computeLeagueAdjustedValue(rawComposite, position, playerName = '', context = {}) {
    const raw = clampValue(Math.round(Number(rawComposite) || 0), 1, COMPOSITE_SCALE);
    const bucket = getLAMBucket(position);
    const assetClass = context.assetClass || getAssetClass(position, playerName);
    const marketReliability = context.marketReliability || computeMarketReliability(raw, position, playerName, context);
    const posDebug = getLAMPositionDebug(bucket) || {};
    const pData = playerName ? getPlayerDataByName(playerName) : null;

    if (assetClass === 'pick') {
      return {
        baselineBucket: bucket || 'PICK',
        rawCompositeValue: raw,
        rawLeagueMultiplier: 1,
        shrunkLeagueMultiplier: 1,
        leagueMultiplier: 1,
        adjustmentStrength: 0,
        effectiveMultiplier: 1,
        finalAdjustedValue: raw,
        valueDelta: 0,
        formatFitSource: 'pick_neutral',
        formatFitConfidence: 1,
        formatFitRaw: 1,
        formatFitShrunk: 1,
        formatFitFinal: 1,
        formatFitPPGTest: null,
        formatFitPPGCustom: null,
        formatFitProductionShare: null,
        assetClass,
        marketReliabilityScore: marketReliability.score,
        evidenceConfidence: 1,
        tierDampen: 0,
        rawDeviation: 0,
        cappedDeviation: 0,
      };
    }

    // If backend already emitted league-adjusted values, use them as the scoring
    // target and apply user strength as a clean blend. This avoids frontend
    // recompute drift and preserves archetype/format-fit movement from scraper output.
    const backendLeagueAdjusted = Number(pData?._leagueAdjusted);
    if (Number.isFinite(backendLeagueAdjusted) && backendLeagueAdjusted > 0) {
      const formatFitSource = String(pData?._formatFitSource || '');
      const formatFitConfidence = Number(pData?._formatFitConfidence);
      const formatFitRaw = Number(pData?._formatFitRaw);
      const formatFitShrunk = Number(pData?._formatFitShrunk);
      const formatFitFinal = Number(pData?._formatFitFinal);
      const formatFitPPGTest = Number(pData?._formatFitPPGTest);
      const formatFitPPGCustom = Number(pData?._formatFitPPGCustom);
      const formatFitProductionShare = Number(pData?._formatFitProductionShare);

      const backendTarget = clampValue(Math.round(backendLeagueAdjusted), 1, COMPOSITE_SCALE);
      const backendMultiplier = backendTarget / Math.max(1, raw);
      const rawDeviation = backendMultiplier - 1;
      const deviationCap = assetClass === 'idp' ? IDP_SCORING_DEVIATION_CAP : OFF_SCORING_DEVIATION_CAP;
      const cappedDeviation = clampValue(rawDeviation, -deviationCap, deviationCap);
      const adjustmentStrength = clampValue(getLAMStrength(), 0, 1);
      const evidenceConfidence = Number.isFinite(formatFitConfidence)
        ? clampValue(formatFitConfidence, MARKET_CONF_MIN, MARKET_CONF_MAX)
        : (formatFitSource ? 0.65 : 0.55);
      const tierDampen = tierDampenForAsset(raw, assetClass);

      let effectiveMultiplier = 1 + (cappedDeviation * adjustmentStrength);
      const lamMin = assetClass === 'idp' ? Math.max(0.92, LAM_MIN_MULT) : Math.max(0.85, LAM_MIN_MULT);
      const lamMax = assetClass === 'idp' ? Math.min(1.10, LAM_MAX_MULT) : Math.min(1.18, LAM_MAX_MULT);
      effectiveMultiplier = clampValue(effectiveMultiplier, lamMin, lamMax);

      const finalAdjustedValue = clampValue(
        Math.round(raw * effectiveMultiplier),
        1,
        COMPOSITE_SCALE
      );
      const valueDelta = finalAdjustedValue - raw;

      return {
        baselineBucket: bucket,
        rawCompositeValue: raw,
        rawLeagueMultiplier: Number(pData?._rawLeagueMultiplier ?? backendMultiplier) || backendMultiplier,
        shrunkLeagueMultiplier: Number(pData?._shrunkLeagueMultiplier ?? backendMultiplier) || backendMultiplier,
        leagueMultiplier: backendMultiplier,
        adjustmentStrength,
        effectiveMultiplier,
        finalAdjustedValue,
        valueDelta,
        formatFitSource,
        formatFitConfidence,
        formatFitRaw,
        formatFitShrunk,
        formatFitFinal,
        formatFitPPGTest,
        formatFitPPGCustom,
        formatFitProductionShare,
        assetClass,
        marketReliabilityScore: marketReliability.score,
        evidenceConfidence,
        tierDampen,
        rawDeviation,
        cappedDeviation,
      };
    }

    let leagueMultiplier = getLAM(bucket);
    let rawLeagueMultiplier = Number(posDebug.rawMultiplier ?? leagueMultiplier) || leagueMultiplier;
    let shrunkLeagueMultiplier = Number(posDebug.shrunkMultiplier ?? leagueMultiplier) || leagueMultiplier;

    let formatFitSource = '';
    let formatFitConfidence = null;
    let formatFitRaw = null;
    let formatFitShrunk = null;
    let formatFitFinal = null;
    let formatFitPPGTest = null;
    let formatFitPPGCustom = null;
    let formatFitProductionShare = null;

    // Prefer player-level format-fit translation if available from scraper.
    // Fallback remains position-level LAM multipliers for compatibility.
    // Prefer the model's full scoring-fit multiplier when available.
    // _formatFitProductionMultiplier is already production-dampened and can
    // make scoring mode too inert when combined with downstream dampening.
    const pMultFinal = Number(pData?._formatFitFinal);
    const pMultProduction = Number(pData?._formatFitProductionMultiplier);
    const pMult = (Number.isFinite(pMultFinal) && pMultFinal > 0) ? pMultFinal : pMultProduction;
    if (Number.isFinite(pMult) && pMult > 0) {
      leagueMultiplier = pMult;
      rawLeagueMultiplier = Number(pData?._formatFitRaw ?? rawLeagueMultiplier) || rawLeagueMultiplier;
      shrunkLeagueMultiplier = Number(pData?._formatFitShrunk ?? shrunkLeagueMultiplier) || shrunkLeagueMultiplier;
      formatFitSource = String(pData?._formatFitSource || '');
      formatFitConfidence = Number(pData?._formatFitConfidence);
      formatFitRaw = Number(pData?._formatFitRaw);
      formatFitShrunk = Number(pData?._formatFitShrunk);
      formatFitFinal = Number(pData?._formatFitFinal);
      formatFitPPGTest = Number(pData?._formatFitPPGTest);
      formatFitPPGCustom = Number(pData?._formatFitPPGCustom);
      formatFitProductionShare = Number(pData?._formatFitProductionShare);
    }

    const evidenceConfidence = Number.isFinite(formatFitConfidence)
      ? clampValue(formatFitConfidence, MARKET_CONF_MIN, MARKET_CONF_MAX)
      : (formatFitSource ? 0.65 : 0.55);
    const tierDampen = tierDampenForAsset(raw, assetClass);
    const rawDeviation = Number(leagueMultiplier || 1) - 1;
    const deviationCap = assetClass === 'idp' ? IDP_SCORING_DEVIATION_CAP : OFF_SCORING_DEVIATION_CAP;
    const cappedDeviation = clampValue(rawDeviation, -deviationCap, deviationCap);
    const adjustmentStrength = clampValue(
      getLAMStrength() * marketReliability.score * evidenceConfidence * tierDampen,
      0,
      1
    );

    let effectiveMultiplier = 1 + (cappedDeviation * adjustmentStrength);
    const lamMin = assetClass === 'idp' ? Math.max(0.92, LAM_MIN_MULT) : Math.max(0.85, LAM_MIN_MULT);
    const lamMax = assetClass === 'idp' ? Math.min(1.10, LAM_MAX_MULT) : Math.min(1.18, LAM_MAX_MULT);
    effectiveMultiplier = clampValue(effectiveMultiplier, lamMin, lamMax);

    const finalAdjustedValue = clampValue(
      Math.round(raw * effectiveMultiplier),
      1,
      COMPOSITE_SCALE
    );
    const valueDelta = finalAdjustedValue - raw;

    return {
      baselineBucket: bucket,
      rawCompositeValue: raw,
      rawLeagueMultiplier,
      shrunkLeagueMultiplier,
      leagueMultiplier,
      adjustmentStrength,
      effectiveMultiplier,
      finalAdjustedValue,
      valueDelta,
      formatFitSource,
      formatFitConfidence,
      formatFitRaw,
      formatFitShrunk,
      formatFitFinal,
      formatFitPPGTest,
      formatFitPPGCustom,
      formatFitProductionShare,
      assetClass,
      marketReliabilityScore: marketReliability.score,
      evidenceConfidence,
      tierDampen,
      rawDeviation,
      cappedDeviation,
    };
  }

  function computeFinalAdjustedValue(rawComposite, position, playerName = '', context = {}) {
    if (context?.preferPrecomputed !== false) {
      const pData = resolveLoadedPlayerDataForPrecomputed(playerName);
      if (pData && typeof pData === 'object') {
        const precomputed = getPrecomputedAdjustmentBundle(pData, rawComposite, position, playerName);
        if (precomputed) return precomputed;
      }
    }
    return computeFinalAdjustedValueCore(rawComposite, position, playerName, context);
  }

  function getValueByRankingMode(bundle, mode) {
    if (!bundle) return 0;
    if (mode === 'raw') return bundle.rawMarketValue;
    if (mode === 'scoring') return bundle.scoringAdjustedValue;
    if (mode === 'scarcity') return bundle.scarcityAdjustedValue;
    return bundle.finalAdjustedValue;
  }

  function applyLAM(composite, position) {
    return computeLeagueAdjustedValue(composite, position).finalAdjustedValue;
  }

  function initLAM() {
    const archetypeLAM = loadedData?.sleeper?.scoringSettings
      ? computeLAM(loadedData.sleeper.scoringSettings, loadedData.sleeper.rosterPositions)
      : null;

    const empirical = loadedData?.empiricalLAM || null;
    const empiricalMultipliers = empirical?.multipliers || null;
    const empiricalCount = Number(empirical?.playerCount || 0);
    const empiricalSamples = empirical?.sampleCounts || {};
    const empiricalPosDebug = empirical?.positionDebug || {};

    lamPositionDebug = {};

    if (empiricalMultipliers && empiricalCount > 0) {
      // Start from archetype model, then override positions that have empirical samples.
      lamMultipliers = archetypeLAM ? { ...archetypeLAM } : {};

      for (const [rawPos, rawMult] of Object.entries(empiricalMultipliers)) {
        const pos = getLAMBucket(String(rawPos || '').toUpperCase());
        const mult = Number(rawMult);
        if (!pos || !Number.isFinite(mult) || mult <= 0) continue;
        const samples = Number(empiricalSamples[pos] ?? empiricalCount);
        if (samples <= 0) continue;
        lamMultipliers[pos] = Math.max(LAM_MIN_MULT, Math.min(LAM_MAX_MULT, mult));
      }

      // Keep core LAM buckets to QB/RB/WR/TE/DL/LB/DB.
      // Sub-position aliases map to DL/DB for compatibility.
      if (lamMultipliers.DL) {
        lamMultipliers.EDGE = lamMultipliers.DL;
        lamMultipliers.DE = lamMultipliers.DL;
        lamMultipliers.DT = lamMultipliers.DL;
      }
      if (lamMultipliers.DB) {
        lamMultipliers.CB = lamMultipliers.DB;
        lamMultipliers.S = lamMultipliers.DB;
      }

      for (const [rawPos, dbg] of Object.entries(empiricalPosDebug || {})) {
        const pos = getLAMBucket(rawPos);
        if (!pos || !dbg || typeof dbg !== 'object') continue;
        lamPositionDebug[pos] = {
          rawMultiplier: Number(dbg.rawMultiplier ?? lamMultipliers[pos] ?? 1) || 1,
          shrunkMultiplier: Number(dbg.shrunkMultiplier ?? lamMultipliers[pos] ?? 1) || 1,
          sampleWeight: Number(dbg.sampleWeight ?? 0) || 0,
          sampleGames: Number(dbg.sampleGames ?? 0) || 0,
          playerCount: Number(dbg.playerCount ?? 0) || 0,
        };
      }

      const seasons = empirical.seasons || [];
      console.log(`[LAM] Using EMPIRICAL+ARCHETYPE blend (${empiricalCount} empirical players across ${seasons.join(', ') || 'n/a'}).`);
    } else if (archetypeLAM) {
      lamMultipliers = archetypeLAM;
      lamPositionDebug = {};
      ['QB','RB','WR','TE','DL','LB','DB'].forEach(pos => {
        const m = Number(lamMultipliers?.[pos] ?? 1) || 1;
        lamPositionDebug[pos] = {
          rawMultiplier: m,
          shrunkMultiplier: m,
          sampleWeight: 0,
          sampleGames: 0,
          playerCount: 0,
        };
      });
      if (empiricalMultipliers && empiricalCount <= 0) {
        console.log('[LAM] Empirical LAM had zero overlap; using ARCHETYPE-BASED multipliers.');
      } else {
        console.log('[LAM] Using ARCHETYPE-BASED multipliers (no empirical data available).');
      }
    } else {
      lamMultipliers = null;
      lamPositionDebug = {};
      return;
    }

    if (lamMultipliers) {
      ['QB','RB','WR','TE','DL','LB','DB'].forEach(pos => {
        const mult = Number(lamMultipliers[pos] ?? 1) || 1;
        const pct = ((mult - 1) * 100).toFixed(1);
        const dbg = lamPositionDebug[pos] || {};
        const w = Number(dbg.sampleWeight ?? 0);
        const g = Number(dbg.sampleGames ?? 0);
        console.log(`  ${pos}: ${mult.toFixed(3)} (${pct > 0 ? '+' : ''}${pct}%) sampleGames=${g} shrinkW=${w.toFixed(3)}`);
      });
    }
  }

  function initScarcity() {
    scarcityModelCache = null;
    scarcityModelKey = '';
    if (SCARCITY_ENABLED) {
      ensureScarcityModel();
    }
  }

  // ── PROFILE & ONBOARDING ──
  const PROFILE_KEY = 'dynasty_profile';
  const HARDCODED_LEAGUE_NAME_FALLBACK = 'Risk It To Get The Brisket';

  function getCanonicalLeagueIds() {
    const lam = loadedData?.settings?.lamLeagues || {};
    const profile = getProfile() || {};
    const customLeagueId = String(
      lam.customLeagueId || profile.customLeagueId || profile.leagueId || ''
    ).trim();
    const baselineLeagueId = String(
      lam.baselineLeagueId || profile.baselineLeagueId || ''
    ).trim();
    return { customLeagueId, baselineLeagueId };
  }

  function getCurrentLeagueId() {
    return getCanonicalLeagueIds().customLeagueId;
  }

  function getBaselineLeagueId() {
    return getCanonicalLeagueIds().baselineLeagueId;
  }

  function getProfile() {
    try { return JSON.parse(localStorage.getItem(PROFILE_KEY) || 'null'); }
    catch { return null; }
  }

  function saveProfile(profile) {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
    updateProfileBar();
  }

  function updateProfileBar() {
    const bar = document.getElementById('profileBar');
    const avatar = document.getElementById('profileAvatar');
    const text = document.getElementById('profileText');
    const profile = getProfile();
    if (!bar) return;

    if (profile && (profile.username || profile.leagueName)) {
      bar.style.display = 'flex';
      const idLabel = String(profile.username || profile.leagueName || '?');
      const initial = (idLabel[0] || '?').toUpperCase();
      avatar.textContent = initial;
      const parts = [];
      if (profile.leagueName) parts.push(profile.leagueName);
      else if (profile.username) parts.push(profile.username);
      if (profile.teamName) parts.push(profile.teamName);
      text.textContent = parts.join(' · ');

      // Also set the rosterMyTeam dropdown if it matches
      if (profile.teamName) {
        const preferred = resolvePreferredTeamName({
          teams: sleeperTeams,
          explicitTeam: profile.teamName,
          savedTeam: localStorage.getItem('dynasty_my_team') || '',
          profileTeam: profile.teamName,
        });
        if (preferred) syncGlobalTeam(preferred);
      }
    } else {
      bar.style.display = 'none';
    }
  }

  // Sleeper API helpers (client-side)
  async function sleeperFetchUser(username) {
    const r = await fetch(`https://api.sleeper.app/v1/user/${encodeURIComponent(username)}`);
    if (!r.ok) return null;
    return r.json();
  }

  async function sleeperFetchLeagues(userId, season) {
    const r = await fetch(`https://api.sleeper.app/v1/user/${userId}/leagues/nfl/${season}`);
    if (!r.ok) return [];
    return r.json();
  }

  async function sleeperFetchRosters(leagueId) {
    const r = await fetch(`https://api.sleeper.app/v1/league/${leagueId}/rosters`);
    if (!r.ok) return [];
    return r.json();
  }

  async function sleeperFetchUsers(leagueId) {
    const r = await fetch(`https://api.sleeper.app/v1/league/${leagueId}/users`);
    if (!r.ok) return [];
    return r.json();
  }

  async function sleeperFetchLeague(leagueId) {
    const r = await fetch(`https://api.sleeper.app/v1/league/${leagueId}`);
    if (!r.ok) return null;
    return r.json();
  }

  // Onboarding flow (configured Sleeper league from backend settings/profile)
  let onboardState = {};

  function _teamExists(teamName) {
    const name = String(teamName || '').trim();
    return !!name && Array.isArray(sleeperTeams) && sleeperTeams.some(t => t.name === name);
  }

  function ensureHardcodedLeagueProfile() {
    const existing = getProfile() || {};
    const savedTeam = localStorage.getItem('dynasty_my_team') || '';
    const ids = getCanonicalLeagueIds();
    const customLeagueId = String(
      ids.customLeagueId || existing.customLeagueId || existing.leagueId || ''
    ).trim();
    const baselineLeagueId = String(
      ids.baselineLeagueId || existing.baselineLeagueId || ''
    ).trim();
    const leagueName = String(loadedData?.sleeper?.leagueName || existing.leagueName || HARDCODED_LEAGUE_NAME_FALLBACK);

    let teamName = String(existing.teamName || savedTeam || '');
    let rosterId = existing.rosterId || '';
    if (Array.isArray(sleeperTeams) && sleeperTeams.length) {
      if (!_teamExists(teamName)) {
        teamName = resolvePreferredTeamName({
          teams: sleeperTeams,
          explicitTeam: existing.teamName,
          savedTeam,
          profileTeam: existing.teamName,
        });
      }
      const t = sleeperTeams.find(x => x.name === teamName);
      if (t) rosterId = t.rosterId ?? t.roster_id ?? rosterId;
    } else if (!_teamExists(teamName)) {
      teamName = '';
    }

    const nextProfile = {
      platform: 'sleeper',
      username: existing.username || 'Sleeper',
      userId: existing.userId || '',
      leagueId: customLeagueId,
      customLeagueId: customLeagueId,
      baselineLeagueId: baselineLeagueId,
      leagueName,
      teamName,
      rosterId,
      savedAt: new Date().toISOString(),
    };
    saveProfile(nextProfile);
    if (teamName) syncGlobalTeam(teamName);
    return nextProfile;
  }

  async function loadHardcodedLeagueTeams() {
    let teams = Array.isArray(sleeperTeams) ? sleeperTeams : [];
    let leagueName = String(loadedData?.sleeper?.leagueName || HARDCODED_LEAGUE_NAME_FALLBACK);
    const leagueId = getCurrentLeagueId();
    if (teams.length) return { teams, leagueName };
    if (!leagueId) return { teams: [], leagueName };

    const [league, rosters, users] = await Promise.all([
      sleeperFetchLeague(leagueId),
      sleeperFetchRosters(leagueId),
      sleeperFetchUsers(leagueId),
    ]);

    if (league?.name) leagueName = String(league.name);
    const userMap = {};
    (users || []).forEach(u => { userMap[u.user_id] = u.display_name || u.username || `Roster ${u.user_id}`; });

    teams = (rosters || []).map(r => ({
      roster_id: r.roster_id,
      rosterId: r.roster_id,
      owner_id: r.owner_id,
      ownerId: r.owner_id,
      name: userMap[r.owner_id] || `Roster ${r.roster_id}`,
      players: Array.isArray(r.players) ? r.players : [],
      picks: [],
      playerCount: Array.isArray(r.players) ? r.players.length : 0,
    })).sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));

    if (teams.length && (!Array.isArray(sleeperTeams) || sleeperTeams.length === 0)) {
      sleeperTeams = teams;
      populateTeamDropdowns();
    }
    return { teams, leagueName };
  }

  async function showOnboarding() {
    const overlay = document.getElementById('onboardOverlay');
    const modal = document.getElementById('onboardModal');
    if (!overlay || !modal) return;
    const leagueId = getCurrentLeagueId();
    const baselineLeagueId = getBaselineLeagueId();

    overlay.classList.add('active');
    modal.innerHTML = `
      <h2>Select Your Team</h2>
      <p>Loading rosters from your configured Sleeper league…</p>
      <div class="onboard-loading">League ID: ${leagueId || 'Not configured'}</div>
      <div class="onboard-loading">Baseline ID: ${baselineLeagueId || 'Not configured'}</div>
    `;

    try {
      const profile = ensureHardcodedLeagueProfile();
      const { teams, leagueName } = await loadHardcodedLeagueTeams();
      if (!teams.length) {
        modal.innerHTML = `
          <h2>League Not Available</h2>
          <p>Could not load rosters for league <strong>${leagueId || 'Not configured'}</strong>.</p>
          <div id="onboardError"><p class="onboard-error">Try refreshing values, then open this again.</p></div>
          <button class="onboard-btn ghost" onclick="closeOnboarding()">Close</button>
        `;
        return;
      }

      const selectedName = resolvePreferredTeamName({
        teams,
        explicitTeam: profile?.teamName || '',
        savedTeam: localStorage.getItem('dynasty_my_team') || '',
        profileTeam: profile?.teamName || '',
      });
      const selectedTeam = teams.find(t => t.name === selectedName) || teams[0];
      onboardState = {
        username: profile?.username || 'Sleeper',
        userId: profile?.userId || '',
        selectedLeague: { league_id: leagueId, name: leagueName },
        teams,
        selectedTeam,
      };

      let teamCards = '';
      teams.forEach((t, i) => {
        const isSel = selectedTeam && t.name === selectedTeam.name;
        const playerCount = Array.isArray(t.players) ? t.players.length : (t.playerCount || 0);
        teamCards += `<div class="onboard-team ${isSel ? 'selected' : ''}" data-idx="${i}" onclick="selectOnboardTeam(${i},this)">
          ${t.name} <span style="color:var(--subtext);">(${playerCount} players)</span>
        </div>`;
      });

      modal.innerHTML = `
        <h2>Select Your Team</h2>
        <p><strong>${leagueName}</strong></p>
        <div class="onboard-teams">${teamCards}</div>
        <button class="onboard-btn primary" onclick="finishOnboarding()" id="onboardTeamDone">Done</button>
        <br><button class="onboard-btn ghost" onclick="closeOnboarding()">Close</button>
      `;
    } catch (e) {
      modal.innerHTML = `
        <h2>League Load Error</h2>
      <p>Could not load your configured league rosters.</p>
        <div id="onboardError"><p class="onboard-error">${String(e?.message || e || 'Unknown error')}</p></div>
        <button class="onboard-btn ghost" onclick="closeOnboarding()">Close</button>
      `;
    }
  }

  function closeOnboarding() {
    document.getElementById('onboardOverlay')?.classList.remove('active');
  }

  function selectOnboardTeam(idx, el) {
    document.querySelectorAll('.onboard-team').forEach(e => e.classList.remove('selected'));
    el.classList.add('selected');
    onboardState.selectedTeam = onboardState.teams[idx];
    document.getElementById('onboardTeamDone').disabled = false;
  }

  function finishOnboarding() {
    const existing = getProfile() || {};
    const ids = getCanonicalLeagueIds();
    const customLeagueId = String(
      ids.customLeagueId || existing.customLeagueId || existing.leagueId || ''
    ).trim();
    const baselineLeagueId = String(
      ids.baselineLeagueId || existing.baselineLeagueId || ''
    ).trim();
    const profile = {
      platform: 'sleeper',
      username: onboardState.username || existing.username || 'Sleeper',
      userId: onboardState.userId || existing.userId || '',
      leagueId: customLeagueId,
      customLeagueId: customLeagueId,
      baselineLeagueId: baselineLeagueId,
      leagueName: onboardState.selectedLeague?.name || existing.leagueName || HARDCODED_LEAGUE_NAME_FALLBACK,
      teamName: onboardState.selectedTeam?.name,
      rosterId: onboardState.selectedTeam?.rosterId ?? onboardState.selectedTeam?.roster_id ?? existing.rosterId ?? '',
      savedAt: new Date().toISOString(),
    };
    saveProfile(profile);
    closeOnboarding();

    // Set team in rosterMyTeam dropdown
    const sel = document.getElementById('rosterMyTeam');
    if (sel) {
      for (const opt of sel.options) {
        if (opt.value === profile.teamName) {
          sel.value = profile.teamName;
          break;
        }
      }
    }
    syncGlobalTeam(profile.teamName);
  }

  // ── SAVE/LOAD TRADES ──
  const SAVED_TRADES_KEY = 'dynasty_saved_trades';

  function getSavedTrades() {
    try { return JSON.parse(localStorage.getItem(SAVED_TRADES_KEY) || '[]'); }
    catch { return []; }
  }

  function populateSavedTrades() {
    const trades = getSavedTrades();
    const selects = ['savedTradesSelect', 'mobileSavedTradesSelect']
      .map(id => document.getElementById(id))
      .filter(Boolean);
    selects.forEach(sel => {
      const prev = String(sel.value || '');
      sel.innerHTML = '<option value="">Saved Trades…</option>';
      trades.forEach((t, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = t.label || `Trade ${i + 1}`;
        sel.appendChild(opt);
      });
      if (prev && trades[Number(prev)]) sel.value = prev;
      sel.style.display = trades.length ? '' : 'none';
    });
    ['deleteSavedBtn', 'mobileDeleteSavedTradeBtn'].forEach(id => {
      const btn = document.getElementById(id);
      if (btn) btn.style.display = trades.length ? '' : 'none';
    });
    syncMobileTradeControlState();
  }

  function saveTrade() {
    const sides = {};
    ['sideABody', 'sideBBody', 'sideCBody'].forEach(id => {
      const tbody = document.getElementById(id);
      if (!tbody) return;
      const players = [];
      tbody.querySelectorAll('tr').forEach(row => {
        const inp = row.querySelector('.player-name-input');
        const name = (inp?.value || '').trim();
        if (name) players.push(name);
      });
      if (players.length) sides[id.replace('Body', '')] = players;
    });
    if (!Object.keys(sides).length) return;

    const pill = document.getElementById('decision');
    const pct = document.getElementById('percentDiff');
    const label = prompt('Name this trade (or leave blank):', '') || 
      `${Object.values(sides).flat().slice(0, 2).join(' / ')} — ${new Date().toLocaleDateString()}`;

    const trades = getSavedTrades();
    trades.unshift({ label, sides, date: new Date().toISOString(), verdict: pill?.textContent, pct: pct?.textContent });
    if (trades.length > 20) trades.length = 20;
    localStorage.setItem(SAVED_TRADES_KEY, JSON.stringify(trades));
    populateSavedTrades();
    buildMoreHub();
    buildHomeHub();
    const btn = document.getElementById('saveTradeBtn');
    if (btn) { btn.textContent = '✓ Saved!'; setTimeout(() => { btn.textContent = '💾 Save Trade'; }, 2000); }
  }

  function loadSavedTrade(idx) {
    if (idx === '') return;
    const trades = getSavedTrades();
    const trade = trades[parseInt(idx)];
    if (!trade) return;

    // Clear all rows
    ['sideABody', 'sideBBody', 'sideCBody'].forEach(id => {
      const tbody = document.getElementById(id);
      if (!tbody) return;
      tbody.querySelectorAll('tr').forEach(row => {
        const inp = row.querySelector('.player-name-input');
        if (inp) inp.value = '';
        row.querySelectorAll('.site-input').forEach(si => { si.value = ''; });
      });
    });

    // Fill in saved players
    for (const [sideKey, players] of Object.entries(trade.sides)) {
      const tbodyId = sideKey + 'Body';
      const tbody = document.getElementById(tbodyId);
      if (!tbody) continue;
      const rows = tbody.querySelectorAll('tr');
      players.forEach((name, i) => {
        if (i < rows.length) {
          const inp = rows[i].querySelector('.player-name-input');
          if (inp) {
            inp.value = name;
            if (loadedData) autoFillRow(rows[i]);
          }
        }
      });
    }
    scheduleRecalc();
    const selDesktop = document.getElementById('savedTradesSelect');
    if (selDesktop) selDesktop.value = String(idx);
    const selMobile = document.getElementById('mobileSavedTradesSelect');
    if (selMobile) selMobile.value = String(idx);
    renderMobileTradeWorkspace();
    updateMobileTradeTray();
  }

  function deleteSavedTrade() {
    const selDesktop = document.getElementById('savedTradesSelect');
    const selMobile = document.getElementById('mobileSavedTradesSelect');
    const activeValue = String(selDesktop?.value || selMobile?.value || '');
    const idx = parseInt(activeValue);
    if (isNaN(idx)) return;
    const trades = getSavedTrades();
    const name = trades[idx]?.label || 'this trade';
    if (!confirm(`Delete "${name}"?`)) return;
    trades.splice(idx, 1);
    localStorage.setItem(SAVED_TRADES_KEY, JSON.stringify(trades));
    populateSavedTrades();
    buildMoreHub();
    buildHomeHub();
    if (selDesktop) selDesktop.value = '';
    if (selMobile) selMobile.value = '';
  }

  // ── TRADE IMPACT SIMULATOR ──
  function computeTradeImpact() {
    const panel = document.getElementById('tradeImpactPanel');
    const body = document.getElementById('tradeImpactBody');
    if (!panel || !body || !loadedData || !sleeperTeams.length) {
      if (panel) panel.style.display = 'none';
      return;
    }

    const teamA = document.getElementById('teamFilterA')?.value;
    const teamB = document.getElementById('teamFilterB')?.value;
    if (!teamA || !teamB) {
      panel.style.display = 'none';
      return;
    }

    const posMap = loadedData.sleeper?.positions || {};
    const posGroups = ['QB', 'RB', 'WR', 'TE', 'IDP'];

    function getTeamPosTotals(teamName, adds, removes) {
      const team = sleeperTeams.find(t => t.name === teamName);
      if (!team) return {};
      const roster = new Set(team.players.map(p => p.toLowerCase()));
      removes.forEach(p => roster.delete(p.toLowerCase()));
      adds.forEach(p => roster.add(p.toLowerCase()));

      const totals = {};
      posGroups.forEach(pg => { totals[pg] = 0; });
      for (const name of roster) {
        // Find canonical name
        let canonical = name;
        for (const pn of Object.keys(loadedData.players)) {
          if (pn.toLowerCase() === name) { canonical = pn; break; }
        }
        const result = computeMetaValueForPlayer(canonical);
        if (!result) continue;
        let pos = (posMap[canonical] || '').toUpperCase();
        if (['LB', 'DL', 'DE', 'DT', 'CB', 'S', 'DB', 'EDGE'].includes(pos)) pos = 'IDP';
        if (totals[pos] !== undefined) totals[pos] += result.metaValue;
      }
      return totals;
    }

    // Get players on each side
    const sideAPlayers = [], sideBPlayers = [];
    document.getElementById('sideABody')?.querySelectorAll('tr').forEach(row => {
      const name = row.querySelector('.player-name-input')?.value?.trim();
      if (name) sideAPlayers.push(name);
    });
    document.getElementById('sideBBody')?.querySelectorAll('tr').forEach(row => {
      const name = row.querySelector('.player-name-input')?.value?.trim();
      if (name) sideBPlayers.push(name);
    });

    if (!sideAPlayers.length || !sideBPlayers.length) {
      panel.style.display = 'none';
      return;
    }

    // Team A gives sideAPlayers, gets sideBPlayers
    const beforeA = getTeamPosTotals(teamA, [], []);
    const afterA = getTeamPosTotals(teamA, sideBPlayers, sideAPlayers);
    const beforeB = getTeamPosTotals(teamB, [], []);
    const afterB = getTeamPosTotals(teamB, sideAPlayers, sideBPlayers);

    // Rank all teams by position group
    function rankTeams(posGroup) {
      return sleeperTeams.map(t => {
        let total = 0;
        t.players.forEach(p => {
          const result = computeMetaValueForPlayer(p);
          if (!result) return;
          let pos = (posMap[p] || '').toUpperCase();
          if (['LB', 'DL', 'DE', 'DT', 'CB', 'S', 'DB', 'EDGE'].includes(pos)) pos = 'IDP';
          if (pos === posGroup) total += result.metaValue;
        });
        return { name: t.name, total };
      }).sort((a, b) => b.total - a.total);
    }

    let html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">';
    [{ name: teamA, before: beforeA, after: afterA, label: 'Side A' },
     { name: teamB, before: beforeB, after: afterB, label: 'Side B' }].forEach(side => {
      html += `<div><strong>${side.name}</strong><table style="width:100%;font-size:0.72rem;font-family:var(--mono);margin-top:6px;">`;
      html += '<tr><th>Pos</th><th>Before</th><th>After</th><th>Δ</th></tr>';
      posGroups.forEach(pg => {
        const before = Math.round(side.before[pg] || 0);
        const after = Math.round(side.after[pg] || 0);
        const diff = after - before;
        const color = diff > 0 ? 'var(--green)' : diff < 0 ? 'var(--red)' : 'var(--subtext)';
        const sign = diff > 0 ? '+' : '';
        html += `<tr><td>${pg}</td><td>${before.toLocaleString()}</td><td>${after.toLocaleString()}</td><td style="color:${color};font-weight:600;">${sign}${diff.toLocaleString()}</td></tr>`;
      });
      html += '</table></div>';
    });
    html += '</div>';

    body.innerHTML = html;
    panel.style.display = '';
  }

  // ── LEAGUE-MATE TRADE TENDENCIES ──
  function buildTendencies() {
    const body = document.getElementById('tendenciesBody');
    if (!body || !loadedData?.sleeper?.trades?.length) {
      if (body) body.innerHTML = '<p style="color:var(--subtext);">No trade data available.</p>';
      return;
    }

    const trades = loadedData.sleeper.trades;
    const managerStats = {};

    trades.forEach(trade => {
      if (!trade.sides || trade.sides.length < 2) return;
      trade.sides.forEach(side => {
        const mgr = side.team || 'Unknown';
        if (!managerStats[mgr]) managerStats[mgr] = { trades: 0, totalGiven: 0, totalGot: 0, posBias: {} };
        const stats = managerStats[mgr];
        stats.trades++;

        let gotTotal = 0, gaveTotal = 0;
        (side.got || []).forEach(name => {
          const r = computeMetaValueForPlayer(name);
          if (r) gotTotal += r.metaValue;
        });
        (side.gave || []).forEach(name => {
          const r = computeMetaValueForPlayer(name);
          if (r) gaveTotal += r.metaValue;
        });
        stats.totalGot += gotTotal;
        stats.totalGiven += gaveTotal;

        // Track position bias in acquisitions
        const posMap = loadedData.sleeper?.positions || {};
        (side.got || []).forEach(name => {
          let pos = (posMap[name] || '').toUpperCase();
          if (!pos) return;
          if (['LB', 'DL', 'DE', 'DT', 'CB', 'S', 'DB', 'EDGE'].includes(pos)) pos = 'IDP';
          stats.posBias[pos] = (stats.posBias[pos] || 0) + 1;
        });
      });
    });

    let html = '<table style="width:100%;font-size:0.74rem;font-family:var(--mono);">';
    html += '<tr><th>Manager</th><th>Trades</th><th>Avg Given</th><th>Avg Got</th><th>Net</th><th>Tendency</th></tr>';

    const sorted = Object.entries(managerStats).sort((a, b) => b[1].trades - a[1].trades);
    sorted.forEach(([mgr, s]) => {
      const avgGiven = Math.round(s.totalGiven / s.trades);
      const avgGot = Math.round(s.totalGot / s.trades);
      const net = avgGot - avgGiven;
      const netColor = net > 0 ? 'var(--green)' : net < 0 ? 'var(--red)' : 'var(--subtext)';
      const netSign = net > 0 ? '+' : '';

      // Find most-acquired position
      const topPos = Object.entries(s.posBias).sort((a, b) => b[1] - a[1])[0];
      const tendency = topPos ? `Targets ${topPos[0]}s` : '—';

      html += `<tr><td>${mgr}</td><td style="text-align:center;">${s.trades}</td>`;
      html += `<td style="text-align:right;">${avgGiven.toLocaleString()}</td>`;
      html += `<td style="text-align:right;">${avgGot.toLocaleString()}</td>`;
      html += `<td style="text-align:right;color:${netColor};font-weight:600;">${netSign}${net.toLocaleString()}</td>`;
      html += `<td>${tendency}</td></tr>`;
    });
    html += '</table>';
    html += '<p style="font-size:0.66rem;color:var(--subtext);margin-top:8px;">Based on current composite values applied to historical trades. Negative net = tends to overpay.</p>';

    body.innerHTML = html;
  }

  // ── AUTO TRADE PROPOSALS ──
  function generateTradePackages(targetName) {
    if (!loadedData || !sleeperTeams.length) return [];
    const myTeamName = document.getElementById('rosterMyTeam')?.value;
    if (!myTeamName) return [];
    const myTeam = sleeperTeams.find(t => t.name === myTeamName);
    if (!myTeam) return [];

    const targetResult = computeMetaValueForPlayer(targetName);
    if (!targetResult) return [];
    const targetVal = targetResult.metaValue;

    // Get my roster with values
    const myPlayers = [];
    myTeam.players.forEach(p => {
      if (p.toLowerCase() === targetName.toLowerCase()) return;
      const r = computeMetaValueForPlayer(p);
      if (r && r.metaValue > 0) myPlayers.push({ name: p, value: r.metaValue });
    });
    myPlayers.sort((a, b) => b.value - a.value);

    const packages = [];
    const tolerance = 0.08; // 8% tolerance

    // 1:1 trades
    myPlayers.forEach(p => {
      const diff = Math.abs(p.value - targetVal) / targetVal;
      if (diff < tolerance) {
        packages.push({ players: [p.name], total: p.value, diff });
      }
    });

    // 2:1 trades
    for (let i = 0; i < Math.min(myPlayers.length, 30); i++) {
      for (let j = i + 1; j < Math.min(myPlayers.length, 30); j++) {
        const total = myPlayers[i].value + myPlayers[j].value;
        const diff = Math.abs(total - targetVal) / targetVal;
        if (diff < tolerance) {
          packages.push({ players: [myPlayers[i].name, myPlayers[j].name], total, diff });
        }
      }
    }

    packages.sort((a, b) => a.diff - b.diff);
    return packages.slice(0, 5);
  }

  // ═══════════════════════════════════════
  // LEAGUE TAB
  // ═══════════════════════════════════════
  let _leagueInited = false;
  const _leaguePanels = ['heatmap','breakdown','compare','ktcTrades','ktcWaivers'];

  function switchLeagueSub(id) {
    _leaguePanels.forEach(p => {
      const el = document.getElementById('leagueSub-' + p);
      if (el) el.style.display = p === id ? '' : 'none';
    });
    // Style buttons
    document.querySelectorAll('#leagueSubTabs button').forEach((b, i) => {
      const isActive = _leaguePanels[i] === id;
      b.className = isActive ? 'btn btn-sm' : 'btn btn-ghost btn-sm';
    });
    if (id === 'heatmap') buildPowerRankingsHeatmap();
    if (id === 'breakdown') buildTeamBreakdown();
    if (id === 'compare') buildTeamComparison();
    if (id === 'ktcTrades') buildKtcTradesView();
    if (id === 'ktcWaivers') buildKtcWaiversView();
  }

  function initLeagueTab() {
    if (!_leagueInited) {
      _populateLeagueDropdowns();
      _leagueInited = true;
    }
    buildPowerRankingsHeatmap();
  }

  function _populateLeagueDropdowns() {
    ['breakdownTeamSelect','compareTeamA','compareTeamB'].forEach(selId => {
      const sel = document.getElementById(selId);
      if (!sel) return;
      sel.innerHTML = '';
      sleeperTeams.forEach(t => {
        const o = document.createElement('option'); o.value = t.name; o.textContent = t.name; sel.appendChild(o);
      });
    });
    const b = document.getElementById('compareTeamB');
    if (b && b.options.length >= 2) b.selectedIndex = 1;
    const myTeam = localStorage.getItem('dynasty_my_team');
    if (myTeam) { const bd = document.getElementById('breakdownTeamSelect'); if (bd) bd.value = myTeam; }
  }

  function _pickRoundSuffix(roundNum) {
    if (roundNum === 1) return 'st';
    if (roundNum === 2) return 'nd';
    if (roundNum === 3) return 'rd';
    return 'th';
  }

  function _getTeamStrengthSnapshot() {
    const posMap = loadedData?.sleeper?.positions || {};
    const ordered = sleeperTeams.map(team => {
      const playerNames = Array.isArray(team.players) ? team.players : [];
      let total = 0;
      for (const pn of playerNames) {
        if (parsePickToken(pn)) continue;
        const r = computeMetaValueForPlayer(pn);
        if (!r || r.metaValue <= 0) continue;
        const pos = (posMap[pn] || '').toUpperCase();
        if (isKickerPosition(pos)) continue;
        const g = posGroup(pos);
        if (['QB','RB','WR','TE','DL','LB','DB'].includes(g)) total += r.metaValue;
      }
      return {
        name: team.name,
        roster_id: Number(team.roster_id),
        total,
      };
    }).sort((a, b) => b.total - a.total);

    const n = Math.max(ordered.length, 1);
    const bucket = Math.max(1, Math.ceil(n / 3));
    const byRosterId = {};
    ordered.forEach((t, idx) => {
      let tier = 'mid';
      if (idx < bucket) tier = 'late';
      else if (idx >= n - bucket) tier = 'early';
      if (Number.isFinite(t.roster_id)) {
        byRosterId[t.roster_id] = { rank: idx + 1, tier, total: t.total, name: t.name };
      }
    });
    return { ordered, byRosterId };
  }

  function _buildTeamPickAssets(team, teamStrengthByRosterId) {
    const pickDetails = Array.isArray(team?.pickDetails) && team.pickDetails.length
      ? team.pickDetails
      : (Array.isArray(team?.picks) ? team.picks.map(p => ({ label: p })) : []);
    const byRid = teamStrengthByRosterId || {};
    const out = [];

    for (const rawEntry of pickDetails) {
      const detail = (rawEntry && typeof rawEntry === 'object') ? rawEntry : { label: String(rawEntry || '') };
      const label = String(detail.label || detail.baseLabel || '').trim();
      const fromRosterId = Number(detail.fromRosterId);
      const fromTeam = String(detail.fromTeam || '').trim();

      let season = Number(detail.season);
      let roundNum = Number(detail.round);
      let slotNum = Number(detail.slot);
      let explicitTier = null;
      let valueToken = null;

      const parsed = parsePickToken(label);
      if ((!Number.isFinite(season) || !Number.isFinite(roundNum)) && parsed) {
        if (Number.isFinite(parsed.year)) season = parsed.year;
        if (Number.isFinite(parsed.round)) roundNum = parsed.round;
      }
      if (!Number.isFinite(slotNum) && parsed && parsed.kind === 'slot' && Number.isFinite(parsed.slot)) {
        slotNum = parsed.slot;
      }
      if (parsed && parsed.kind === 'slot' && Number.isFinite(parsed.year)) {
        valueToken = `${parsed.year} ${parsed.round}.${String(parsed.slot).padStart(2, '0')}`;
      } else if (parsed && parsed.kind === 'tier' && /(EARLY|MID|LATE)/i.test(label)) {
        explicitTier = parsed.tier;
      }
      if (!Number.isFinite(season) || !Number.isFinite(roundNum)) {
        const stripped = label.replace(/\s*\([^)]*\)\s*$/, '').trim();
        const m = stripped.match(/^(20\d{2})\s+([1-6])/i);
        if (m) {
          season = Number(m[1]);
          roundNum = Number(m[2]);
        }
      }

      if (!valueToken && Number.isFinite(season) && Number.isFinite(roundNum) && Number.isFinite(slotNum) && slotNum > 0) {
        valueToken = `${season} ${roundNum}.${String(slotNum).padStart(2, '0')}`;
      }

      if (!valueToken && Number.isFinite(season) && Number.isFinite(roundNum)) {
        let tier = explicitTier;
        if (!tier && Number.isFinite(fromRosterId) && byRid[fromRosterId]?.tier) {
          tier = byRid[fromRosterId].tier;
        }
        if (!tier) tier = 'mid';
        valueToken = `${season} ${tier.charAt(0).toUpperCase() + tier.slice(1)} ${roundNum}${_pickRoundSuffix(roundNum)}`;
      }

      let meta = 0;
      if (valueToken) {
        const r = computeMetaValueForPlayer(valueToken);
        if (r && r.metaValue > 0) meta = r.metaValue;
        else meta = estimatePickAssetValue(valueToken);
      }
      if ((!isFinite(meta) || meta <= 0) && label) {
        meta = estimatePickAssetValue(label);
      }

      out.push({
        name: label || valueToken || 'Pick',
        meta: Math.max(0, Math.round(Number(meta) || 0)),
        pos: 'PICK',
        group: 'PICKS',
        isPick: true,
        valueToken: valueToken || '',
        slot: Number.isFinite(slotNum) ? slotNum : null,
        fromTeam,
      });
    }
    return out;
  }

  // ── POWER RANKINGS HEATMAP ──
  function buildPowerRankingsHeatmap() {
    const c = document.getElementById('powerRankingsHeatmap');
    if (!c || !loadedData || !sleeperTeams.length) { if(c) c.innerHTML='<p style="color:var(--subtext);padding:12px;">Load data with Sleeper league first.</p>'; return; }
    const posMap = loadedData.sleeper?.positions || {};
    const PG = ['QB','RB','WR','TE','DL','LB','DB','PICKS'];
    const myTeam = localStorage.getItem('dynasty_my_team') || '';
    const strengthSnapshot = _getTeamStrengthSnapshot();

    const td = sleeperTeams.map(team => {
      const bg = {}; PG.forEach(g => bg[g]=0); let total=0;
      const playerNames = Array.isArray(team.players) ? team.players : [];
      for (const pn of playerNames) {
        if (parsePickToken(pn)) continue;
        const r = computeMetaValueForPlayer(pn); if(!r||r.metaValue<=0) continue;
        const pos = (posMap[pn]||'').toUpperCase();
        if (isKickerPosition(pos)) continue;
        const g = posGroup(pos);
        if (!PG.includes(g) || g === 'PICKS') continue;
        bg[g] += r.metaValue;
      }
      const pickAssets = _buildTeamPickAssets(team, strengthSnapshot.byRosterId);
      for (const p of pickAssets) {
        if (p.meta > 0) bg.PICKS += p.meta;
      }
      total = PG.reduce((s, g) => s + (bg[g] || 0), 0);
      return {name:team.name, total, bg};
    });

    const gRanks = {};
    PG.forEach(g => {
      const s = td.slice().sort((a,b) => b.bg[g]-a.bg[g]);
      s.forEach((t,i) => { if(!gRanks[t.name]) gRanks[t.name]={}; gRanks[t.name][g]=i+1; });
    });
    const overall = td.slice().sort((a,b)=>b.total-a.total);
    overall.forEach((t,i) => { gRanks[t.name]._rank=i+1; gRanks[t.name]._total=t.total; });
    const n = sleeperTeams.length;

    function hc(rank, total) {
      const p = (rank-1)/Math.max(total-1,1);
      if(p<=0.25) return `rgb(${10+p/0.25*20|0},${80+p/0.25*60|0},${100+p/0.25*40|0})`;
      if(p<=0.5) { const t=(p-0.25)/0.25; return `rgb(${30+t*30|0},${140-t*40|0},${140-t*20|0})`; }
      if(p<=0.75) { const t=(p-0.5)/0.25; return `rgb(${60+t*100|0},${100-t*40|0},${120-t*30|0})`; }
      const t=(p-0.75)/0.25; return `rgb(${160+t*60|0},${60-t*20|0},${90-t*20|0})`;
    }
    function heatTextColor(bg) {
      const m = String(bg || '').match(/rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)/i);
      if (!m) return 'var(--heat-text-dark)';
      const r = Number(m[1]) || 0;
      const g = Number(m[2]) || 0;
      const b = Number(m[3]) || 0;
      // Relative luminance threshold tuned for compact mono labels on colored badges.
      const lum = ((0.2126 * r) + (0.7152 * g) + (0.0722 * b)) / 255;
      return lum < 0.54 ? 'var(--heat-text-light)' : 'var(--heat-text-dark)';
    }

    let h = '<table style="width:100%;border-collapse:collapse;font-size:0.74rem;"><thead><tr>';
    h += '<th style="text-align:left;padding:8px 6px;font-size:0.62rem;color:var(--subtext);font-family:var(--mono);">#</th>';
    h += '<th style="text-align:left;padding:8px 6px;font-size:0.62rem;color:var(--subtext);">Team</th>';
    h += '<th style="text-align:right;padding:8px 6px;font-size:0.62rem;color:var(--subtext);font-family:var(--mono);">Total</th>';
    PG.forEach(g => { const cl = POS_GROUP_COLORS[g]||'var(--subtext)'; h += `<th style="text-align:center;padding:8px 6px;font-size:0.62rem;color:${cl};font-family:var(--mono);">${g}</th>`; });
    h += '</tr></thead><tbody>';

    overall.forEach((team,idx) => {
      const rk = gRanks[team.name]; const isMe = team.name===myTeam;
      h += `<tr style="cursor:pointer;border-bottom:1px solid var(--border-dim);${isMe?'background:rgba(200,56,3,0.06);':''}" onclick="document.getElementById('breakdownTeamSelect').value='${team.name.replace(/'/g,"\\'")}';switchLeagueSub('breakdown');">`;
      h += `<td style="padding:6px;font-family:var(--mono);font-weight:700;color:var(--subtext);">${idx+1}</td>`;
      h += `<td style="padding:6px;font-weight:700;${isMe?'color:var(--cyan);':''}">${team.name}</td>`;
      h += `<td style="padding:6px;text-align:right;font-family:var(--mono);font-weight:600;">${Math.round(team.total).toLocaleString()}</td>`;
      PG.forEach(g => {
        const rank = rk[g]; const bg = hc(rank,n);
        const gVal = Math.round(team.bg[g] || 0).toLocaleString();
        const fg = heatTextColor(bg);
        h += `<td style="padding:6px;text-align:center;"><span title="${g}: ${gVal}" style="display:inline-block;min-width:32px;padding:4px 8px;border-radius:4px;background:${bg};color:${fg};font-family:var(--mono);font-weight:700;">${rank}</span></td>`;
      });
      h += '</tr>';
    });
    h += '</tbody></table>';
    c.innerHTML = h;
  }

  // ── TEAM BREAKDOWN ──
  function buildTeamBreakdown() {
    const c = document.getElementById('teamBreakdownContent');
    if (!c||!loadedData||!sleeperTeams.length) { if(c) c.innerHTML='<p style="color:var(--subtext);">Load data first.</p>'; return; }
    const tn = document.getElementById('breakdownTeamSelect')?.value; if (!tn) return;
    const viewMode = document.getElementById('breakdownViewMode')?.value || 'grouped';
    const team = sleeperTeams.find(t=>t.name===tn); if (!team) return;
    const posMap = loadedData.sleeper?.positions || {};
    const GROUPS = ['QB','RB','WR','TE','DL','LB','DB','PICKS'];
    const GC = {
      QB:'#e74c3c', RB:'#27ae60', WR:'#3498db', TE:'#e67e22',
      DL:'#9b59b6', LB:'#8e44ad', DB:'#16a085', PICKS:'#f39c12'
    };
    const LABELS = {
      QB:'Quarterbacks', RB:'Running Backs', WR:'Wide Receivers', TE:'Tight Ends',
      DL:'Defensive Line', LB:'Linebackers', DB:'Defensive Backs', PICKS:'Draft Picks'
    };
    const strengthSnapshot = _getTeamStrengthSnapshot();

    const all = sleeperTeams.map(t => {
      const bg={}; GROUPS.forEach(g=>bg[g]=0);
      const playerNames = Array.isArray(t.players) ? t.players : [];
      for (const p of playerNames) {
        if (parsePickToken(p)) continue;
        const r=computeMetaValueForPlayer(p);
        if(!r||r.metaValue<=0)continue;
        const pos=(posMap[p]||'').toUpperCase();
        if (isKickerPosition(pos)) continue;
        const g = posGroup(pos);
        if (GROUPS.includes(g) && g !== 'PICKS') bg[g]+=r.metaValue;
      }
      const pickAssets = _buildTeamPickAssets(t, strengthSnapshot.byRosterId);
      pickAssets.forEach(p => { if (p.meta > 0) bg.PICKS += p.meta; });
      const total = GROUPS.reduce((s, g) => s + (bg[g] || 0), 0);
      return {name:t.name,total,bg};
    });
    all.sort((a,b)=>b.total-a.total);
    const rank = all.findIndex(t=>t.name===tn)+1;
    const my = all.find(t=>t.name===tn);
    const posRanks={}; GROUPS.forEach(g=>{const s=all.slice().sort((a,b)=>b.bg[g]-a.bg[g]);posRanks[g]=s.findIndex(t=>t.name===tn)+1;});

    const players=[];
    const teamPlayers = Array.isArray(team.players) ? team.players : [];
    for(const pn of teamPlayers){
      if (parsePickToken(pn)) continue;
      const r=computeMetaValueForPlayer(pn);
      const pos=(posMap[pn]||'').toUpperCase();
      if (isKickerPosition(pos)) continue;
      const g=posGroup(pos);
      players.push({name:pn,pos:pos||'?',group:g,meta:r?r.metaValue:0,isPick:false});
    }
    const pickAssets = _buildTeamPickAssets(team, strengthSnapshot.byRosterId);
    const assets = players.concat(pickAssets).sort((a,b)=>b.meta-a.meta);

    const ord=n=>{const s=['th','st','nd','rd'];const v=n%100;return s[(v-20)%10]||s[v]||s[0];};
    const pickCount = Array.isArray(team.picks) ? team.picks.length : pickAssets.length;
    let h = `<div style="display:flex;align-items:center;gap:14px;margin-bottom:14px;">`;
    h += `<div style="font-size:1.6rem;font-weight:800;color:var(--cyan);width:48px;height:48px;display:flex;align-items:center;justify-content:center;border:2px solid var(--cyan-border);border-radius:var(--radius);background:var(--cyan-soft);">${rank}</div>`;
    h += `<div><div style="font-size:1.2rem;font-weight:700;">${tn}</div>`;
    h += `<div style="font-size:0.72rem;color:var(--subtext);font-family:var(--mono);">${teamPlayers.length} players · ${pickCount} picks</div></div></div>`;

    h += '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;">';
    GROUPS.forEach(g => {
      const r=posRanks[g];const cl=GC[g];
      h += `<span style="padding:4px 12px;border-radius:20px;font-size:0.68rem;font-weight:700;font-family:var(--mono);color:${cl};border:1px solid ${cl}44;background:${r<=3?cl+'22':'transparent'};">${g}: ${r}${ord(r)}</span>`;
    });
    h += '</div>';

    if (viewMode === 'value') {
      h += '<div style="margin-bottom:14px;"><div style="padding:4px 8px;border-bottom:1px solid var(--border);font-weight:700;font-size:0.78rem;">All Assets by Value</div>';
      assets.filter(p => p.meta > 0).forEach((p, i) => {
        const pColor = GC[p.group] || 'var(--subtext)';
        const pickHint = (p.isPick && p.valueToken && p.valueToken !== p.name)
          ? `<span style="display:block;color:var(--subtext);font-size:0.6rem;">→ ${p.valueToken}</span>`
          : '';
        h += `<div style="display:flex;align-items:center;gap:8px;padding:5px 8px;font-size:0.74rem;border-bottom:1px solid var(--border-dim);">`;
        h += `<span style="width:22px;color:var(--subtext);font-family:var(--mono);font-size:0.66rem;">${i+1}</span>`;
        h += `<span style="flex:1;font-weight:600;">${p.name}${pickHint}</span>`;
        h += `<span style="font-family:var(--mono);font-size:0.62rem;font-weight:700;color:${pColor};width:48px;">${p.group === 'PICKS' ? 'PICK' : (p.pos || '?')}</span>`;
        h += `<span style="font-family:var(--mono);font-weight:600;width:70px;text-align:right;">${Math.round(p.meta).toLocaleString()}</span></div>`;
      });
      h += '</div>';
      c.innerHTML = h;
      return;
    }

    GROUPS.forEach(g => {
      const gp = assets.filter(p=>p.group===g && p.meta > 0).sort((a,b)=>b.meta-a.meta);
      if(!gp.length)return;
      h += `<div style="margin-bottom:14px;"><div style="display:flex;justify-content:space-between;padding:4px 8px;border-bottom:1px solid var(--border);"><span style="font-weight:700;color:${GC[g]};font-size:0.78rem;">${LABELS[g] || g}</span><span style="font-size:0.68rem;color:var(--subtext);font-family:var(--mono);">${posRanks[g]}${ord(posRanks[g])} / ${sleeperTeams.length}</span></div>`;
      gp.forEach((p,i) => {
        const pickHint = (p.isPick && p.valueToken && p.valueToken !== p.name)
          ? `<span style="display:block;color:var(--subtext);font-size:0.6rem;">→ ${p.valueToken}</span>`
          : '';
        h += `<div style="display:flex;align-items:center;gap:8px;padding:5px 8px;font-size:0.74rem;border-bottom:1px solid var(--border-dim);">`;
        h += `<span style="width:22px;color:var(--subtext);font-family:var(--mono);font-size:0.66rem;">${i+1}</span>`;
        h += `<span style="flex:1;font-weight:600;">${p.name}${pickHint}</span>`;
        h += `<span style="font-family:var(--mono);font-size:0.62rem;font-weight:700;color:${GC[g]};width:42px;">${g === 'PICKS' ? 'PICK' : (p.pos || '?')}</span>`;
        h += `<span style="font-family:var(--mono);font-weight:600;width:70px;text-align:right;">${Math.round(p.meta).toLocaleString()}</span></div>`;
      });
      h += '</div>';
    });
    c.innerHTML = h;
  }

  // ── TEAM COMPARISON ──
  function buildTeamComparison() {
    const c = document.getElementById('teamComparisonContent');
    if (!c||!loadedData||!sleeperTeams.length) { if(c) c.innerHTML='<p style="color:var(--subtext);">Load data first.</p>'; return; }
    const tA = document.getElementById('compareTeamA')?.value;
    const tB = document.getElementById('compareTeamB')?.value;
    if (!tA||!tB) return;
    const posMap = loadedData.sleeper?.positions || {};
    const GROUPS=['QB','RB','WR','TE','DL','LB','DB','PICKS'];
    const GC={QB:'#e74c3c',RB:'#27ae60',WR:'#3498db',TE:'#e67e22',DL:'#9b59b6',LB:'#8e44ad',DB:'#16a085',PICKS:'#f39c12'};
    const strengthSnapshot = _getTeamStrengthSnapshot();

    function getData(name) {
      const team = sleeperTeams.find(t=>t.name===name);
      if(!team)return{bg:{},assets:[],playerAssets:[],pickAssets:[],total:0};

      const bg={}; GROUPS.forEach(g=>bg[g]=0);
      const playerAssets=[];
      const playerNames = Array.isArray(team.players) ? team.players : [];

      for (const pn of playerNames) {
        if (parsePickToken(pn)) continue;
        const r=computeMetaValueForPlayer(pn);
        if(!r||r.metaValue<=0)continue;
        const pos=(posMap[pn]||'').toUpperCase();
        if (isKickerPosition(pos)) continue;
        const g = posGroup(pos);
        if (GROUPS.includes(g) && g !== 'PICKS') bg[g]+=r.metaValue;
        playerAssets.push({name:pn,meta:r.metaValue,pos:pos||'?',group:g,isPick:false});
      }
      playerAssets.sort((a,b)=>b.meta-a.meta);

      const pickAssets = _buildTeamPickAssets(team, strengthSnapshot.byRosterId);
      const keptPicks = pickAssets.filter(p => p.meta > 0).sort((a,b) => b.meta - a.meta);
      keptPicks.forEach(p => { bg.PICKS += p.meta; });

      const total = GROUPS.reduce((s, g) => s + (bg[g] || 0), 0);
      const assets = playerAssets.concat(keptPicks);
      assets.sort((a,b)=>b.meta-a.meta);
      return {bg,assets,playerAssets,pickAssets:keptPicks,total};
    }
    const dA=getData(tA), dB=getData(tB);

    let h = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">';
    [{name:tA,d:dA,cl:'rgba(100,180,220,0.8)'},{name:tB,d:dB,cl:'rgba(220,100,120,0.8)'}].forEach(side => {
      h += `<div><div style="font-weight:700;font-size:0.82rem;margin-bottom:8px;color:${side.cl};">${side.name}</div>`;
      h += `<div style="font-size:0.68rem;color:var(--subtext);margin-bottom:6px;">Total: <span style="font-family:var(--mono);font-weight:700;color:var(--text);">${Math.round(side.d.total).toLocaleString()}</span></div>`;
      GROUPS.forEach(g=>{h+=`<div style="font-size:0.68rem;color:var(--subtext);margin-bottom:2px;">${g}: <span style="color:${GC[g]};font-weight:600;">${Math.round(side.d.bg[g]||0).toLocaleString()}</span></div>`;});
      h+='<div style="margin-top:8px;">';
      h += `<div style="margin:8px 0 4px 0;font-size:0.66rem;color:var(--subtext);font-weight:700;">Top Players</div>`;
      side.d.playerAssets.slice(0,25).forEach((p,i)=>{
        const cl = GC[p.group] || '#9b59b6';
        const posLabel = p.pos || '?';
        h+=`<div style="display:flex;gap:6px;align-items:center;padding:3px 6px;font-size:0.72rem;border-bottom:1px solid var(--border-dim);">`;
        h+=`<span style="width:18px;color:var(--subtext);font-family:var(--mono);font-size:0.62rem;">${i+1}</span>`;
        h+=`<span style="font-weight:600;flex:1;">${p.name}</span>`;
        h+=`<span style="color:${cl};font-family:var(--mono);font-size:0.6rem;font-weight:700;">${posLabel}</span>`;
        h+=`<span style="font-family:var(--mono);font-weight:600;width:64px;text-align:right;">${Math.round(p.meta).toLocaleString()}</span></div>`;
      });
      if (side.d.pickAssets.length) {
        h += `<div style="margin:10px 0 4px 0;padding-top:6px;border-top:1px solid var(--border);font-size:0.66rem;color:${GC.PICKS};font-weight:700;">Draft Picks (${side.d.pickAssets.length})</div>`;
        side.d.pickAssets.forEach((p, i) => {
          const pickHint = (p.valueToken && p.valueToken !== p.name)
            ? `<span style="display:block;color:var(--subtext);font-size:0.58rem;">→ ${p.valueToken}</span>`
            : '';
        h += `<div style="display:flex;gap:6px;align-items:center;padding:3px 6px;font-size:0.72rem;border-bottom:1px solid var(--border-dim);">`;
          h += `<span style="width:18px;color:var(--subtext);font-family:var(--mono);font-size:0.62rem;">${i+1}</span>`;
          h += `<span style="font-weight:600;flex:1;">${p.name}${pickHint}</span>`;
          h += `<span style="color:${GC.PICKS};font-family:var(--mono);font-size:0.6rem;font-weight:700;">PICK</span>`;
          h += `<span style="font-family:var(--mono);font-weight:600;width:64px;text-align:right;">${Math.round(p.meta).toLocaleString()}</span></div>`;
        });
      }
      h+='</div></div>';
    });
    h += '</div>';
    c.innerHTML = h;
  }

  // ── KTC TRADE DB ──
  function buildKtcTradesView() {
    const c = document.getElementById('ktcTradesList'); if(!c) return;
    const trades = loadedData?.ktcCrowd?.trades || [];
    if (!trades.length) { c.innerHTML='<p style="color:var(--subtext);font-size:0.78rem;">No KTC trade data. Run scraper with KTC enabled.</p>'; return; }
    _renderKtcTrades(trades, c);
  }
  function filterKtcTrades() {
    const q = (document.getElementById('ktcTradeSearch')?.value||'').toLowerCase().trim();
    const trades = loadedData?.ktcCrowd?.trades || [];
    const c = document.getElementById('ktcTradesList'); if(!c) return;
    if (!q) { _renderKtcTrades(trades,c); return; }
    _renderKtcTrades(trades.filter(t=>t.sides?.some(s=>s.players?.some(p=>p.toLowerCase().includes(q)))), c);
  }
  function _renderKtcTrades(trades, c) {
    if (!trades.length) { c.innerHTML='<p style="color:var(--subtext);">No trades match.</p>'; return; }
    let h = `<div style="font-size:0.66rem;color:var(--subtext);margin-bottom:8px;">${trades.length.toLocaleString()} trades</div>`;
    h += '<div style="overflow:auto;"><table style="width:100%;border-collapse:collapse;font-size:0.74rem;">';
    h += '<thead><tr>';
    h += '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">Date</th>';
    h += '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">Side A</th>';
    h += '<th style="text-align:right;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">A Value</th>';
    h += '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">Side B</th>';
    h += '<th style="text-align:right;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">B Value</th>';
    h += '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">Format</th>';
    h += '</tr></thead><tbody>';

    trades.slice(0, 50).forEach(t => {
      if (!t.sides || t.sides.length < 2) return;
      const sideA = t.sides[0]?.players || [];
      const sideB = t.sides[1]?.players || [];
      const sideAVal = sideA.reduce((sum, p) => sum + _quickVal(p), 0);
      const sideBVal = sideB.reduce((sum, p) => sum + _quickVal(p), 0);
      const sideAText = sideA.map(p => {
        const v = _quickVal(p);
        return `<div><span style="font-weight:600;">${p}</span>${v > 0 ? ` <span style="font-family:var(--mono);font-size:0.64rem;color:var(--subtext);">${v.toLocaleString()}</span>` : ''}</div>`;
      }).join('') || '—';
      const sideBText = sideB.map(p => {
        const v = _quickVal(p);
        return `<div><span style="font-weight:600;">${p}</span>${v > 0 ? ` <span style="font-family:var(--mono);font-size:0.64rem;color:var(--subtext);">${v.toLocaleString()}</span>` : ''}</div>`;
      }).join('') || '—';

      const s = t.settings || {};
      const parts = [];
      if (s.teams) parts.push(`${s.teams} Teams`);
      if (s.sf) parts.push('SF');
      if (s.tep) parts.push('TE+');
      const fmt = parts.join(' · ') || '—';
      const dt = String(t.date || '');
      const dtLabel = dt ? dt.slice(0, 10) : '—';

      h += '<tr style="border-bottom:1px solid var(--border-dim);">';
      h += `<td data-sort-value="${dt.replace(/"/g, '&quot;')}" style="padding:6px;font-family:var(--mono);color:var(--subtext);white-space:nowrap;">${dtLabel}</td>`;
      h += `<td style="padding:6px;min-width:220px;">${sideAText}</td>`;
      h += `<td data-sort-value="${sideAVal}" style="padding:6px;text-align:right;font-family:var(--mono);font-weight:600;">${sideAVal > 0 ? sideAVal.toLocaleString() : '—'}</td>`;
      h += `<td style="padding:6px;min-width:220px;">${sideBText}</td>`;
      h += `<td data-sort-value="${sideBVal}" style="padding:6px;text-align:right;font-family:var(--mono);font-weight:600;">${sideBVal > 0 ? sideBVal.toLocaleString() : '—'}</td>`;
      h += `<td style="padding:6px;font-size:0.66rem;color:var(--muted);font-family:var(--mono);white-space:nowrap;">${fmt}</td>`;
      h += '</tr>';
    });
    h += '</tbody></table></div>';
    if (trades.length > 50) h += `<div style="text-align:center;padding:10px;color:var(--subtext);font-size:0.72rem;">Showing 50 of ${trades.length}</div>`;
    c.innerHTML = h;
  }
  function _quickVal(name) {
    if (!loadedData?.players || !name) return 0;
    const r = computeMetaValueForPlayer(name);
    if (r && isFinite(r.metaValue) && r.metaValue > 0) return Math.round(r.metaValue);
    return 0;
  }

  // ── KTC WAIVER DB ──
  function buildKtcWaiversView() {
    const c = document.getElementById('ktcWaiversList'); if(!c) return;
    const waivers = loadedData?.ktcCrowd?.waivers || [];
    if (!waivers.length) { c.innerHTML='<p style="color:var(--subtext);font-size:0.78rem;">No KTC waiver data. Run scraper with KTC enabled.</p>'; return; }
    _renderKtcWaivers(waivers, c);
  }
  function filterKtcWaivers() {
    const q = (document.getElementById('ktcWaiverSearch')?.value||'').toLowerCase().trim();
    const waivers = loadedData?.ktcCrowd?.waivers || [];
    const c = document.getElementById('ktcWaiversList'); if(!c) return;
    if(!q){_renderKtcWaivers(waivers,c);return;}
    _renderKtcWaivers(waivers.filter(w=>(w.added||'').toLowerCase().includes(q)||(w.dropped||'').toLowerCase().includes(q)),c);
  }
  function _renderKtcWaivers(waivers, c) {
    if(!waivers.length){c.innerHTML='<p style="color:var(--subtext);">No waivers match.</p>';return;}
    let h=`<div style="font-size:0.66rem;color:var(--subtext);margin-bottom:8px;">${waivers.length.toLocaleString()} waivers</div>`;
    h += '<div style="overflow:auto;"><table style="width:100%;border-collapse:collapse;font-size:0.74rem;">';
    h += '<thead><tr>';
    h += '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">Date</th>';
    h += '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">Added</th>';
    h += '<th style="text-align:right;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">Bid</th>';
    h += '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">Dropped</th>';
    h += '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--border);font-size:0.62rem;color:var(--subtext);text-transform:uppercase;letter-spacing:0.06em;">Format</th>';
    h += '</tr></thead><tbody>';
    waivers.slice(0,50).forEach(w=>{
      const av = _quickVal(w.added || '');
      const bidDisplay = w.bidPct ? w.bidPct : (w.bid ? `$${w.bid}` : '—');
      let bidSort = 0;
      if (w.bidPct) {
        const p = parseFloat(String(w.bidPct).replace('%', ''));
        if (isFinite(p)) bidSort = p;
      } else if (isFinite(Number(w.bid))) {
        bidSort = Number(w.bid);
      }
      const dt = String(w.date || '');
      const dtLabel = dt ? dt.slice(0, 10) : '—';
      const s = w.settings || {};
      const parts = [];
      if (s.teams) parts.push(`${s.teams} Teams`);
      if (s.sf) parts.push('SF');
      if (s.tep) parts.push('TE+');
      const fmt = parts.join(' · ') || '—';

      h += '<tr style="border-bottom:1px solid var(--border-dim);">';
      h += `<td data-sort-value="${dt.replace(/"/g, '&quot;')}" style="padding:6px;font-family:var(--mono);color:var(--subtext);white-space:nowrap;">${dtLabel}</td>`;
      h += `<td style="padding:6px;font-weight:700;">${w.added || '—'}${av > 0 ? ` <span style="font-family:var(--mono);font-size:0.62rem;color:var(--subtext);">${av.toLocaleString()}</span>` : ''}</td>`;
      h += `<td data-sort-value="${bidSort}" style="padding:6px;text-align:right;font-family:var(--mono);color:var(--green);font-weight:600;white-space:nowrap;">${bidDisplay}</td>`;
      h += `<td style="padding:6px;color:var(--subtext);">${w.dropped || '—'}</td>`;
      h += `<td style="padding:6px;font-size:0.66rem;color:var(--muted);font-family:var(--mono);white-space:nowrap;">${fmt}</td>`;
      h += '</tr>';
    });
    h += '</tbody></table></div>';
    if(waivers.length>50) h+=`<div style="text-align:center;padding:10px;color:var(--subtext);font-size:0.72rem;">Showing 50 of ${waivers.length}</div>`;
    c.innerHTML=h;
  }
