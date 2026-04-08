/*
 * Runtime Module: 00-core-shell.js
 * Core constants, tabs, and shared helpers.
 * Extracted from legacy monolithic inline runtime to keep live behavior intact.
 */


  // ── SITES ──
  const sites = [
    { key:'ktc',          label:'KTC',           defaultMax:9999,  defaultInclude:true,  defaultWeight:1.2, mode:'value',   tep:true },
    { key:'idpTradeCalc', label:'IDP Trade',     defaultMax:9998,  defaultInclude:true,  defaultWeight:1.0, mode:'value',   tep:true },
  ];

  // ── NAMED CONSTANTS ──
  const MAX_PLAYERS = 20;
  const COMPOSITE_SCALE = 9999;          // max composite value
  const Z_FLOOR = -2.0;                  // z-score floor (bottom ~2.3% of site)
  const Z_CEILING = 4.0;                 // z-score ceiling (preserves elite separation)
  const FUZZY_MATCH_THRESHOLD = 0.78;    // minimum similarity score for name matching
  // Dynamic tier-break tuning (replaces fixed % cliff).
  const TIER_BREAK_MIN_REL = 0.032;       // minimum relative gap considered for a break
  const TIER_BREAK_MAX_REL = 0.16;        // cap dynamic threshold in ultra-flat columns
  const TIER_BREAK_MIN_ABS = 110;         // minimum absolute value gap for canonical 0-9999 values
  const TIER_BREAK_RANGE_FRACTION = 0.012; // scale-aware absolute gap floor by column range
  const TIER_BREAK_LOCAL_STRENGTH = 1.85; // local-cliff ratio vs neighboring gaps
  const TIER_BREAK_MIN_SIZE = 4;          // minimum rows per tier to prevent fragmentation
  const TIER_BREAK_MAX_TIERS = 12;        // hard safety cap for tier count
  const SINGLE_SOURCE_DISCOUNT = 0.88;   // baseline discount for players on only 1 site
  const OUTLIER_TRIM_GAP = 0.18;         // trim only true edge outliers
  const ELITE_NORM_THRESHOLD = 0.91;     // start elite expansion only at stronger consensus
  const ELITE_BOOST_MAX = 0.12;          // cap elite expansion at +12.0%
  const IDP_VALUE_HEADROOM_FRACTION = 0.18; // limit IDP synthetic headroom above value-site cap
  const MIN_EDGE_PCT = 15;                // minimum % diff to show BUY/SELL badge (was 5, raised to reduce noise)
  const RANK_OFFSET = 27;                // rank-to-value curve: offset
  const RANK_DIVISOR = 28;               // rank-to-value curve: divisor
  const RANK_EXPONENT = -0.66;           // rank-to-value curve: power
  const IDP_ANCHOR_DEFAULT = 6250;       // IDP rank #1 = 6250 (~2 early 1sts)
  const IDP_MAX_RANK = 384;              // IDP rank curve: max rank
  const IDP_POWER = 3.28;                // IDP rank curve: steepness
  const IDP_FACTOR = 0.57;               // IDP scaling factor vs offense
  const RANK_CURVE_MIN_SOURCE_COUNT = 10;
  const RANK_CURVE_MIN_TARGET_COUNT = 24;
  const DEFAULT_ALPHA = 1.678;           // star player bonus exponent
  const DEFAULT_TOLERANCE = 0.05;        // 5% trade tolerance
  const DEFAULT_TEAM_NAME = 'Draft Daddies';
  const NATIVE_CANONICAL_VALUE_SITES = new Set(['ktc', 'idpTradeCalc']);
  const ROOKIE_ONLY_DLF_SITE_KEYS = new Set();
  const STORAGE_KEY = 'dynastyCalcV5';
  const RECENT_PLAYERS_KEY = 'dynasty_recent_players_v1';
  const RECENT_SEARCHES_KEY = 'dynasty_recent_searches_v1';
  const TRADE_DRAFT_KEY = 'dynasty_trade_draft_v1';
  const ACTIVE_TAB_KEY = 'dynasty_active_tab_v1';
  const MOBILE_DEFAULT_LANDING_TAB = 'calculator';
  const MOBILE_PREFS_KEY = 'dynasty_mobile_prefs_v1';
  const MOBILE_MORE_SECTION_KEY = 'dynasty_mobile_more_section_v1';
  const MOBILE_LEAGUE_SUB_KEY = 'dynasty_mobile_league_sub_v1';
  const MOBILE_MORE_ROSTER_VIEW_KEY = 'dynasty_mobile_more_roster_view_v1';
  const MOBILE_MORE_TRADES_VIEW_KEY = 'dynasty_mobile_more_trades_view_v1';
  const MOBILE_POWER_MODE_KEY = 'dynasty_mobile_power_mode_v1';
  const MOBILE_RANKINGS_QUICK_SIDE_KEY = 'dynasty_rankings_quick_trade_side_v1';
  const MOBILE_POWER_MODE_DEFAULT = true;
  const PREV_TREND_STAMP_KEY = 'dynasty_prev_stamp';
  const RANKINGS_POSITION_FILTER_OPTIONS = ['ALL', 'OFF', 'IDP', 'QB', 'RB', 'WR', 'TE', 'LB', 'DL', 'DB'];
  const RANKINGS_POSITION_FILTER_LABELS = {
    ALL: 'All',
    OFF: 'Offense',
    IDP: 'IDP',
    QB: 'QB',
    RB: 'RB',
    WR: 'WR',
    TE: 'TE',
    LB: 'LB',
    DL: 'DL',
    DB: 'DB',
  };
  async function logoutJasonSession() {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
      });
    } catch (_) {
      // Intentionally ignore logout API errors; still return to landing.
    }
    window.location.href = '/';
  }

  let recalcTimer = null;
  let settingsPersistTimer = null;
  let currentRankingsFilter = 'ALL';
  let rankingsSortAsc = false;
  let activeTabId = 'calculator';
  let globalSearchTargetSide = '';
  let dataFreshnessDetailsOpen = false;
  let mobileMoreSection = 'edge';
  let mobileMoreRosterView = 'board';
  let mobileMoreTradesView = 'history';
  let mobilePowerModeEnabled = false;
  let rankingsExtraFilters = {
    picksOnly: false,
    trendingOnly: false,
    ageBucket: 'ALL',
  };
  let tableSortObserver = null;
  let tableSortRefreshQueued = false;
  const RANKINGS_DATA_MODE_LABELS = {
    dynasty: 'Dynasty',
    redraft: 'Redraft',
    ros: 'ROS',
  };
  let rankingsBaseRowsCache = {
    playersRef: null,
    key: '',
    rows: [],
  };
  let rankingsTopKtcCache = {
    playersRef: null,
    limit: 0,
    names: [],
  };
  let rankingsBuildDebounce = null;
  let rankingsQuickTradeSide = 'B';
  const RANKINGS_MOBILE_INITIAL_ROWS = 260;
  const RANKINGS_MOBILE_LOAD_STEP = 220;
  let rankingsMobileVisibleCount = RANKINGS_MOBILE_INITIAL_ROWS;
  let rankingsMobileRowsCache = [];
  let rankingsMobileRenderSignature = '';

  function invalidateRankingsBaseRowsCache() {
    rankingsBaseRowsCache = {
      playersRef: null,
      key: '',
      rows: [],
    };
    rankingsTopKtcCache = {
      playersRef: null,
      limit: 0,
      names: [],
    };
  }

  function queueBuildFullRankings(delayMs = 120) {
    clearTimeout(rankingsBuildDebounce);
    rankingsBuildDebounce = setTimeout(() => {
      buildFullRankings();
    }, Math.max(0, Number(delayMs) || 0));
  }

  function queuePersistSettings(delayMs = 220) {
    clearTimeout(settingsPersistTimer);
    settingsPersistTimer = setTimeout(() => {
      persistSettings();
    }, Math.max(0, Number(delayMs) || 0));
  }

  function getRankingsBaseRowsCacheKey(cfg = []) {
    const dataStamp = String(loadedData?.scrapeTimestamp || loadedData?.date || '');
    const playerCount = Object.keys(loadedData?.players || {}).length;
    const lamStrength = Number(getLAMStrength() || 0).toFixed(3);
    const scarcityStrength = Number(getScarcityStrength() || 0).toFixed(3);
    const teamCount = Number(getLeagueTeamCount() || 0);
    const starterReq = getLeagueStarterRequirements() || {};
    const starterSig = Object.keys(starterReq).sort().map(k => `${k}:${starterReq[k]}`).join(',');
    const cfgSig = cfg
      .map(sc => `${sc.key}:${sc.include ? 1 : 0}:${Number(sc.weight || 0).toFixed(4)}:${Number(sc.max || 0)}`)
      .join('|');
    const pickSig = Object.entries(loadedData?.pickAnchors || {})
      .map(([siteKey, pickMap]) => {
        const vals = Object.values(pickMap || {}).map(v => Number(v)).filter(v => Number.isFinite(v));
        const checksum = vals.reduce((acc, v) => acc + Math.round(v), 0);
        return `${siteKey}:${vals.length}:${checksum}`;
      })
      .join('|');
    return [dataStamp, playerCount, lamStrength, scarcityStrength, teamCount, starterSig, cfgSig, pickSig].join('~');
  }

  function enforceSingleCanonicalTop(rankedRows, sortBasis) {
    if (!Array.isArray(rankedRows) || !rankedRows.length) return rankedRows;
    const mode = String(sortBasis || 'full').toLowerCase();
    const targetField = mode === 'raw'
      ? 'rawComposite'
      : (mode === 'scoring' ? 'scoringComposite' : 'adjustedComposite');
    const topIdx = rankedRows.findIndex(r => Number(r?.[targetField]) >= COMPOSITE_SCALE);
    if (topIdx < 0) return rankedRows;

    for (let i = 0; i < rankedRows.length; i++) {
      if (i === topIdx) continue;
      const row = rankedRows[i];
      if (!row || Number(row[targetField]) < COMPOSITE_SCALE) continue;

      if (targetField === 'rawComposite') {
        row.rawComposite = COMPOSITE_SCALE - 1;
        if (row.adjustment) row.adjustment.rawMarketValue = COMPOSITE_SCALE - 1;
      } else if (targetField === 'scoringComposite') {
        row.scoringComposite = COMPOSITE_SCALE - 1;
        if (row.adjustment) {
          row.adjustment.scoringAdjustedValue = COMPOSITE_SCALE - 1;
          if (row.adjustment.scoring && typeof row.adjustment.scoring === 'object') {
            row.adjustment.scoring.finalAdjustedValue = COMPOSITE_SCALE - 1;
          }
        }
      } else {
        row.adjustedComposite = COMPOSITE_SCALE - 1;
        if (row.adjustment) {
          row.adjustment.finalAdjustedValue = COMPOSITE_SCALE - 1;
          row.adjustment.valueDelta = (COMPOSITE_SCALE - 1) - Math.round(Number(row.adjustment.rawMarketValue || row.rawComposite || 0));
        }
      }
      row.sortValue = getValueByRankingMode(row.adjustment, mode);
    }
    return rankedRows;
  }

  function normalizeRankingsDataMode(mode) {
    const m = String(mode || '').toLowerCase();
    if (m === 'redraft' || m === 'ros') return m;
    return 'dynasty';
  }

  function getRankingsDataMode() {
    const el = document.getElementById('rankingsDataMode');
    return normalizeRankingsDataMode(el?.value || 'dynasty');
  }

  function setRankingsDataMode(mode, opts = {}) {
    const normalized = normalizeRankingsDataMode(mode);
    const el = document.getElementById('rankingsDataMode');
    if (el && el.value !== normalized) el.value = normalized;
    if (opts.persist !== false) persistSettings();
    if (opts.refresh !== false) buildFullRankings();
    return normalized;
  }

  function handleValuationModeChange(mode) {
    setRankingsDataMode(mode, { persist: true, refresh: true });
  }

  // ── GLOBAL TABLE SORT ──
  function isSortableHeader(th) {
    if (!th) return false;
    const table = th.closest('table');
    if (!table) return false;
    if (table.dataset.sortDisabled === '1') return false;
    if (th.dataset.sortDisabled === '1' || th.classList.contains('no-sort')) return false;
    const label = (th.textContent || '').trim();
    if (!label) return false;
    // Respect existing dedicated sort handlers unless explicitly forced.
    if (th.hasAttribute('onclick') && th.dataset.sortForce !== '1') return false;
    return true;
  }

  function markSortableHeaders(root = document) {
    root.querySelectorAll('table th').forEach(th => {
      if (isSortableHeader(th)) th.classList.add('sortable-header');
      else th.classList.remove('sortable-header');
    });
  }

  function queueSortableHeaderRefresh() {
    if (tableSortRefreshQueued) return;
    tableSortRefreshQueued = true;
    requestAnimationFrame(() => {
      tableSortRefreshQueued = false;
      markSortableHeaders(document);
    });
  }

  function headerLogicalIndex(th) {
    const row = th.parentElement;
    if (!row) return -1;
    let idx = 0;
    for (const cell of Array.from(row.children)) {
      if (!(cell instanceof HTMLTableCellElement)) continue;
      if (cell === th) return idx;
      idx += Math.max(1, Number(cell.colSpan) || 1);
    }
    return -1;
  }

  function rowCellByLogicalIndex(row, logicalIdx) {
    if (!row || logicalIdx < 0) return null;
    let idx = 0;
    for (const cell of Array.from(row.cells || [])) {
      const span = Math.max(1, Number(cell.colSpan) || 1);
      if (logicalIdx >= idx && logicalIdx < idx + span) return cell;
      idx += span;
    }
    return null;
  }

  function isChildLikeTableRow(row) {
    if (!(row instanceof HTMLTableRowElement)) return false;
    const cls = (row.className || '').toLowerCase();
    if (/(child|detail|expanded|subrow|sub-row|secondary)/.test(cls)) return true;
    if (row.dataset && (row.dataset.parent || row.dataset.parentRow || row.dataset.childOf)) return true;
    if (row.cells && row.cells.length === 1 && (row.cells[0].colSpan || 1) > 1) return true;
    return false;
  }

  function cellSortText(cell) {
    if (!cell) return '';
    const explicit = cell.dataset.sortValue;
    if (explicit != null && String(explicit).trim() !== '') return String(explicit).trim();
    const input = cell.querySelector('input, select, textarea');
    if (input && typeof input.value === 'string' && input.value.trim() !== '') {
      return input.value.trim();
    }
    return (cell.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function parseSortValue(raw) {
    const s = String(raw ?? '').replace(/\s+/g, ' ').trim();
    if (!s || s === '—' || s === '-' || s.toLowerCase() === 'n/a') {
      return { type: 'empty', num: 0, str: '' };
    }

    const up = s.toUpperCase();
    if (up === 'BUY') return { type: 'num', num: -1, str: s };
    if (up === 'SELL') return { type: 'num', num: 1, str: s };

    // Plain integers must stay numeric (avoid mis-parsing "1".."6" as pick rounds).
    if (/^[+\-]?\d+$/.test(s)) {
      return { type: 'num', num: Number(s), str: s };
    }

    // Pick labels: 2026 Pick 1.03, 2027 Early 1st, etc.
    try {
      if (typeof parsePickToken === 'function') {
        const info = parsePickToken(s);
        if (info) {
          const year = Number.isFinite(info.year) ? info.year : 0;
          if (info.kind === 'slot') {
            const slot = Number.isFinite(info.slot) ? info.slot : 0;
            return { type: 'num', num: (year * 10000) + (info.round * 100) + slot, str: s };
          }
          const tierOrd = { early: 1, mid: 2, late: 3 }[String(info.tier || 'mid').toLowerCase()] || 2;
          return { type: 'num', num: (year * 10000) + (info.round * 100) + tierOrd, str: s };
        }
      }
    } catch (_) {}

    // Date-ish strings.
    if (/^\d{4}[-/]\d{2}[-/]\d{2}/.test(s) || s.includes('T')) {
      const ts = Date.parse(s);
      if (!Number.isNaN(ts)) return { type: 'num', num: ts, str: s };
    }

    // Trend and percentage strings (e.g. "↗ +4.2%").
    if ((s.includes('%') || s.includes('↗') || s.includes('↘')) && /[-+]?\d+(?:\.\d+)?/.test(s)) {
      const m = s.match(/[-+]?\d+(?:\.\d+)?/);
      if (m) {
        let num = Number(m[0]);
        // Some trend cells use arrows without an explicit sign.
        if (!/[-+]/.test(m[0])) {
          if (s.includes('↘')) num = -Math.abs(num);
          else if (s.includes('↗')) num = Math.abs(num);
        }
        return { type: 'num', num, str: s };
      }
    }

    // Numeric strings with $, commas, %, parentheses.
    let cleaned = s.replace(/\u2212/g, '-').trim();
    let sign = 1;
    if (/^\(.*\)$/.test(cleaned)) {
      sign = -1;
      cleaned = cleaned.slice(1, -1);
    }
    cleaned = cleaned.replace(/[$€£,%]/g, '').replace(/,/g, '').trim();
    const suffixNum = cleaned.match(/^([+\-]?\d+(?:\.\d+)?)([KMB])$/i);
    if (suffixNum) {
      const base = Number(suffixNum[1]);
      const mult = /k/i.test(suffixNum[2]) ? 1e3 : /m/i.test(suffixNum[2]) ? 1e6 : 1e9;
      if (isFinite(base)) return { type: 'num', num: sign * base * mult, str: s };
    }
    if (/^[+\-]?\d+(?:\.\d+)?$/.test(cleaned)) {
      return { type: 'num', num: sign * Number(cleaned), str: s };
    }

    // Leading numeric fallback for mixed cells like "12 / 75" or "1,240 pts".
    const leadingNum = cleaned.match(/^([+\-]?\d[\d,]*(?:\.\d+)?)([KMB])?(?:\b|[^A-Za-z])/i);
    if (leadingNum) {
      const base = Number(String(leadingNum[1]).replace(/,/g, ''));
      if (isFinite(base)) {
        const mult = leadingNum[2]
          ? (/k/i.test(leadingNum[2]) ? 1e3 : /m/i.test(leadingNum[2]) ? 1e6 : 1e9)
          : 1;
        return { type: 'num', num: sign * base * mult, str: s };
      }
    }

    // Text with trailing rank-like number, e.g. "QB12".
    const tn = s.match(/^([A-Za-z]+)\s*#?(\d+)$/);
    if (tn) {
      return { type: 'textnum', num: Number(tn[2]), str: tn[1].toLowerCase() };
    }

    return { type: 'text', num: 0, str: s.toLowerCase() };
  }

  function compareSortValues(a, b) {
    if (a.type === 'empty' && b.type === 'empty') return 0;
    if (a.type === 'empty') return 1;
    if (b.type === 'empty') return -1;

    if (a.type === 'num' && b.type === 'num') return a.num - b.num;

    if (a.type === 'textnum' && b.type === 'textnum') {
      const t = a.str.localeCompare(b.str, undefined, { numeric: true, sensitivity: 'base' });
      if (t !== 0) return t;
      return a.num - b.num;
    }

    if (a.type === 'num' && b.type !== 'num') return -1;
    if (b.type === 'num' && a.type !== 'num') return 1;

    return a.str.localeCompare(b.str, undefined, { numeric: true, sensitivity: 'base' });
  }

  function isParsedSortEmpty(v) {
    return !!v && v.type === 'empty';
  }

  function medianNumber(values) {
    const nums = (values || []).filter(v => Number.isFinite(v)).slice().sort((a, b) => a - b);
    if (!nums.length) return 0;
    const mid = Math.floor(nums.length / 2);
    return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
  }

  function computeTierBreakIndexesFromOrderedValues(values = []) {
    const breaks = new Set();
    if (!Array.isArray(values) || values.length < 2) return breaks;

    const numericEntries = [];
    values.forEach((v, idx) => {
      const n = Number(v);
      if (Number.isFinite(n)) numericEntries.push({ idx, value: n });
    });
    if (numericEntries.length < 2) return breaks;

    // Keep a hard separator when numeric values end and empty/non-numeric rows begin.
    for (let i = 1; i < values.length; i++) {
      const prevNum = Number(values[i - 1]);
      const curNum = Number(values[i]);
      if (Number.isFinite(prevNum) && !Number.isFinite(curNum)) {
        breaks.add(i);
        break;
      }
    }

    const gaps = [];
    for (let i = 1; i < numericEntries.length; i++) {
      const prev = Number(numericEntries[i - 1].value);
      const cur = Number(numericEntries[i].value);
      const absGap = Math.abs(prev - cur);
      const relGap = absGap / Math.max(Math.abs(prev), Math.abs(cur), 1);
      gaps.push({
        numericPos: i, // break would occur before numericEntries[i]
        absGap,
        relGap,
      });
    }
    if (!gaps.length) return breaks;

    const relGaps = gaps.map(g => g.relGap);
    const medianRel = medianNumber(relGaps);
    const madRel = medianNumber(relGaps.map(v => Math.abs(v - medianRel)));
    const dynamicRelBase = clampValue(medianRel + (madRel * 1.35), TIER_BREAK_MIN_REL, TIER_BREAK_MAX_REL);

    const topVal = Number(numericEntries[0].value);
    const bottomVal = Number(numericEntries[numericEntries.length - 1].value);
    const valueRange = Math.abs(topVal - bottomVal);
    const absFloor = Math.max(TIER_BREAK_MIN_ABS, valueRange * TIER_BREAK_RANGE_FRACTION);

    const minTierSize = Math.max(2, TIER_BREAK_MIN_SIZE);
    const maxTiers = Math.max(2, Math.min(TIER_BREAK_MAX_TIERS, Math.ceil(numericEntries.length / minTierSize)));
    let tierCount = 1;
    let lastBreakNumericPos = 0;

    for (let gi = 0; gi < gaps.length; gi++) {
      const g = gaps[gi];
      if (tierCount >= maxTiers) break;

      const rowsSinceLastBreak = g.numericPos - lastBreakNumericPos;
      const rowsRemaining = numericEntries.length - g.numericPos;
      if (rowsSinceLastBreak < minTierSize || rowsRemaining < minTierSize) continue;

      const prevLocal = gaps[gi - 1]?.relGap ?? medianRel;
      const nextLocal = gaps[gi + 1]?.relGap ?? medianRel;
      const localBase = Math.max(0.0001, (prevLocal + nextLocal) / 2);
      const localStrength = g.relGap / localBase;

      const topBias = g.numericPos <= 12 ? 0.90 : (g.numericPos <= 24 ? 0.96 : 1.0);
      const relThreshold = Math.max(TIER_BREAK_MIN_REL, dynamicRelBase * topBias);
      const strongLocalCliff = (
        g.relGap >= (TIER_BREAK_MIN_REL * 1.15) &&
        g.absGap >= TIER_BREAK_MIN_ABS &&
        localStrength >= TIER_BREAK_LOCAL_STRENGTH
      );
      const strongGlobalGap = (
        g.relGap >= relThreshold &&
        g.absGap >= (absFloor * 0.85)
      );

      if (!strongLocalCliff && !strongGlobalGap) continue;

      const breakRowIdx = numericEntries[g.numericPos].idx;
      breaks.add(breakRowIdx);
      tierCount += 1;
      lastBreakNumericPos = g.numericPos;
    }

    return breaks;
  }

  function tableLogicalColumnCount(table, fallbackRow) {
    const headRow = table?.tHead?.rows?.[0];
    const cells = headRow ? Array.from(headRow.cells || []) : Array.from(fallbackRow?.cells || []);
    let count = 0;
    cells.forEach(cell => {
      count += Math.max(1, Number(cell?.colSpan) || 1);
    });
    return count || Math.max(1, Number(fallbackRow?.cells?.length) || 1);
  }

  function rebuildRankingsTiersFromSortedColumn(table, sortCol) {
    const tbody = table?.tBodies?.[0] || table?.querySelector('tbody');
    if (!tbody || tbody.id !== 'rookieBody') return;

    // Always remove stale separators first so we don't leave orphan tier rows.
    Array.from(tbody.querySelectorAll('tr.tier-separator')).forEach(r => r.remove());

    const dataRows = Array.from(tbody.rows || []).filter(r =>
      r instanceof HTMLTableRowElement &&
      !r.classList.contains('tier-separator') &&
      r.cells && r.cells.length > 0
    );
    if (dataRows.length < 2) return;

    const metrics = dataRows.map(row => {
      const cell = rowCellByLogicalIndex(row, sortCol);
      const parsed = parseSortValue(cellSortText(cell));
      return { row, parsed };
    });

    const numericCount = metrics.filter(m => m.parsed?.type === 'num' && isFinite(m.parsed?.num)).length;
    // Only render tiers when this sort column has enough numeric signal.
    if (numericCount < 2) return;

    const colSpan = tableLogicalColumnCount(table, dataRows[0]);
    const tierBreaks = computeTierBreakIndexesFromOrderedValues(
      metrics.map(m => (m.parsed?.type === 'num' && Number.isFinite(m.parsed?.num)) ? Number(m.parsed.num) : NaN)
    );

    let tierNum = 1;
    const inserts = [];
    for (let i = 0; i < metrics.length; i++) {
      if (i > 0 && tierBreaks.has(i)) {
        tierNum += 1;
        inserts.push({ before: metrics[i].row, tier: tierNum });
      }
      metrics[i].row.dataset.tierNum = String(tierNum);
    }

    inserts.forEach(item => {
      const sepTr = document.createElement('tr');
      sepTr.className = 'tier-separator';
      sepTr.innerHTML = `<td colspan="${colSpan}"><span class="tier-label">── Tier ${item.tier} ──</span></td>`;
      tbody.insertBefore(sepTr, item.before);
    });
  }

  function sortTableByHeader(th) {
    if (!isSortableHeader(th)) return;
    const table = th.closest('table');
    if (!table) return;
    const tbody = table.tBodies?.[0] || table.querySelector('tbody');
    if (!tbody) return;

    const col = headerLogicalIndex(th);
    if (col < 0) return;

    const rows = Array.from(tbody.rows || []);
    if (rows.length < 2) return;

    const sortableGroups = [];
    const prefixRows = [];
    const suffixRows = [];
    let lastSortableGroup = null;

    rows.forEach((row, idx) => {
      if (!(row instanceof HTMLTableRowElement)) return;
      if (row.classList.contains('tier-separator')) return; // remove tier separators once manually sorted
      if (!row.cells || row.cells.length === 0) return;
      const cell = rowCellByLogicalIndex(row, col);
      const childLike = isChildLikeTableRow(row);
      const sortableLeader = Boolean(cell) && !childLike;
      if (sortableLeader) {
        const group = {
          rows: [row],
          idx,
          parsed: parseSortValue(cellSortText(cell)),
        };
        sortableGroups.push(group);
        lastSortableGroup = group;
      } else if (childLike && lastSortableGroup) {
        lastSortableGroup.rows.push(row);
      } else if (sortableGroups.length === 0) {
        prefixRows.push(row);
        lastSortableGroup = null;
      } else {
        suffixRows.push(row);
        lastSortableGroup = null;
      }
    });

    if (sortableGroups.length < 2) return;

    const prevCol = Number(table.dataset.sortCol ?? -1);
    const prevDir = table.dataset.sortDir === 'asc' ? 'asc' : 'desc';
    let dir = 'asc';
    if (prevCol === col) {
      dir = prevDir === 'asc' ? 'desc' : 'asc';
    } else {
      const sample = sortableGroups.find(x => x.parsed.type !== 'empty');
      dir = sample && sample.parsed.type === 'num' ? 'desc' : 'asc';
    }
    const m = dir === 'asc' ? 1 : -1;

    sortableGroups.sort((a, b) => {
      // Keep empties at the bottom for both asc and desc.
      const aEmpty = isParsedSortEmpty(a.parsed);
      const bEmpty = isParsedSortEmpty(b.parsed);
      if (aEmpty && bEmpty) return a.idx - b.idx;
      if (aEmpty) return 1;
      if (bEmpty) return -1;

      const cmp = compareSortValues(a.parsed, b.parsed);
      if (cmp !== 0) return cmp * m;
      return a.idx - b.idx;
    });

    prefixRows.forEach(r => tbody.appendChild(r));
    sortableGroups.forEach(group => {
      group.rows.forEach(r => tbody.appendChild(r));
    });
    suffixRows.forEach(r => tbody.appendChild(r));

    table.dataset.sortCol = String(col);
    table.dataset.sortDir = dir;
    table.querySelectorAll('th').forEach(h => h.classList.remove('sorted-asc', 'sorted-desc'));
    th.classList.add(dir === 'asc' ? 'sorted-asc' : 'sorted-desc');

    // Rankings table: reflow tier separators using the active sort column.
    rebuildRankingsTiersFromSortedColumn(table, col);
  }

  function initGlobalTableSorting() {
    document.addEventListener('click', (event) => {
      const th = event.target.closest('th');
      if (!th) return;
      if (!isSortableHeader(th)) return;
      sortTableByHeader(th);
    });

    markSortableHeaders(document);
    if (!tableSortObserver) {
      tableSortObserver = new MutationObserver((mutations) => {
        for (const m of mutations) {
          if (m.type === 'childList' && (m.addedNodes.length || m.removedNodes.length)) {
            queueSortableHeaderRefresh();
            break;
          }
        }
      });
      if (document.body) {
        tableSortObserver.observe(document.body, { childList: true, subtree: true });
      }
    }
  }

  // ── COLLAPSE ──
  const colState = {};

  function toggleCollapse(id) {
    const body = document.getElementById('body-' + id);
    const chev = document.getElementById('chev-' + id);
    const opening = !colState[id];
    colState[id] = opening;
    if (opening) {
      body.style.maxHeight = body.scrollHeight + 'px';
      setTimeout(() => { body.style.maxHeight = 'none'; }, 300);
      chev.classList.add('open');
      body.classList.remove('collapsed');
    } else {
      body.style.maxHeight = body.scrollHeight + 'px';
      requestAnimationFrame(() => {
        body.style.maxHeight = '0px';
        body.classList.add('collapsed');
      });
      chev.classList.remove('open');
    }
  }

  // ── TABS ──
  function isMobileViewport() {
    return window.matchMedia('(max-width: 920px)').matches;
  }

  function getMobilePowerModeEnabled() {
    return !!mobilePowerModeEnabled;
  }

  function syncMobilePowerModeControls() {
    const enabled = getMobilePowerModeEnabled();
    const ids = ['mobilePowerModeToggle', 'mobilePowerModeToggleMore'];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.checked = enabled;
    });
    const tradeBtn = document.getElementById('mobilePowerModeQuickBtn');
    if (tradeBtn) {
      tradeBtn.textContent = enabled ? 'Power: On' : 'Power: Off';
      tradeBtn.classList.toggle('primary', enabled);
    }
  }

  function setMobilePowerMode(on, opts = {}) {
    mobilePowerModeEnabled = !!on;
    document.body.classList.toggle('mobile-power-mode', mobilePowerModeEnabled);
    syncMobilePowerModeControls();

    if (opts.persist !== false) {
      try { localStorage.setItem(MOBILE_POWER_MODE_KEY, mobilePowerModeEnabled ? '1' : '0'); } catch (_) {}
      persistSettings();
    }
    if (opts.refresh !== false) {
      if (activeTabId === 'rookies') buildFullRankings();
      if (activeTabId === 'edge') buildEdgeTable();
      if (activeTabId === 'more') buildMoreHub();
      updateMobileChrome(activeTabId);
    }
  }

  function hydrateMobilePowerModeFromStorage() {
    let resolved = null;
    try {
      const rawSession = sessionStorage.getItem(STORAGE_KEY);
      if (rawSession) {
        const parsed = JSON.parse(rawSession);
        if (typeof parsed?.mobilePowerMode === 'boolean') {
          resolved = parsed.mobilePowerMode;
        }
      }
    } catch (_) {}

    try {
      const raw = localStorage.getItem(MOBILE_POWER_MODE_KEY);
      if (resolved == null && raw != null) resolved = (raw === '1' || raw === 'true');
    } catch (_) {}
    if (resolved == null) resolved = MOBILE_POWER_MODE_DEFAULT;
    setMobilePowerMode(!!resolved, { persist: false, refresh: false });
  }

  function openFullMobileWorkspace(tabId) {
    const target = String(tabId || '').toLowerCase();
    if (!target) return;
    if (isMobileViewport()) {
      setMobileMoreSection(target, { persist: true, refresh: false });
      setMobilePowerMode(true, { persist: true, refresh: false });
      switchTab(target, { allowLegacyMobile: true });
      if (target === 'league') {
        const leagueSub = getMobileLeagueSubPreference();
        setTimeout(() => {
          try { switchLeagueSub(leagueSub); } catch (_) {}
        }, 0);
      }
      return;
    }
    switchTab(target);
    if (target === 'league') {
      const leagueSub = getMobileLeagueSubPreference();
      try { switchLeagueSub(leagueSub); } catch (_) {}
    }
  }

  function getPrimaryMobileTab(tabId) {
    if (['home', 'rookies', 'calculator', 'more'].includes(tabId)) return tabId;
    return 'more';
  }

  function normalizeMobileMoreSection(section) {
    const s = String(section || '').toLowerCase();
    if (s === 'finder') return 'finder';
    if (s === 'rosters') return 'rosters';
    if (s === 'league') return 'league';
    if (s === 'trades') return 'trades';
    if (s === 'settings') return 'settings';
    return 'edge';
  }

  function normalizeLeagueSubId(section) {
    const s = String(section || '').toLowerCase();
    if (s === 'heatmap') return 'heatmap';
    if (s === 'breakdown') return 'breakdown';
    if (s === 'compare') return 'compare';
    if (s === 'ktctrades' || s === 'ktctrade' || s === 'tradedb') return 'ktcTrades';
    if (s === 'ktcwaivers' || s === 'ktcwaiver' || s === 'waiverdb') return 'ktcWaivers';
    return 'heatmap';
  }

  function getMobileLeagueSubPreference() {
    try {
      return normalizeLeagueSubId(localStorage.getItem(MOBILE_LEAGUE_SUB_KEY) || 'heatmap');
    } catch (_) {
      return 'heatmap';
    }
  }

  function setMobileLeagueSubPreference(section) {
    const normalized = normalizeLeagueSubId(section);
    try { localStorage.setItem(MOBILE_LEAGUE_SUB_KEY, normalized); } catch (_) {}
    return normalized;
  }

  function normalizeMobileMoreRosterSubview(section) {
    const s = String(section || '').toLowerCase();
    if (s === 'targets') return 'targets';
    if (s === 'grades') return 'grades';
    if (s === 'waivers') return 'waivers';
    if (s === 'tendencies') return 'tendencies';
    return 'board';
  }

  function normalizeMobileMoreTradesSubview(section) {
    const s = String(section || '').toLowerCase();
    if (s === 'stats') return 'stats';
    return 'history';
  }

  function setMobileMoreRosterSubview(section, opts = {}) {
    mobileMoreRosterView = normalizeMobileMoreRosterSubview(section);
    if (opts.persist !== false) {
      try { localStorage.setItem(MOBILE_MORE_ROSTER_VIEW_KEY, mobileMoreRosterView); } catch (_) {}
    }
    if (opts.refresh !== false && activeTabId === 'more' && normalizeMobileMoreSection(mobileMoreSection) === 'rosters') {
      renderMobileMoreSection();
    }
  }

  function setMobileMoreTradesSubview(section, opts = {}) {
    mobileMoreTradesView = normalizeMobileMoreTradesSubview(section);
    if (opts.persist !== false) {
      try { localStorage.setItem(MOBILE_MORE_TRADES_VIEW_KEY, mobileMoreTradesView); } catch (_) {}
    }
    if (opts.refresh !== false && activeTabId === 'more' && normalizeMobileMoreSection(mobileMoreSection) === 'trades') {
      renderMobileMoreSection();
    }
  }

  const ROSTER_POSITION_GROUP_KEYS = ['QB','RB','WR','TE','DL','LB','DB'];
  const ROSTER_GROUP_KEYS = [...ROSTER_POSITION_GROUP_KEYS, 'PICKS'];

  function getRosterGroupFilterState(opts = {}) {
    const defaults = new Set(['QB','RB','WR','TE','PICKS']);
    const prefix = typeof opts.prefix === 'string' ? opts.prefix : 'rosterFilter_';
    const state = {};
    ROSTER_GROUP_KEYS.forEach(g => {
      const cb = document.getElementById(prefix + g);
      state[g] = cb ? !!cb.checked : defaults.has(g);
    });
    if (opts.forceIncludePicks != null) state.PICKS = !!opts.forceIncludePicks;
    return state;
  }

  function getMobileMoreRosterGroupState() {
    const state = getRosterGroupFilterState();
    const hasMobileControls = ROSTER_POSITION_GROUP_KEYS.some(g => !!document.getElementById('moreRosterFilter_' + g));
    if (hasMobileControls) {
      ROSTER_POSITION_GROUP_KEYS.forEach(g => {
        const cb = document.getElementById('moreRosterFilter_' + g);
        if (cb) state[g] = !!cb.checked;
      });
    }
    const includePicks = document.getElementById('moreRosterIncludePicks');
    if (includePicks) {
      state.PICKS = !!includePicks.checked;
    } else {
      const picksCb = document.getElementById('moreRosterFilter_PICKS');
      if (picksCb) state.PICKS = !!picksCb.checked;
    }
    return state;
  }

  function setMobileMoreRosterGroupPreset(preset) {
    const key = String(preset || 'all').toLowerCase();
    const enabled = new Set();
    if (key === 'offense') ['QB','RB','WR','TE'].forEach(g => enabled.add(g));
    else if (key === 'idp') ['DL','LB','DB'].forEach(g => enabled.add(g));
    else if (key === 'none') {}
    else ROSTER_POSITION_GROUP_KEYS.forEach(g => enabled.add(g));

    ROSTER_POSITION_GROUP_KEYS.forEach(g => {
      const cb = document.getElementById('moreRosterFilter_' + g);
      if (cb) cb.checked = enabled.has(g);
    });
    const includePicks = document.getElementById('moreRosterIncludePicks');
    if (includePicks && key !== 'none') includePicks.checked = true;
    applyMobileMoreRosterControls(true);
  }

  function applyMobileMoreRosterControls(skipHubRebuild = false) {
    const teamName = String(document.getElementById('moreRosterTeamSelect')?.value || '');
    const valueMode = String(document.getElementById('moreRosterValueModeSelect')?.value || 'full');
    const basisMode = normalizeValueBasis(document.getElementById('moreRosterValueBasisSelect')?.value || getCalculatorValueBasis());
    const basisChanged = basisMode !== getCalculatorValueBasis();
    const mobileState = getMobileMoreRosterGroupState();
    const selectedPosCount = ROSTER_POSITION_GROUP_KEYS.reduce((n, g) => n + (mobileState[g] ? 1 : 0), 0);
    if (selectedPosCount <= 0) {
      ['QB','RB','WR','TE'].forEach(g => { mobileState[g] = true; });
      ROSTER_POSITION_GROUP_KEYS
        .filter(g => !['QB','RB','WR','TE'].includes(g))
        .forEach(g => { mobileState[g] = false; });
      mobileState.PICKS = true;
      ROSTER_POSITION_GROUP_KEYS.forEach(g => {
        const cb = document.getElementById('moreRosterFilter_' + g);
        if (cb) cb.checked = !!mobileState[g];
      });
      const picksCb = document.getElementById('moreRosterIncludePicks');
      if (picksCb) picksCb.checked = true;
    }

    const rosterTeamEl = document.getElementById('rosterMyTeam');
    if (rosterTeamEl && teamName) rosterTeamEl.value = teamName;
    const rosterValueModeEl = document.getElementById('rosterValueMode');
    if (rosterValueModeEl) rosterValueModeEl.value = valueMode;
    if (basisChanged) syncValueBasisControls(basisMode);

    if (teamName) syncGlobalTeam(teamName);
    const needsRosterFilterBootstrap = !document.getElementById('rosterFilter_QB');
    if (needsRosterFilterBootstrap) buildRosterDashboard();

    // buildRosterDashboard creates group checkboxes dynamically; apply toggles after render.
    ROSTER_POSITION_GROUP_KEYS.forEach(g => {
      const dst = document.getElementById('rosterFilter_' + g);
      if (dst) dst.checked = !!mobileState[g];
    });
    const picksDst = document.getElementById('rosterFilter_PICKS');
    if (picksDst) picksDst.checked = !!mobileState.PICKS;
    buildRosterDashboard();
    if (basisChanged) {
      recalculate();
      buildFullRankings();
    }
    persistSettings();
    if (activeTabId === 'home') buildHomeHub();
    if (activeTabId === 'more') {
      if (skipHubRebuild) renderMobileMoreSection();
      else buildMoreHub();
    }
  }

  function applyMobileMoreLeagueControls(skipHubRebuild = false) {
    initLeagueTab();
    const view = setMobileLeagueSubPreference(document.getElementById('moreLeagueViewSelect')?.value || 'heatmap');
    const basisMode = normalizeValueBasis(document.getElementById('moreLeagueValueBasisSelect')?.value || getCalculatorValueBasis());
    const basisChanged = basisMode !== getCalculatorValueBasis();
    if (basisChanged) syncValueBasisControls(basisMode);

    if (view === 'breakdown') {
      const team = String(document.getElementById('moreLeagueBreakdownTeam')?.value || '');
      const el = document.getElementById('breakdownTeamSelect');
      if (el && team) el.value = team;
      const mode = String(document.getElementById('moreLeagueBreakdownMode')?.value || 'grouped');
      const vm = document.getElementById('breakdownViewMode');
      if (vm) vm.value = (mode === 'value' ? 'value' : 'grouped');
    } else if (view === 'compare') {
      const a = String(document.getElementById('moreLeagueCompareA')?.value || '');
      const b = String(document.getElementById('moreLeagueCompareB')?.value || '');
      const aEl = document.getElementById('compareTeamA');
      const bEl = document.getElementById('compareTeamB');
      if (aEl && a) aEl.value = a;
      if (bEl && b) bEl.value = b;
    }

    switchLeagueSub(view);
    if (basisChanged) {
      recalculate();
      buildFullRankings();
    }
    persistSettings();
    if (activeTabId === 'more' && normalizeMobileMoreSection(mobileMoreSection) === 'league') {
      if (skipHubRebuild) renderMobileMoreLeaguePreview(view);
      else renderMobileMoreSection();
    }
  }

  function applyMobileLeagueSearch(kind, value) {
    const needle = String(value || '');
    if (kind === 'trades') {
      const desktop = document.getElementById('ktcTradeSearch');
      if (desktop) desktop.value = needle;
      filterKtcTrades();
    } else {
      const desktop = document.getElementById('ktcWaiverSearch');
      if (desktop) desktop.value = needle;
      filterKtcWaivers();
    }
    renderMobileMoreLeaguePreview(getMobileLeagueSubPreference());
  }

  function applyMobileMoreTradeControls(skipHubRebuild = false) {
    const team = String(document.getElementById('moreTradeTeamFilter')?.value || '');
    const tradeFilter = document.getElementById('tradeTeamFilter');
    if (tradeFilter) tradeFilter.value = team;
    buildTradeHistoryPage();
    persistSettings();
    if (activeTabId === 'more' && normalizeMobileMoreSection(mobileMoreSection) === 'trades') {
      if (skipHubRebuild) renderMobileMoreTradesPreview();
      else renderMobileMoreSection();
    }
  }

  function refreshMobileMoreTendencies() {
    buildTendencies();
    setMobileMoreRosterSubview('tendencies', { persist: true, refresh: true });
  }

  function applyMobileMoreAdvancedSettings() {
    const alpha = Number(document.getElementById('moreSettingsAlphaInput')?.value);
    const lamStrength = Number(document.getElementById('moreSettingsLamInput')?.value);
    const scarcityStrength = Number(document.getElementById('moreSettingsScarcityInput')?.value);
    const tepMultiplier = Number(document.getElementById('moreSettingsTepInput')?.value);
    const zBlend = !!document.getElementById('moreSettingsZBlendToggle')?.checked;

    const alphaInput = document.getElementById('alphaInput');
    const lamInput = document.getElementById('lamStrengthInput');
    const scarcityInput = document.getElementById('scarcityStrengthInput');
    const tepInput = document.getElementById('tepMultiplierInput');
    const zToggle = document.getElementById('zScoreToggle');

    if (alphaInput && Number.isFinite(alpha) && alpha >= 1 && alpha <= 3) alphaInput.value = alpha.toFixed(3);
    if (lamInput && Number.isFinite(lamStrength) && lamStrength >= 0 && lamStrength <= 1) lamInput.value = lamStrength.toFixed(2);
    if (scarcityInput && Number.isFinite(scarcityStrength) && scarcityStrength >= 0 && scarcityStrength <= 1) scarcityInput.value = scarcityStrength.toFixed(2);
    if (tepInput && Number.isFinite(tepMultiplier) && tepMultiplier >= 1 && tepMultiplier <= 2) tepInput.value = tepMultiplier.toFixed(2);
    if (zToggle) zToggle.checked = zBlend;

    saveSettingsAndRecalc();
    buildMoreHub();
  }

  function closeMobileSiteMatrixEditor() {
    const overlay = document.getElementById('mobileSiteMatrixOverlay');
    if (!overlay) return;
    overlay.classList.remove('active');
  }

  function openMobileSiteMatrixEditor() {
    const overlay = document.getElementById('mobileSiteMatrixOverlay');
    const grid = document.getElementById('mobileSiteMatrixGrid');
    const status = document.getElementById('mobileSiteMatrixStatus');
    if (!overlay || !grid) return;
    const cfg = getSiteConfig();
    const cfgByKey = new Map(cfg.map((row) => [row.key, row]));
    grid.innerHTML = sites.map((s) => {
      const rowCfg = cfgByKey.get(s.key) || {
        include: !!s.defaultInclude,
        max: Number(s.defaultMax || 0),
        weight: Number(s.defaultWeight || 1),
        tep: s.tep !== false,
      };
      const desktopRow = document.querySelector(`#siteConfigBody tr[data-site-key="${s.key}"]`);
      const includeDesktop = document.getElementById(`include_${s.key}`);
      const tepDesktop = document.getElementById(`tep_${s.key}`);
      const unavailable = !!desktopRow && desktopRow.style.display === 'none';
      const includeDisabled = !!includeDesktop?.disabled;
      const tepDisabled = !!tepDesktop?.disabled;
      const includeChecked = rowCfg.include ? 'checked' : '';
      const tepChecked = rowCfg.tep ? 'checked' : '';
      const unavailableBadge = unavailable ? '<span class="mobile-site-matrix-badge">No Data</span>' : '<span class="mobile-site-matrix-badge">Live</span>';
      return `
        <div class="mobile-site-matrix-card">
          <div class="mobile-site-matrix-head">
            <div class="mobile-site-matrix-name">${s.label}</div>
            ${unavailableBadge}
          </div>
          <div class="mobile-site-matrix-fields">
            <label class="mobile-site-matrix-field">
              Max
              <input id="mobileSiteMatrix_max_${s.key}" type="number" step="0.01" inputmode="decimal" value="${Number(rowCfg.max || 0)}">
            </label>
            <label class="mobile-site-matrix-field">
              Weight
              <input id="mobileSiteMatrix_weight_${s.key}" type="number" step="0.01" inputmode="decimal" value="${Number(rowCfg.weight || 0)}">
            </label>
          </div>
          <div class="mobile-site-matrix-toggles">
            <label class="mobile-site-matrix-toggle" title="${includeDisabled ? 'Disabled because this source has no loaded data.' : ''}">
              <input id="mobileSiteMatrix_include_${s.key}" type="checkbox" ${includeChecked} ${includeDisabled ? 'disabled' : ''}>
              Include
            </label>
            <label class="mobile-site-matrix-toggle" title="${tepDisabled ? 'TEP locked for this source.' : ''}">
              <input id="mobileSiteMatrix_tep_${s.key}" type="checkbox" ${tepChecked} ${tepDisabled ? 'disabled' : ''}>
              TEP
            </label>
          </div>
        </div>
      `;
    }).join('');
    if (status) status.textContent = 'Changes write to the same site matrix used by desktop rankings and calculator.';
    overlay.classList.add('active');
  }

  function resetMobileSiteMatrixEditorToDefaults() {
    sites.forEach((s) => {
      const inc = document.getElementById(`mobileSiteMatrix_include_${s.key}`);
      const max = document.getElementById(`mobileSiteMatrix_max_${s.key}`);
      const weight = document.getElementById(`mobileSiteMatrix_weight_${s.key}`);
      const tep = document.getElementById(`mobileSiteMatrix_tep_${s.key}`);
      if (inc && !inc.disabled) inc.checked = !!s.defaultInclude;
      if (max) max.value = String(Number(s.defaultMax || 0));
      if (weight) weight.value = String(Number(s.defaultWeight || 0));
      if (tep && !tep.disabled) tep.checked = s.tep !== false;
    });
    const status = document.getElementById('mobileSiteMatrixStatus');
    if (status) status.textContent = 'Defaults loaded in the editor. Tap Apply Matrix to commit.';
  }

  function applyMobileSiteMatrixEditor() {
    sites.forEach((s) => {
      const includeEditor = document.getElementById(`mobileSiteMatrix_include_${s.key}`);
      const maxEditor = document.getElementById(`mobileSiteMatrix_max_${s.key}`);
      const weightEditor = document.getElementById(`mobileSiteMatrix_weight_${s.key}`);
      const tepEditor = document.getElementById(`mobileSiteMatrix_tep_${s.key}`);

      const includeDesktop = document.getElementById(`include_${s.key}`);
      const maxDesktop = document.getElementById(`max_${s.key}`);
      const weightDesktop = document.getElementById(`weight_${s.key}`);
      const tepDesktop = document.getElementById(`tep_${s.key}`);

      if (includeDesktop && includeEditor && !includeDesktop.disabled) includeDesktop.checked = !!includeEditor.checked;
      const maxVal = Number(maxEditor?.value);
      if (maxDesktop && Number.isFinite(maxVal) && maxVal >= 0) maxDesktop.value = String(maxVal);
      const weightVal = Number(weightEditor?.value);
      if (weightDesktop && Number.isFinite(weightVal) && weightVal >= 0) weightDesktop.value = String(weightVal);
      if (tepDesktop && tepEditor && !tepDesktop.disabled) tepDesktop.checked = !!tepEditor.checked;
    });

    markSiteConfigDirty();
    persistSettings();
    recalculate();
    buildFullRankings();
    if (activeTabId === 'more' && normalizeMobileMoreSection(mobileMoreSection) === 'settings') {
      renderMobileMoreSection();
    }
    closeMobileSiteMatrixEditor();
  }

  function renderMobileMoreLeaguePreview(view) {
    const preview = document.getElementById('moreLeaguePreview');
    if (!preview) return;

    let html = '';
    try {
      if (view === 'heatmap') {
        buildPowerRankingsHeatmap();
        html = document.getElementById('powerRankingsHeatmap')?.innerHTML || '';
      } else if (view === 'breakdown') {
        buildTeamBreakdown();
        html = document.getElementById('teamBreakdownContent')?.innerHTML || '';
      } else if (view === 'compare') {
        buildTeamComparison();
        html = document.getElementById('teamComparisonContent')?.innerHTML || '';
      } else if (view === 'ktcTrades') {
        filterKtcTrades();
        html = document.getElementById('ktcTradesList')?.innerHTML || '';
      } else if (view === 'ktcWaivers') {
        filterKtcWaivers();
        html = document.getElementById('ktcWaiversList')?.innerHTML || '';
      }
    } catch (_) {}

    preview.innerHTML = html
      ? `<div class="mobile-embedded-panel">${html}</div>`
      : '<div class="mobile-row-card"><div class="mobile-row-name">No league view data available.</div></div>';
  }

  function renderMobileMoreTradesPreview() {
    const preview = document.getElementById('moreTradesPreview');
    if (!preview) return;
    const mode = normalizeMobileMoreTradesSubview(mobileMoreTradesView);
    const statsDiv = document.getElementById('tradeStats');
    if (mode === 'stats') {
      const statsHtml = statsDiv?.innerHTML || '';
      preview.innerHTML = statsHtml
        ? `<div class="mobile-embedded-panel">${statsHtml}</div>`
        : '<div class="mobile-row-card"><div class="mobile-row-name">No winner/loser stats for this filter.</div></div>';
      return;
    }
    const rows = Array.isArray(tradeHistoryRenderCache) ? tradeHistoryRenderCache : [];
    if (!rows.length) {
      preview.innerHTML = '<div class="mobile-row-card"><div class="mobile-row-name">No trades match this filter.</div></div>';
      return;
    }
    const esc = (v) => String(v ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
    const html = rows.slice(0, 10).map((row, idx) => {
      const sides = Array.isArray(row?.sides) ? row.sides : [];
      const sideHtml = sides.map(side => {
        const isWinner = side === row.winner && row.pctGap >= 3;
        const isLoser = side === row.loser && row.pctGap >= 3;
        const grade = isWinner ? row.winnerGrade : (isLoser ? row.loserGrade : { grade: 'A', color: 'var(--green)', label: 'Fair trade' });
        const borderColor = isWinner ? 'var(--green)' : (isLoser ? 'var(--red)' : 'var(--border)');
        const assets = Array.isArray(side?.items) ? side.items : [];
        const received = assets.slice(0, 4).map(item => esc(item?.name || '')).filter(Boolean).join(', ');
        const extra = assets.length > 4 ? ` +${assets.length - 4}` : '';
        return `
          <div style="border-left:3px solid ${borderColor};padding:8px 10px;margin-top:6px;background:var(--bg-card);border-radius:8px;">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
              <div style="font-weight:700;font-size:0.74rem;">${esc(side?.team || 'Unknown Team')}</div>
              <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-weight:800;font-size:0.82rem;color:${grade?.color || 'var(--text)'};">${esc(grade?.grade || '—')}</span>
                <span style="font-size:0.62rem;color:var(--subtext);">${esc(grade?.label || '')}</span>
              </div>
            </div>
            <div style="font-size:0.66rem;color:var(--subtext);margin-top:4px;">Received</div>
            <div style="font-size:0.68rem;line-height:1.35;margin-top:2px;">${received || 'No mapped assets'}${extra}</div>
          </div>
        `;
      }).join('');

      const winnerLine = row.pctGap >= 3
        ? `${esc(row?.winner?.team || 'Winner')} won by ${Number(row.pctGap || 0).toFixed(1)}%`
        : 'Fair trade (within 3%)';
      const winnerTone = row.pctGap >= 3 ? 'var(--subtext)' : 'var(--green)';

      return `
        <div class="mobile-row-card" style="padding:10px 12px;">
          <div class="mobile-row-head">
            <div>
              <div class="mobile-row-name">Week ${esc(row?.trade?.week ?? '?')} · ${esc(row?.date || '?')}</div>
              <div class="mobile-row-sub" style="color:${winnerTone};">${winnerLine}</div>
            </div>
            <button class="mobile-chip-btn primary" onclick="openHistoricalTradeInBuilder(${idx})">Open Builder</button>
          </div>
          ${sideHtml}
        </div>
      `;
    }).join('');
    preview.innerHTML = html;
  }

  function getMobileTitleForTab(tabId) {
    const legacyMap = {
      edge: 'Edge',
      finder: 'Finder',
      rosters: 'Rosters',
      league: 'League',
      trades: 'Trades',
      settings: 'Settings',
    };
    if (legacyMap[tabId]) return `${legacyMap[tabId]} · Full`;
    const t = getPrimaryMobileTab(tabId);
    if (t === 'home') return 'Home';
    if (t === 'rookies') return 'Ranks';
    if (t === 'calculator') return 'Trade';
    const section = normalizeMobileMoreSection(mobileMoreSection);
    if (section === 'edge') return 'More · Edge';
    if (section === 'finder') return 'More · Finder';
    if (section === 'rosters') return 'More · Teams';
    if (section === 'league') return 'More · League';
    if (section === 'trades') return 'More · Trades';
    if (section === 'settings') return 'More · Settings';
    return 'More';
  }

  function updateMobileChrome(tabId) {
    const titleEl = document.getElementById('mobileScreenTitle');
    const wordmarkEl = document.getElementById('mobileWordmark');
    const isHome = tabId === 'home';
    if (titleEl) {
      titleEl.textContent = getMobileTitleForTab(tabId);
      titleEl.style.display = isHome ? 'none' : '';
    }
    if (wordmarkEl) {
      wordmarkEl.style.display = isHome ? '' : 'none';
    }
    const primary = getPrimaryMobileTab(tabId);
    document.querySelectorAll('.mobile-nav-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mobileTab === primary);
    });
  }

  function switchMobilePrimary(id) {
    switchTab(id);
  }

  function openLegacyTabFromMore(id) {
    if (isMobileViewport()) {
      setMobileMoreSection(id, { persist: true, refresh: true });
      if (getMobilePowerModeEnabled()) {
        switchTab(id, { allowLegacyMobile: true });
      } else {
        switchTab('more');
      }
      return;
    }
    switchTab(id);
  }

  function triggerMobileQuickAction() {
    if (activeTabId !== 'calculator') switchTab('calculator');
    openGlobalSearchForTrade('B');
  }

  function toggleMobilePowerModeFromTrade() {
    const next = !getMobilePowerModeEnabled();
    setMobilePowerMode(next, { persist: true, refresh: true });
    if (next) {
      switchTab('calculator', { allowLegacyMobile: true, persist: false });
    }
  }

  function switchTab(id, opts = {}) {
    const requestedId = id;
    let nextId = id;
    const mobilePrimary = ['home', 'rookies', 'calculator', 'more'];
    const isMobile = isMobileViewport();
    const allowLegacyMobile = !!opts.allowLegacyMobile
      || (isMobile && getMobilePowerModeEnabled() && !mobilePrimary.includes(nextId));
    const redirectedToMore = isMobile && !allowLegacyMobile && !mobilePrimary.includes(nextId);
    if (redirectedToMore) {
      setMobileMoreSection(nextId, { persist: true, refresh: false });
      nextId = 'more';
    }
    if (isMobile && !redirectedToMore && !mobilePrimary.includes(requestedId)) {
      setMobileMoreSection(requestedId, { persist: true, refresh: false });
    }

    closeMobileTradeRowEditor();
    closeMobileSiteMatrixEditor();

    activeTabId = nextId;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === nextId));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + nextId));
    updateMobileChrome(nextId);

    if (opts.persist !== false) {
      try { localStorage.setItem(ACTIVE_TAB_KEY, nextId); } catch(_) {}
    }

    if (nextId === 'home') buildHomeHub();
    if (nextId === 'more') buildMoreHub();
    if (nextId === 'calculator' && isMobileViewport()) { renderMobileTradeWorkspace(); updateMobileTradeTray(); }
    if (nextId === 'rookies') buildRookieRankings();

    // Desktop-only tab execution path for legacy panels.
    if (!redirectedToMore && (!isMobile || allowLegacyMobile)) {
      if (requestedId === 'rosters') buildRosterDashboard();
      if (requestedId === 'trades') buildTradeHistoryPage();
      if (requestedId === 'edge') { checkEdgeGate(); buildEdgeTable(); }
      if (requestedId === 'finder') { checkFinderGate(); }
      if (requestedId === 'league') initLeagueTab();
    }

    if (isMobile && opts.ensureTopOnMobile) {
      requestAnimationFrame(() => {
        try {
          window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
        } catch (_) {
          window.scrollTo(0, 0);
        }
      });
    }
  }

  function normalizeInitialTabFromUrl(rawTab) {
    const v = String(rawTab || '').trim().toLowerCase();
    if (!v) return '';
    const alias = {
      trade: 'calculator',
      calculator: 'calculator',
      ranks: 'rookies',
      rankings: 'rookies',
      rookies: 'rookies',
      home: 'home',
      watch: 'calculator',
      watchlist: 'calculator',
      more: 'more',
      edge: 'edge',
      rosters: 'rosters',
      league: 'league',
      trades: 'trades',
      settings: 'settings',
    };
    return alias[v] || '';
  }

  function getInitialTabFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search || '');
      return normalizeInitialTabFromUrl(params.get('tab') || params.get('view') || '');
    } catch (_) {
      return '';
    }
  }

  // ── 2026 ROOKIE CLASS ──
  const ROOKIES_2026 = [
    // QBs
    {name:"Fernando Mendoza", pos:"QB"}, {name:"Ty Simpson", pos:"QB"},
    {name:"Trinidad Chambliss", pos:"QB"}, {name:"Garrett Nussmeier", pos:"QB"},
    {name:"Carson Beck", pos:"QB"}, {name:"Drew Allar", pos:"QB"},
    {name:"Cole Payton", pos:"QB"}, {name:"Cade Klubnik", pos:"QB"},
    {name:"Taylen Green", pos:"QB"}, {name:"Luke Altmyer", pos:"QB"},
    // RBs
    {name:"Jeremiyah Love", pos:"RB"}, {name:"Jonah Coleman", pos:"RB"},
    {name:"Jadarian Price", pos:"RB"}, {name:"Emmett Johnson", pos:"RB"},
    {name:"Nicholas Singleton", pos:"RB"}, {name:"Kaytron Allen", pos:"RB"},
    {name:"Demond Claiborne", pos:"RB"}, {name:"Mike Washington Jr.", pos:"RB"},
    {name:"Seth McGowan", pos:"RB"}, {name:"Le'Veon Moss", pos:"RB"},
    {name:"Adam Randall", pos:"RB"}, {name:"Roman Hemby", pos:"RB"},
    {name:"J'Mari Taylor", pos:"RB"}, {name:"Jam Miller", pos:"RB"},
    {name:"C.J. Donaldson", pos:"RB"}, {name:"Noah Whittington", pos:"RB"},
    {name:"Jaydn Ott", pos:"RB"}, {name:"Robert Henry Jr.", pos:"RB"},
    {name:"Desmond Reid", pos:"RB"}, {name:"Jamal Haynes", pos:"RB"},
    {name:"Terion Stewart", pos:"RB"},
    // WRs
    {name:"Carnell Tate", pos:"WR"}, {name:"Jordyn Tyson", pos:"WR"},
    {name:"Makai Lemon", pos:"WR"}, {name:"Denzel Boston", pos:"WR"},
    {name:"KC Concepcion", pos:"WR"}, {name:"Chris Bell", pos:"WR"},
    {name:"Omar Cooper Jr.", pos:"WR"}, {name:"Elijah Sarratt", pos:"WR"},
    {name:"Germie Bernard", pos:"WR"}, {name:"Chris Brazzell II", pos:"WR"},
    {name:"Zachariah Branch", pos:"WR"}, {name:"Ja'Kobi Lane", pos:"WR"},
    {name:"Antonio Williams", pos:"WR"}, {name:"Skyler Bell", pos:"WR"},
    {name:"Malachi Fields", pos:"WR"}, {name:"Ted Hurst", pos:"WR"},
    {name:"Deion Burks", pos:"WR"}, {name:"Brenen Thompson", pos:"WR"},
    {name:"Eric McAlister", pos:"WR"}, {name:"C.J. Daniels", pos:"WR"},
    {name:"Kevin Coleman Jr.", pos:"WR"}, {name:"De'Zhaun Stribling", pos:"WR"},
    {name:"Eric Rivers", pos:"WR"}, {name:"Bryce Lance", pos:"WR"},
    {name:"Aaron Anderson", pos:"WR"}, {name:"Barion Brown", pos:"WR"},
    {name:"Josh Cameron", pos:"WR"}, {name:"Noah Thomas", pos:"WR"},
    {name:"Dane Key", pos:"WR"}, {name:"Reggie Virgil", pos:"WR"},
    {name:"Caleb Douglas", pos:"WR"},
    // TEs
    {name:"Kenyon Sadiq", pos:"TE"}, {name:"Eli Stowers", pos:"TE"},
    {name:"Max Klare", pos:"TE"}, {name:"Michael Trigg", pos:"TE"},
    {name:"Jack Endries", pos:"TE"}, {name:"Justin Joly", pos:"TE"},
    {name:"Joe Royer", pos:"TE"}, {name:"Eli Raridon", pos:"TE"},
    {name:"Oscar Delp", pos:"TE"}, {name:"Marlin Klein", pos:"TE"},
    {name:"Tanner Koziol", pos:"TE"},
    // LB
    {name:"Arvell Reese", pos:"LB"}, {name:"Sonny Styles", pos:"LB"},
    {name:"C.J. Allen", pos:"LB"}, {name:"Jacob Rodriguez", pos:"LB"},
    {name:"Jake Golday", pos:"LB"}, {name:"Kyle Louis", pos:"LB"},
    {name:"Anthony Hill Jr.", pos:"LB"}, {name:"Keyshaun Elliott", pos:"LB"},
    {name:"Josiah Trotter", pos:"LB"}, {name:"Deontae Lawson", pos:"LB"},
    {name:"Harold Perkins", pos:"LB"}, {name:"Taurean York", pos:"LB"},
    // EDGE
    {name:"David Bailey", pos:"EDGE"}, {name:"Rueben Bain Jr.", pos:"EDGE"},
    {name:"Cashius Howell", pos:"EDGE"}, {name:"Akheem Mesidor", pos:"EDGE"},
    {name:"T.J. Parker", pos:"EDGE"}, {name:"Keldric Faulk", pos:"EDGE"},
    {name:"R Mason Thomas", pos:"EDGE"}, {name:"Zion Young", pos:"EDGE"},
    {name:"Dani Dennis-Sutton", pos:"EDGE"},
    // DT
    {name:"Caleb Banks", pos:"DT"}, {name:"Peter Woods", pos:"DT"},
    {name:"Kayden McDonald", pos:"DT"}, {name:"Christen Miller", pos:"DT"},
    {name:"Lee Hunter", pos:"DT"},
    // S/DB
    {name:"Caleb Downs", pos:"S"}, {name:"Dillon Thieneman", pos:"S"},
    {name:"Emmanuel McNeil-Warren", pos:"S"}, {name:"A.J. Haulcy", pos:"S"},
    {name:"Kamari Ramsey", pos:"S"}, {name:"Mansoor Delane", pos:"CB"},
    {name:"Jermod McCoy", pos:"CB"},
  ];

  const IDP_POSITIONS = new Set(['EDGE','DT','DL','DE','LB','CB','S','DB']);
  const OFFENSE_POSITIONS = new Set(['QB','RB','WR','TE']);
  function isKickerPosition(pos) {
    const p = String(pos || '').toUpperCase();
    return p === 'K' || p === 'PK';
  }
  let rookieHintCache = { key: '', names: new Set(), posByNorm: new Map() };

  function getRookieHintData() {
    const mustHave = Array.isArray(loadedData?.settings?.mustHaveRookies)
      ? loadedData.settings.mustHaveRookies
      : [];
    const key = `${mustHave.length}|${mustHave.join('|')}`;
    if (rookieHintCache.key === key) return rookieHintCache;

    const names = new Set();
    const posByNorm = new Map();
    const pushName = (name, pos = '') => {
      const norm = normalizeForLookup(name);
      if (!norm) return;
      names.add(norm);
      if (pos && !posByNorm.has(norm)) posByNorm.set(norm, String(pos).toUpperCase());
    };

    ROOKIES_2026.forEach(r => pushName(r?.name || '', r?.pos || ''));
    mustHave.forEach(name => pushName(name || '', ''));

    rookieHintCache = { key, names, posByNorm };
    return rookieHintCache;
  }

  function getRookiePosHint(name) {
    const norm = normalizeForLookup(name);
    if (!norm) return '';
    return getRookieHintData().posByNorm.get(norm) || '';
  }

  function getPlayerDataByName(name) {
    if (!name || !loadedData?.players) return null;
    const canonical = resolveCanonicalPlayerName(name);
    return canonical ? (loadedData.players[canonical] || null) : null;
  }

  function hasAnyRankingSiteValue(pData) {
    if (!pData || typeof pData !== 'object') return false;
    for (const [k, v] of Object.entries(pData)) {
      if (String(k).startsWith('_')) continue;
      const n = Number(v);
      if (isFinite(n) && n > 0) return true;
    }
    return false;
  }

  function isRookiePlayerName(name, pData = null) {
    if (!name) return false;
    const pd = pData || getPlayerDataByName(name);
    if (pd && pd._isRookie === true) return true;
    const yrs = Number(pd?._yearsExp ?? pd?.years_exp);
    if (isFinite(yrs)) return yrs === 0;
    const norm = normalizeForLookup(name);
    if (!norm) return false;
    return getRookieHintData().names.has(norm);
  }

  // Position colors for badges
  const POS_COLORS = {
    'QB': { bg:'rgba(231,76,60,0.15)', fg:'#e74c3c', border:'rgba(231,76,60,0.3)' },
    'RB': { bg:'rgba(39,174,96,0.15)', fg:'#27ae60', border:'rgba(39,174,96,0.3)' },
    'WR': { bg:'rgba(52,152,219,0.15)', fg:'#3498db', border:'rgba(52,152,219,0.3)' },
    'TE': { bg:'rgba(243,156,18,0.15)', fg:'#f39c12', border:'rgba(243,156,18,0.3)' },
    'EDGE':{ bg:'rgba(155,89,182,0.15)', fg:'#9b59b6', border:'rgba(155,89,182,0.3)' },
    'DT': { bg:'rgba(155,89,182,0.15)', fg:'#9b59b6', border:'rgba(155,89,182,0.3)' },
    'DL': { bg:'rgba(155,89,182,0.15)', fg:'#9b59b6', border:'rgba(155,89,182,0.3)' },
    'LB': { bg:'rgba(230,126,34,0.15)', fg:'#e67e22', border:'rgba(230,126,34,0.3)' },
    'CB': { bg:'rgba(26,188,156,0.15)', fg:'#1abc9c', border:'rgba(26,188,156,0.3)' },
    'S':  { bg:'rgba(26,188,156,0.15)', fg:'#1abc9c', border:'rgba(26,188,156,0.3)' },
    'DB': { bg:'rgba(26,188,156,0.15)', fg:'#1abc9c', border:'rgba(26,188,156,0.3)' },
    'WR/DB':{ bg:'rgba(142,68,173,0.15)', fg:'#8e44ad', border:'rgba(142,68,173,0.3)' },
  };

  function getPosStyle(pos) {
    const c = POS_COLORS[pos] || { bg:'rgba(100,100,100,0.15)', fg:'var(--subtext)', border:'rgba(100,100,100,0.3)' };
    return `background:${c.bg};color:${c.fg};border:1px solid ${c.border}`;
  }

  // [NEW] Coverage penalty factor
  // coverageFactor removed — single-source discount applied directly in composite

  // [NEW] Coefficient of variation for site agreement
  function coeffOfVariation(values) {
    if (values.length < 2) return 0;
    const mean = values.reduce((a,b) => a + b, 0) / values.length;
    if (mean === 0) return 0;
    const variance = values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / values.length;
    return Math.sqrt(variance) / mean;
  }

  function applyCanonicalEliteCalibration(baseValue, opts = {}) {
    const v = Number(baseValue);
    const nativeTop = Number(opts.nativeTop || 0);
    const siteCount = Math.max(0, Number(opts.siteCount || 0));
    const cv = Number(opts.cv);
    const assetClass = String(opts.assetClass || 'offense').toLowerCase();
    if (!Number.isFinite(v) || v <= 0) return v;
    if (!Number.isFinite(nativeTop) || nativeTop <= 0 || nativeTop <= v) return v;
    if (assetClass === 'pick' || nativeTop < 9800) return v;

    const expectedSites = assetClass === 'idp' ? 3 : 6;
    const coverage = clampValue(siteCount / Math.max(1, expectedSites), 0.35, 1.00);
    const agreement = Number.isFinite(cv)
      ? clampValue(1 - (Math.min(Math.abs(cv), 0.35) / 0.35), 0.25, 1.00)
      : 0.65;
    const strength = clampValue((0.45 + (0.55 * coverage)) * agreement, 0, 1);
    const pulled = v + ((nativeTop - v) * strength);
    const nearTopFloor = nativeTop - ((1 - strength) * 45);
    return clampValue(Math.max(pulled, nearTopFloor), 1, COMPOSITE_SCALE);
  }

  // ── Z-SCORE NORMALIZATION ──
  // Precompute per-site mean and stdev from all loaded players.
  // Stats are computed on TRANSFORMED values (after Flock/IDP curves, TEP boost)
  // so z-scores are directly comparable across sites.
  let siteStatsCache = {};  // { siteKey: { mean, stdev, count } }
  let siteStatsCachePlayersRef = null;
  let siteStatsCacheKey = '';

  function buildSiteStatsCacheKey(cfg = []) {
    const players = loadedData?.players || {};
    const stamp = String(loadedData?.scrapeTimestamp || loadedData?.date || '');
    const cfgSig = (cfg || [])
      .map(sc => `${sc.key}:${sc.include ? 1 : 0}:${Number(sc.max || 0)}:${sc.tep !== false ? 1 : 0}`)
      .join('|');
    const knobs = [
      document.getElementById('flockOffsetInput')?.value || '',
      document.getElementById('flockDivisorInput')?.value || '',
      document.getElementById('flockExponentInput')?.value || '',
      document.getElementById('idpAnchorInput')?.value || '',
      document.getElementById('idpRankOffsetInput')?.value || '',
      document.getElementById('idpRankDivisorInput')?.value || '',
      document.getElementById('idpRankExponentInput')?.value || '',
      document.getElementById('tepMultiplierInput')?.value || '',
    ].join('|');
    return `${stamp}|${Object.keys(players).length}|${cfgSig}|${knobs}`;
  }

  function hydrateSiteStatsFromPayload(data, cfg = []) {
    const incoming = data?.siteStats;
    if (!incoming || typeof incoming !== 'object') return false;
    const keys = (cfg || []).map(sc => sc.key).filter(Boolean);
    if (!keys.length) return false;
    const out = {};
    keys.forEach((key) => {
      const row = incoming?.[key];
      if (!row || typeof row !== 'object') return;
      const mean = Number(row.mean);
      const stdev = Number(row.stdev);
      const count = Number(row.count);
      if (!Number.isFinite(mean) || !Number.isFinite(stdev) || !Number.isFinite(count)) return;
      if (count < 2 || stdev <= 0) return;
      out[key] = { mean, stdev, count };
    });
    if (!Object.keys(out).length) return false;
    siteStatsCache = out;
    siteStatsCachePlayersRef = loadedData?.players || null;
    siteStatsCacheKey = buildSiteStatsCacheKey(cfg);
    return true;
  }

  function computeSiteStats() {
    if (!loadedData || !loadedData.players) return;

    const cfg = getSiteConfig();
    const playersRef = loadedData.players;
    const nextKey = buildSiteStatsCacheKey(cfg);
    if (
      siteStatsCachePlayersRef === playersRef &&
      siteStatsCacheKey === nextKey &&
      Object.keys(siteStatsCache || {}).length
    ) {
      return;
    }
    siteStatsCache = {};
    const siteMode = Object.fromEntries(sites.map(s => [s.key, s.mode || 'value']));
    const flockOffset   = parseFloat(document.getElementById('flockOffsetInput').value)||27;
    const flockDivisor  = parseFloat(document.getElementById('flockDivisorInput').value)||28;
    const flockExponent = parseFloat(document.getElementById('flockExponentInput').value)||-0.66;
    const idpAnchor     = parseFloat(document.getElementById('idpAnchorInput').value)||6250;
    const idpRankOff    = parseFloat(document.getElementById('idpRankOffsetInput').value)||15;
    const idpRankDiv    = parseFloat(document.getElementById('idpRankDivisorInput').value)||16;
    const idpRankExp    = parseFloat(document.getElementById('idpRankExponentInput').value)||-0.72;
    const tepMultiplier = parseFloat(document.getElementById('tepMultiplierInput').value)||1.15;
    const siteTep = Object.fromEntries(cfg.map(s => [s.key, s.tep !== false]));

    // Collect all transformed values per site
    const siteVals = {};  // { key: [val, val, ...] }
    cfg.forEach(sc => { if (sc.include) siteVals[sc.key] = []; });

    for (const [pName, pData] of Object.entries(loadedData.players)) {
      const playerIsTE = isPlayerTE(pName);
      const hasBackendCanonicalMap = !!(
        pData &&
        typeof pData._canonicalSiteValues === 'object' &&
        Object.keys(pData._canonicalSiteValues).length
      );
      cfg.forEach(sc => {
        if (!sc.include || !sc.max || sc.max <= 0) return;
        const canonicalStored = Number(pData?._canonicalSiteValues?.[sc.key]);
        if (hasBackendCanonicalMap) {
          // Backend canonical map is authoritative when present.
          // Do not synthesize per-site transforms client-side for missing keys.
          if (Number.isFinite(canonicalStored) && canonicalStored > 0) {
            siteVals[sc.key].push(canonicalStored);
          }
          return;
        }
        if (Number.isFinite(canonicalStored) && canonicalStored > 0) {
          siteVals[sc.key].push(canonicalStored);
          return;
        }
        const v = pData[sc.key];
        if (v == null || !isFinite(v)) return;

        const pPos = (getPlayerPosition(pName) || '').toUpperCase();
        const siteRaw = getCanonicalSiteValueForSource(sc, v, {
          ctx: { cfg, siteMode, flockOffset, flockDivisor, flockExponent, idpAnchor, idpRankOff, idpRankDiv, idpRankExp, tepMultiplier, siteTep },
          playerName: pName,
          playerData: pData,
          playerPos: pPos,
          playerIsTE,
          playerIsIdp: ['DL','DE','DT','LB','DB','CB','S','EDGE'].includes(pPos),
          isPick: false,
        });
        if (isFinite(siteRaw) && siteRaw > 0) {
          siteVals[sc.key].push(siteRaw);
        }
      });
    }

    // Compute mean and stdev per site
    for (const [key, vals] of Object.entries(siteVals)) {
      if (vals.length < 2) continue;
      const mean = vals.reduce((a,b) => a+b, 0) / vals.length;
      const variance = vals.reduce((sum, v) => sum + (v - mean) ** 2, 0) / vals.length;
      const stdev = Math.sqrt(variance);
      siteStatsCache[key] = { mean, stdev, count: vals.length };
    }
    siteStatsCachePlayersRef = playersRef;
    siteStatsCacheKey = nextKey;

    if (DEBUG_MODE) {
      console.log('[Z-Score] Site stats recomputed:', Object.fromEntries(
        Object.entries(siteStatsCache).map(([k,v]) => [k, `μ=${v.mean.toFixed(1)} σ=${v.stdev.toFixed(1)} n=${v.count}`])
      ));
    }
  }

  const DEBUG_MODE = false; // set true for diagnostics in console


  let __idpBackboneCache = null;
  let __idpBackboneCacheKey = '';
  let __canonicalContextCache = null;
  let __canonicalContextCacheKey = '';

  function buildCanonicalContextCacheKey(cfg = []) {
    const cfgSig = (cfg || [])
      .map(sc => `${sc.key}:${sc.include ? 1 : 0}:${Number(sc.max || 0)}:${Number(sc.weight || 0).toFixed(4)}:${sc.tep !== false ? 1 : 0}`)
      .join('|');
    const knobs = [
      document.getElementById('flockOffsetInput')?.value || '',
      document.getElementById('flockDivisorInput')?.value || '',
      document.getElementById('flockExponentInput')?.value || '',
      document.getElementById('idpAnchorInput')?.value || '',
      document.getElementById('idpRankOffsetInput')?.value || '',
      document.getElementById('idpRankDivisorInput')?.value || '',
      document.getElementById('idpRankExponentInput')?.value || '',
      document.getElementById('tepMultiplierInput')?.value || '',
    ].join('|');
    return `${cfgSig}|${knobs}`;
  }

  function getCanonicalValueContext() {
    const cfg = getSiteConfig();
    const key = buildCanonicalContextCacheKey(cfg);
    if (__canonicalContextCache && __canonicalContextCacheKey === key) {
      return __canonicalContextCache;
    }
    __canonicalContextCache = {
      cfg,
      siteMode: Object.fromEntries(sites.map(s => [s.key, s.mode || 'value'])),
      flockOffset: parseFloat(document.getElementById('flockOffsetInput')?.value) || 27,
      flockDivisor: parseFloat(document.getElementById('flockDivisorInput')?.value) || 28,
      flockExponent: parseFloat(document.getElementById('flockExponentInput')?.value) || -0.66,
      idpAnchor: parseFloat(document.getElementById('idpAnchorInput')?.value) || 6250,
      idpRankOff: parseFloat(document.getElementById('idpRankOffsetInput')?.value) || 15,
      idpRankDiv: parseFloat(document.getElementById('idpRankDivisorInput')?.value) || 16,
      idpRankExp: parseFloat(document.getElementById('idpRankExponentInput')?.value) || -0.72,
      tepMultiplier: parseFloat(document.getElementById('tepMultiplierInput')?.value) || 1.15,
      siteTep: Object.fromEntries(cfg.map(s => [s.key, s.tep !== false])),
    };
    __canonicalContextCacheKey = key;
    return __canonicalContextCache;
  }

  function getIdpBucket(pos) {
    const p = String(pos || '').toUpperCase();
    if (['LB'].includes(p)) return 'LB';
    if (['DL','DE','DT','EDGE'].includes(p)) return 'DL';
    if (['DB','CB','S'].includes(p)) return 'DB';
    return 'ALL';
  }

  let __rankCurveCache = null;
  let __rankCurveCacheKey = '';

  function getValueEconomyPointFromPlayerData(pData = null) {
    if (!pData || typeof pData !== 'object') return null;
    const keys = ['_finalAdjusted', '_leagueAdjusted', '_scoringAdjusted', '_scarcityAdjusted', '_composite', '_rawComposite'];
    for (const k of keys) {
      const v = Number(pData[k]);
      if (Number.isFinite(v) && v > 0) return v;
    }
    return null;
  }

  function getCurveUniverseForPlayer(playerName = '', pData = null, posOverride = '') {
    if (parsePickToken(playerName)) return 'picks';
    const pos = String(posOverride || getPlayerPosition(playerName) || pData?.position || '').toUpperCase();
    const isIdp = IDP_POSITIONS.has(pos);
    const isRookie = isRookiePlayerName(playerName, pData || {});
    if (isIdp) return isRookie ? 'idp_rookies' : 'idp_veterans';
    return isRookie ? 'offense_rookies' : 'offense_veterans';
  }

  function rankPercentileFromSortedRanks(rankValue, sortedRanks = []) {
    if (!sortedRanks.length) return 1;
    if (sortedRanks.length === 1) return 0;
    const r = Number(rankValue);
    if (!Number.isFinite(r)) return 1;
    let left = 0;
    let right = sortedRanks.length;
    while (left < right) {
      const mid = (left + right) >> 1;
      if (sortedRanks[mid] < r) left = mid + 1;
      else right = mid;
    }
    const l = left;
    let l2 = left;
    let right2 = sortedRanks.length;
    while (l2 < right2) {
      const mid = (l2 + right2) >> 1;
      if (sortedRanks[mid] <= r) l2 = mid + 1;
      else right2 = mid;
    }
    const rIdx = l2;
    let pos;
    if (l < rIdx) {
      pos = (l + rIdx - 1) / 2;
    } else if (l <= 0) {
      pos = 0;
    } else if (l >= sortedRanks.length) {
      pos = sortedRanks.length - 1;
    } else {
      const lo = Number(sortedRanks[l - 1]);
      const hi = Number(sortedRanks[l]);
      const frac = hi > lo ? Math.max(0, Math.min(1, (r - lo) / (hi - lo))) : 0;
      pos = (l - 1) + frac;
    }
    return Math.max(0, Math.min(1, pos / Math.max(1, sortedRanks.length - 1)));
  }

  function valueAtPercentileDesc(valuesDesc = [], percentile = 1) {
    if (!Array.isArray(valuesDesc) || !valuesDesc.length) return null;
    if (valuesDesc.length === 1) return Number(valuesDesc[0]);
    const p = Math.max(0, Math.min(1, Number(percentile) || 0));
    const idx = p * (valuesDesc.length - 1);
    const lo = Math.floor(idx);
    const hi = Math.ceil(idx);
    if (hi <= lo) return Number(valuesDesc[lo]);
    const t = idx - lo;
    const lv = Number(valuesDesc[lo]);
    const hv = Number(valuesDesc[hi]);
    return lv + ((hv - lv) * t);
  }

  function buildRankCurveContext(c = null) {
    const ctx = c || getCanonicalValueContext();
    const players = loadedData?.players || {};
    const playerCount = Object.keys(players).length;
    if (!playerCount) return null;
    const key = `${loadedData?.scrapeTimestamp || loadedData?.date || ''}|${playerCount}|${Number(ctx.idpAnchor || 0).toFixed(2)}`;
    if (__rankCurveCache && __rankCurveCacheKey === key) return __rankCurveCache;

    const universes = ['offense_veterans', 'offense_rookies', 'idp_veterans', 'idp_rookies', 'picks'];
    const targets = Object.fromEntries(universes.map(u => [u, []]));
    for (const [name, pData] of Object.entries(players)) {
      const val = getValueEconomyPointFromPlayerData(pData);
      if (!Number.isFinite(val) || val <= 0) continue;
      const universe = getCurveUniverseForPlayer(name, pData);
      if (!targets[universe]) targets[universe] = [];
      targets[universe].push(Number(val));
    }
    Object.keys(targets).forEach(u => {
      targets[u] = (targets[u] || []).filter(v => Number.isFinite(v) && v > 0).sort((a, b) => b - a);
    });

    const rankSites = (ctx.cfg || [])
      .filter(sc => {
        const mode = (ctx.siteMode?.[sc.key] || sc.mode || 'value');
        return mode === 'rank' || mode === 'idpRank';
      })
      .map(sc => sc.key);
    const sourceRanks = {};
    for (const [name, pData] of Object.entries(players)) {
      const universe = getCurveUniverseForPlayer(name, pData);
      rankSites.forEach(sk => {
        const rv = Number(pData?.[sk]);
        if (!Number.isFinite(rv) || rv <= 0) return;
        const k = `${sk}::${universe}`;
        if (!Array.isArray(sourceRanks[k])) sourceRanks[k] = [];
        sourceRanks[k].push(rv);
      });
    }
    Object.keys(sourceRanks).forEach(k => sourceRanks[k].sort((a, b) => a - b));

    const diagnostics = {
      generatedAt: new Date().toISOString(),
      minSourceCount: RANK_CURVE_MIN_SOURCE_COUNT,
      minTargetCount: RANK_CURVE_MIN_TARGET_COUNT,
      universes: Object.fromEntries(universes.map(u => [u, { targetCount: (targets[u] || []).length }])),
      sources: {},
    };
    rankSites.forEach(sk => {
      universes.forEach(u => {
        const src = sourceRanks[`${sk}::${u}`] || [];
        const tgt = targets[u] || [];
        diagnostics.sources[`${sk}:${u}`] = {
          sourceCount: src.length,
          targetCount: tgt.length,
          curveBuilt: src.length >= RANK_CURVE_MIN_SOURCE_COUNT && tgt.length >= RANK_CURVE_MIN_TARGET_COUNT,
          fallbackUsed: !(src.length >= RANK_CURVE_MIN_SOURCE_COUNT && tgt.length >= RANK_CURVE_MIN_TARGET_COUNT),
        };
      });
    });
    const nextCtx = { key, targets, sourceRanks, diagnostics };
    enrichRankCurveDiagnostics(nextCtx, ctx);
    if (loadedData && typeof loadedData === 'object') loadedData.rankCurveDiagnostics = diagnostics;

    __rankCurveCacheKey = key;
    __rankCurveCache = nextCtx;
    return __rankCurveCache;
  }

  function fallbackSparseRankValue(rankValue, universe, c, sc, curveCtx = null) {
    const rank = Math.max(1, Number(rankValue) || 1);
    const rc = curveCtx || buildRankCurveContext(c);
    const defaults = {
      offense_veterans: COMPOSITE_SCALE,
      offense_rookies: 3800,
      idp_veterans: Number(c?.idpAnchor || IDP_ANCHOR_DEFAULT || 6250),
      idp_rookies: 2800,
      picks: 4200,
    };
    const topFromTarget = Number(rc?.targets?.[universe]?.[0]);
    const top = Math.max(200, Math.min(COMPOSITE_SCALE, Number.isFinite(topFromTarget) && topFromTarget > 0 ? topFromTarget : defaults[universe] || Number(sc?.max || COMPOSITE_SCALE)));
    const exp = universe.includes('rookies') ? 0.68 : 0.62;
    const off = universe.includes('rookies') ? 8 : 18;
    const floor = top * (universe.includes('rookies') ? 0.10 : 0.06);
    const est = top * Math.pow((rank + off) / (1 + off), -exp);
    return Math.max(1, Math.min(COMPOSITE_SCALE, Math.max(floor, est)));
  }

  function calibrateRankToValueCurve(sc, rankValue, opts = {}, c = null) {
    const ctx = c || getCanonicalValueContext();
    const rc = buildRankCurveContext(ctx);
    const universe = getCurveUniverseForPlayer(opts.playerName || '', opts.playerData || null, opts.playerPos || '');
    const sourceRanks = rc?.sourceRanks?.[`${sc.key}::${universe}`] || [];
    const targetCurve = rc?.targets?.[universe] || [];
    const curveBuilt = sourceRanks.length >= RANK_CURVE_MIN_SOURCE_COUNT && targetCurve.length >= RANK_CURVE_MIN_TARGET_COUNT;
    if (curveBuilt) {
      const pct = rankPercentileFromSortedRanks(rankValue, sourceRanks);
      const mapped = valueAtPercentileDesc(targetCurve, pct);
      if (Number.isFinite(mapped) && mapped > 0) return mapped;
    }
    return fallbackSparseRankValue(rankValue, universe, ctx, sc, rc);
  }

  function enrichRankCurveDiagnostics(curveCtx, c = null) {
    const rc = curveCtx || __rankCurveCache;
    if (!rc || !rc.diagnostics || !rc.sourceRanks || !rc.targets) return;
    const ctx = c || getCanonicalValueContext();
    const findSite = (k) => (ctx.cfg || []).find(s => s.key === k) || { key: k, max: COMPOSITE_SCALE };
    Object.entries(rc.diagnostics.sources || {}).forEach(([key, row]) => {
      const [siteKey, universe] = String(key).split(':');
      const src = rc.sourceRanks?.[`${siteKey}::${universe}`] || [];
      const tgt = rc.targets?.[universe] || [];
      if (!src.length) {
        row.examples = {};
        row.spreadRatioTopToTail = null;
        row.suspiciousSpacing = null;
        return;
      }
      const siteCfg = findSite(siteKey);
      const curveBuilt = !!row.curveBuilt;
      const sampleRanks = {
        top: src[0],
        middle: src[Math.floor(src.length / 2)],
        tail: src[src.length - 1],
      };
      const examples = {};
      Object.entries(sampleRanks).forEach(([label, rankVal]) => {
        let value;
        if (curveBuilt && tgt.length >= RANK_CURVE_MIN_TARGET_COUNT) {
          const pct = rankPercentileFromSortedRanks(rankVal, src);
          value = valueAtPercentileDesc(tgt, pct);
        } else {
          value = fallbackSparseRankValue(rankVal, universe, ctx, siteCfg, rc);
        }
        examples[label] = {
          rank: Math.round(Number(rankVal) * 1000) / 1000,
          value: Math.round(Number(value) || 0),
          fallback: !curveBuilt,
        };
      });
      row.examples = examples;
      const topV = Number(examples.top?.value);
      const tailV = Number(examples.tail?.value);
      if (Number.isFinite(topV) && Number.isFinite(tailV) && tailV > 0) {
        const spread = topV / tailV;
        row.spreadRatioTopToTail = Math.round(spread * 1000) / 1000;
        row.suspiciousSpacing = spread < 1.35 ? 'compressed_spacing' : (spread > 280 ? 'inflated_spacing' : null);
      } else {
        row.spreadRatioTopToTail = null;
        row.suspiciousSpacing = null;
      }
      row.rookieIsolated = universe.includes('rookies');
      row.idpIsolated = universe.startsWith('idp_');
    });
  }

  function getIdpBackboneCurves(ctx = null) {
    const c = ctx || getCanonicalValueContext();
    const key = JSON.stringify({
      anchor: c.idpAnchor,
      players: Object.keys(loadedData?.players || {}).length,
      hasPos: Object.keys(loadedData?.sleeper?.positions || {}).length,
    });
    if (__idpBackboneCache && __idpBackboneCacheKey === key) return __idpBackboneCache;
    const buckets = { ALL: [] , DL: [], LB: [], DB: [] };
    const posMap = loadedData?.sleeper?.positions || {};
    for (const [name, pdata] of Object.entries(loadedData?.players || {})) {
      const raw = Number(pdata?.idpTradeCalc);
      if (!Number.isFinite(raw) || raw <= 0) continue;
      const pos = String(posMap[name] || '').toUpperCase();
      const bucket = getIdpBucket(pos);
      if (bucket === 'ALL') continue;
      buckets.ALL.push(raw);
      buckets[bucket].push(raw);
    }
    Object.keys(buckets).forEach(k => {
      buckets[k] = buckets[k].filter(v => Number.isFinite(v) && v > 0).sort((a,b) => b-a);
    });
    if (!buckets.ALL.length) buckets.ALL = [c.idpAnchor];
    __idpBackboneCacheKey = key;
    __idpBackboneCache = buckets;
    return buckets;
  }

  function interpolateIdpBackbone(rankValue, playerPos = '', ctx = null) {
    const c = ctx || getCanonicalValueContext();
    const rank = Math.max(1, Number(rankValue) || 1);
    const curves = getIdpBackboneCurves(c);
    const bucket = getIdpBucket(playerPos);
    const arr = (curves[bucket] && curves[bucket].length >= 8 ? curves[bucket] : curves.ALL) || [c.idpAnchor];
    if (!arr.length) {
      return c.idpAnchor * Math.pow(((rank + c.idpRankOff) / c.idpRankDiv), c.idpRankExp);
    }
    const lowerIdx = Math.max(0, Math.floor(rank) - 1);
    const upperIdx = Math.max(0, Math.ceil(rank) - 1);
    const lower = arr[Math.min(lowerIdx, arr.length - 1)];
    const upper = arr[Math.min(upperIdx, arr.length - 1)];
    let val;
    if (upperIdx === lowerIdx) {
      val = lower;
    } else {
      const t = rank - Math.floor(rank);
      val = lower + (upper - lower) * t;
    }
    if (rank > arr.length) {
      const tailA = arr[Math.max(0, arr.length - 2)] || arr[arr.length - 1] || c.idpAnchor;
      const tailB = arr[arr.length - 1] || tailA;
      const tailRatio = Math.max(0.82, Math.min(0.995, tailB / Math.max(1, tailA)));
      val = tailB * Math.pow(tailRatio, rank - arr.length);
    }
    return Math.max(1, Math.min(c.idpAnchor, Number(val) || 1));
  }

  function getCanonicalSiteValueForSource(sc, value, opts = {}) {
    const c = opts.ctx || getCanonicalValueContext();
    const v = Number(value);
    if (!Number.isFinite(v)) return null;
    const mode = (c.siteMode?.[sc.key] || sc.mode || 'value');
    let siteRaw;
    if (!opts.isPick && (mode === 'rank' || mode === 'idpRank')) {
      // Rank-only sources: map rank percentile onto the same universe's
      // Fully-Adjusted value distribution so spacing reflects real value economics.
      siteRaw = calibrateRankToValueCurve(sc, v, opts, c);
      if (!Number.isFinite(siteRaw) || siteRaw <= 0) {
        // Defensive fallback only; calibrated curve above is the primary path.
        if (mode === 'idpRank') siteRaw = interpolateIdpBackbone(v, opts.playerPos, c);
        else siteRaw = sc.max * Math.pow(((v + c.flockOffset) / c.flockDivisor), c.flockExponent);
      }
    } else {
      let nativeVal = v;
      if (sc.key === 'idpTradeCalc' && opts.playerIsIdp) {
        // Explicit policy: cap IDPTradeCalc IDP rows to IDP anchor for stability.
        nativeVal = Math.min(nativeVal, c.idpAnchor);
      }
      if (opts.isPick && opts.pickValuesCanonical) {
        siteRaw = nativeVal;
      } else if (NATIVE_CANONICAL_VALUE_SITES.has(sc.key)) {
        // Native 0–9999 sources pass through directly.
        siteRaw = nativeVal;
      } else {
        const usableMax = Number(sc.max);
        siteRaw = (Number.isFinite(usableMax) && usableMax > 0)
          ? (nativeVal / usableMax) * COMPOSITE_SCALE
          : nativeVal;
      }
    }
    if (opts.playerIsTE && !c.siteTep?.[sc.key] && c.tepMultiplier > 1) {
      siteRaw *= c.tepMultiplier;
    }
    if (!Number.isFinite(siteRaw)) return null;
    return Math.max(1, Math.min(COMPOSITE_SCALE, siteRaw));
  }

  function getCanonicalSiteNorm(siteKey, siteRaw) {
    const useZ = document.getElementById('zScoreToggle')?.checked;
    if (useZ && siteStatsCache[siteKey] && siteStatsCache[siteKey].stdev > 0) {
      const { mean, stdev } = siteStatsCache[siteKey];
      const zFloor = parseFloat(document.getElementById('zFloorInput')?.value) || Z_FLOOR;
      const zCeiling = parseFloat(document.getElementById('zCeilingInput')?.value) || Z_CEILING;
      const z = (siteRaw - mean) / stdev;
      return Math.max(0, Math.min(1, (z - zFloor) / (zCeiling - zFloor)));
    }
    return Math.max(0, Math.min(1, siteRaw / COMPOSITE_SCALE));
  }

  // Shared canonical composite engine.
  // Every live valuation path should route through this so canonical source transforms
  // (value/rank/idpRank) and composite blending stay identical across rankings + calculator.
  function computeCanonicalCompositeFromSiteValues(siteValues, opts = {}) {
    if (!siteValues || typeof siteValues !== 'object') return null;
    const isPick = !!opts.isPick;
    const playerName = opts.playerName || '';
    const playerIsRookie = !!(opts.playerIsRookie ?? (!isPick && isRookiePlayerName(playerName, siteValues)));
    const includeRookieOnlyDlf = !!opts.includeRookieOnlyDlf;
    const cctx = opts.ctx || getCanonicalValueContext();
    const playerPos = String(
      opts.playerPos != null
        ? opts.playerPos
        : (isPick ? 'PICK' : (getPlayerPosition(playerName) || ''))
    ).toUpperCase();
    const playerIsTE = !!(opts.playerIsTE ?? (!isPick && isPlayerTE(playerName)));
    const playerIsIdp = !!(opts.playerIsIdp ?? (!isPick && IDP_POSITIONS.has(playerPos)));
    const pickValuesCanonical = !!(isPick && (opts.pickValuesCanonical || siteValues?.__canonical));

    const wNorms = [];
    const rawNorms = [];
    const siteDetails = {};
    let maxValueSiteRaw = 0;
    let nativeTopSiteRaw = 0;

    cctx.cfg.forEach(sc => {
      if (!sc.include || !sc.max || sc.max <= 0) return;
      if (ROOKIE_ONLY_DLF_SITE_KEYS.has(sc.key)) {
        // Rookie-only DLF lists are overlay inputs. They are excluded from
        // normal dynasty composite blending unless explicitly enabled for
        // a rookie-focused context.
        if (!(includeRookieOnlyDlf && playerIsRookie)) return;
      }
      const rawValue = Number(siteValues[sc.key]);
      if (!Number.isFinite(rawValue)) return;

      const siteRaw = getCanonicalSiteValueForSource(sc, rawValue, {
        ctx: cctx,
        playerName,
        playerData: siteValues,
        playerPos,
        playerIsTE,
        playerIsIdp,
        isPick,
        pickValuesCanonical,
      });
      if (!Number.isFinite(siteRaw)) return;

      const norm = getCanonicalSiteNorm(sc.key, siteRaw);
      if (!Number.isFinite(norm)) return;

      const mode = (cctx.siteMode?.[sc.key] || sc.mode || 'value');
      wNorms.push({ norm, weight: sc.weight });
      rawNorms.push(norm);
      siteDetails[sc.key] = Math.round(siteRaw);
      if (NATIVE_CANONICAL_VALUE_SITES.has(sc.key)) {
        nativeTopSiteRaw = Math.max(nativeTopSiteRaw, siteRaw);
      }
      // Cap ceiling only from true value-mode sites.
      if (sc.max > 1000 && mode !== 'rank' && mode !== 'idpRank' && siteRaw > maxValueSiteRaw) {
        maxValueSiteRaw = siteRaw;
      }
    });

    if (!wNorms.length) return null;

    let trimmed = [...wNorms];
    if (trimmed.length >= 5) {
      const sortedNorms = [...trimmed].sort((a, b) => a.norm - b.norm);
      const lowGap = sortedNorms[1].norm - sortedNorms[0].norm;
      const highGap = sortedNorms[sortedNorms.length - 1].norm - sortedNorms[sortedNorms.length - 2].norm;
      const startIdx = lowGap >= OUTLIER_TRIM_GAP ? 1 : 0;
      const endIdx = highGap >= OUTLIER_TRIM_GAP ? -1 : sortedNorms.length;
      const next = sortedNorms.slice(startIdx, endIdx === -1 ? -1 : endIdx);
      trimmed = next.length ? next : sortedNorms;
    }

    let wSum = 0;
    let wTotal = 0;
    trimmed.forEach(({ norm, weight }) => {
      wTotal += norm * weight;
      wSum += weight;
    });
    const metaNorm = wSum > 0 ? wTotal / wSum : 0;

    let metaValue = metaNorm * COMPOSITE_SCALE;
    const cv = coeffOfVariation(rawNorms);

    if (rawNorms.length >= 4) {
      const sortedVals = [...rawNorms].sort((a, b) => a - b);
      const mid = Math.floor(sortedVals.length / 2);
      const medianNorm = sortedVals.length % 2
        ? sortedVals[mid]
        : (sortedVals[mid - 1] + sortedVals[mid]) / 2;
      if (medianNorm >= ELITE_NORM_THRESHOLD) {
        const agreement = Math.max(0, 1 - Math.min(cv, 0.30) / 0.30);
        const span = Math.min(1, (medianNorm - ELITE_NORM_THRESHOLD) / (1 - ELITE_NORM_THRESHOLD));
        const eliteBoost = 1 + (ELITE_BOOST_MAX * span * agreement);
        metaValue *= eliteBoost;
      }
    }

    if (wNorms.length === 1) metaValue *= SINGLE_SOURCE_DISCOUNT;

    let capLimit = maxValueSiteRaw;
    if (playerIsIdp && capLimit > 0) {
      const idpHeadroom = Math.max(0, cctx.idpAnchor - capLimit);
      capLimit = capLimit + (IDP_VALUE_HEADROOM_FRACTION * idpHeadroom);
    }
    if (capLimit > 0 && metaValue > capLimit) metaValue = capLimit;

    metaValue = applyCanonicalEliteCalibration(metaValue, {
      nativeTop: nativeTopSiteRaw,
      siteCount: wNorms.length,
      cv,
      assetClass: playerIsIdp ? 'idp' : (isPick ? 'pick' : 'offense'),
    });

    return {
      rawCompositeValue: clampValue(Math.round(metaValue), 1, COMPOSITE_SCALE),
      siteCount: wNorms.length,
      siteDetails,
      cv,
      playerPos,
      playerIsTE,
      playerIsIdp,
      isPick,
    };
  }

  function getPrecomputedAdjustmentBundle(playerData, rawComposite, position, playerName = '') {
    if (!playerData || typeof playerData !== 'object') return null;
    const hasModernPrecomputed =
      Number.isFinite(Number(playerData._scoringAdjusted)) ||
      Number.isFinite(Number(playerData._scarcityAdjusted)) ||
      Number.isFinite(Number(playerData._finalAdjusted)) ||
      Number.isFinite(Number(playerData._combinedMultiplier)) ||
      Number.isFinite(Number(playerData._scoringEffectiveMultiplier)) ||
      Number.isFinite(Number(playerData._preCalibrationValue));
    if (!hasModernPrecomputed) return null;
    const raw = clampValue(
      Math.round(Number(rawComposite ?? playerData._rawComposite ?? playerData._rawMarketValue ?? playerData._composite) || 0),
      1,
      COMPOSITE_SCALE
    );
    const finalAdjustedValue = Number(playerData._finalAdjusted ?? playerData._leagueAdjusted);
    if (!Number.isFinite(finalAdjustedValue) || finalAdjustedValue <= 0) return null;
    const scoringAdjustedValue = clampValue(Math.round(Number(playerData._scoringAdjusted ?? raw) || raw), 1, COMPOSITE_SCALE);
    const scarcityAdjustedValue = clampValue(Math.round(Number(playerData._scarcityAdjusted ?? scoringAdjustedValue) || scoringAdjustedValue), 1, COMPOSITE_SCALE);
    const marketReliabilityScore = clampValue(Number(playerData._marketReliabilityScore ?? 0.55), MARKET_CONF_MIN, MARKET_CONF_MAX);
    return {
      rawMarketValue: raw,
      marketReliability: {
        score: marketReliabilityScore,
        label: String(playerData._marketReliabilityLabel || ''),
        siteCount: Number(playerData._marketReliabilitySiteCount ?? playerData._sites ?? 0) || 0,
      },
      assetClass: String(playerData._assetClass || getAssetClass(position, playerName) || ''),
      scoring: {
        baselineBucket: String(playerData._lamBucket || ''),
        rawCompositeValue: raw,
        rawLeagueMultiplier: Number(playerData._rawLeagueMultiplier ?? 1) || 1,
        shrunkLeagueMultiplier: Number(playerData._shrunkLeagueMultiplier ?? 1) || 1,
        adjustmentStrength: Number(playerData._scoringAdjustmentStrength ?? playerData._lamStrength ?? 0) || 0,
        effectiveMultiplier: Number(playerData._scoringEffectiveMultiplier ?? 1) || 1,
        finalAdjustedValue: scoringAdjustedValue,
        valueDelta: scoringAdjustedValue - raw,
        formatFitSource: String(playerData._formatFitSource || ''),
        formatFitConfidence: Number(playerData._formatFitConfidence ?? 0) || 0,
        formatFitRaw: Number(playerData._formatFitRaw ?? 0) || 0,
        formatFitShrunk: Number(playerData._formatFitShrunk ?? 0) || 0,
        formatFitFinal: Number(playerData._formatFitFinal ?? 0) || 0,
        formatFitPPGTest: Number(playerData._formatFitPPGTest ?? 0) || 0,
        formatFitPPGCustom: Number(playerData._formatFitPPGCustom ?? 0) || 0,
        formatFitProductionShare: Number(playerData._formatFitProductionShare ?? 0) || 0,
      },
      scarcity: {
        scarcityBucket: String(playerData._lamBucket || ''),
        scarcityMultiplierRaw: Number(playerData._scarcityMultiplierRaw ?? 1) || 1,
        scarcityMultiplierEffective: Number(playerData._scarcityMultiplierEffective ?? 1) || 1,
        scarcityStrength: Number(playerData._scarcityStrength ?? 0) || 0,
        replacementRank: Number(playerData._replacementRank ?? 0) || 0,
        replacementValue: Number(playerData._replacementValue ?? 0) || 0,
        valueAboveReplacement: Number(playerData._valueAboveReplacement ?? 0) || 0,
        finalScarcityAdjustedValue: scarcityAdjustedValue,
        scarcityDelta: scarcityAdjustedValue - raw,
      },
      scoringAdjustedValue,
      scarcityAdjustedValue,
      guardrailedValue: clampValue(Math.round(Number(playerData._guardrailedValue ?? scarcityAdjustedValue) || scarcityAdjustedValue), 1, COMPOSITE_SCALE),
      topEndGuardrail: {
        minValue: Number(playerData._guardrailMin ?? 0) || 0,
        maxValue: Number(playerData._guardrailMax ?? 0) || 0,
        upCap: Number(playerData._guardrailUpCap ?? 0) || 0,
        downCap: Number(playerData._guardrailDownCap ?? 0) || 0,
        applied: !!playerData._guardrailApplied,
      },
      combinedMultiplierUnclamped: Number(playerData._combinedMultiplierUnclamped ?? playerData._combinedMultiplier ?? 1) || 1,
      combinedMultiplier: Number(playerData._combinedMultiplier ?? playerData._effectiveMultiplier ?? 1) || 1,
      boundedCombinedMultiplier: Number(playerData._boundedCombinedMultiplier ?? playerData._combinedMultiplier ?? 1) || 1,
      preCalibrationValue: clampValue(Math.round(Number(playerData._preCalibrationValue ?? finalAdjustedValue) || finalAdjustedValue), 1, COMPOSITE_SCALE),
      canonicalCeilingCalibrationApplied: !!playerData._canonicalCeilingCalibrationApplied,
      finalAdjustedValue: clampValue(Math.round(finalAdjustedValue), 1, COMPOSITE_SCALE),
      valueDelta: Math.round(Number(playerData._lamDelta ?? (finalAdjustedValue - raw)) || (finalAdjustedValue - raw)),
    };
  }

  let __topNonPickRawPlayersRef = null;
  let __topNonPickRawValue = null;
  let __topNonPickRawPlayerName = null;

  function getTopNonPickRawFromLoadedData() {
    const players = loadedData?.players;
    if (!players || typeof players !== 'object') return null;
    if (
      __topNonPickRawPlayersRef === players &&
      Number.isFinite(__topNonPickRawValue) &&
      __topNonPickRawValue > 0 &&
      typeof __topNonPickRawPlayerName === 'string'
    ) {
      return __topNonPickRawValue;
    }
    let top = 0;
    let topName = '';
    for (const [name, pdata] of Object.entries(players)) {
      if (!pdata || typeof pdata !== 'object') continue;
      if (parsePickToken(name)) continue;
      const raw = Number(pdata._rawComposite ?? pdata._rawMarketValue ?? pdata._composite);
      if (!Number.isFinite(raw)) continue;
      if (raw > top) {
        top = raw;
        topName = String(name || '');
      } else if (raw === top) {
        // Deterministic tie-break for canonical single-top behavior.
        const current = String(name || '');
        if (!topName || current.localeCompare(topName) < 0) topName = current;
      }
    }
    __topNonPickRawPlayersRef = players;
    __topNonPickRawValue = top > 0 ? clampValue(Math.round(top), 1, COMPOSITE_SCALE) : null;
    __topNonPickRawPlayerName = topName || null;
    return __topNonPickRawValue;
  }

  function getTopNonPickRawPlayerName() {
    // Ensure cache is populated.
    getTopNonPickRawFromLoadedData();
    return typeof __topNonPickRawPlayerName === 'string' ? __topNonPickRawPlayerName : null;
  }

  function resolveLoadedPlayerDataForPrecomputed(playerName = '') {
    if (!playerName || !loadedData?.players) return null;
    const canonical = resolveCanonicalPlayerName(playerName);
    return canonical ? (loadedData.players[canonical] || null) : null;
  }

  function computeFinalAdjustedValueCore(rawComposite, position, playerName = '', context = {}) {
    const raw = clampValue(Math.round(Number(rawComposite) || 0), 1, COMPOSITE_SCALE);
    const assetClass = context.assetClass || getAssetClass(position, playerName);
    const marketReliability = context.marketReliability || computeMarketReliability(raw, position, playerName, {
      ...context,
      assetClass,
    });

    const scoring = computeLeagueAdjustedValue(raw, position, playerName, {
      ...context,
      assetClass,
      marketReliability,
    });
    const scoringAdjustedValue = clampValue(
      Math.round(raw * Number(scoring.effectiveMultiplier || 1)),
      1,
      COMPOSITE_SCALE
    );

    const scarcity = computeScarcityAdjustedValue(scoringAdjustedValue, position, playerName, {
      ...context,
      assetClass,
      marketReliability,
    });
    const scarcityAdjustedValue = clampValue(
      Math.round(Number(scarcity.finalScarcityAdjustedValue || scoringAdjustedValue)),
      1,
      COMPOSITE_SCALE
    );

    const guardrailCaps = directionalGuardrailCaps(raw, assetClass, marketReliability.score);
    const guardrailMin = Math.max(1, Math.round(raw * (1 - guardrailCaps.downCap)));
    const guardrailMax = clampValue(Math.round(raw * (1 + guardrailCaps.upCap)), 1, COMPOSITE_SCALE);
    const guardrailedValue = clampValue(
      Math.max(guardrailMin, Math.min(guardrailMax, scarcityAdjustedValue)),
      1,
      COMPOSITE_SCALE
    );

    const combinedMultiplierUnclamped = guardrailedValue / Math.max(1, raw);
    const boundedCombinedMultiplier = Math.max(
      FULL_ADJ_MIN_MULT,
      Math.min(FULL_ADJ_MAX_MULT, combinedMultiplierUnclamped)
    );
    const preCalibrationValue = clampValue(Math.round(raw * boundedCombinedMultiplier), 1, COMPOSITE_SCALE);
    const finalAdjustedValue = Math.round(applyFinalCanonicalCeilingCalibration(
      raw,
      preCalibrationValue,
      marketReliability,
      assetClass,
      playerName
    ));
    const canonicalCeilingCalibrationApplied = finalAdjustedValue !== preCalibrationValue;
    const combinedMultiplier = finalAdjustedValue / Math.max(1, raw);

    return {
      rawMarketValue: raw,
      marketReliability,
      assetClass,
      scoring,
      scarcity,
      scoringAdjustedValue,
      scarcityAdjustedValue,
      guardrailedValue,
      topEndGuardrail: {
        minValue: guardrailMin,
        maxValue: guardrailMax,
        upCap: guardrailCaps.upCap,
        downCap: guardrailCaps.downCap,
        applied: guardrailedValue !== scarcityAdjustedValue,
      },
      combinedMultiplierUnclamped,
      combinedMultiplier,
      boundedCombinedMultiplier,
      preCalibrationValue,
      canonicalCeilingCalibrationApplied,
      finalAdjustedValue,
      valueDelta: finalAdjustedValue - raw,
    };
  }

  function applyFinalCanonicalCeilingCalibration(rawValue, candidateValue, marketReliability, assetClass, playerName = '') {
    const raw = clampValue(rawValue, 1, COMPOSITE_SCALE);
    const candidate = clampValue(candidateValue, 1, COMPOSITE_SCALE);
    const topNonPickRaw = getTopNonPickRawFromLoadedData();
    const topNonPickName = getTopNonPickRawPlayerName();
    if (assetClass !== 'pick' && Number.isFinite(topNonPickRaw) && raw >= (topNonPickRaw - 0.5)) {
      const sameTopPlayer =
        !!playerName &&
        !!topNonPickName &&
        normalizeForLookup(playerName) === normalizeForLookup(topNonPickName);
      return sameTopPlayer ? COMPOSITE_SCALE : Math.min(COMPOSITE_SCALE - 1, candidate);
    }
    if (assetClass === 'pick' || raw < 9600) return candidate >= COMPOSITE_SCALE ? (COMPOSITE_SCALE - 1) : candidate;
    const rel = clampValue(Number(marketReliability?.score ?? marketReliability ?? 0.6), MARKET_CONF_MIN, MARKET_CONF_MAX);
    const elitePct = clampValue((raw - 9600) / (COMPOSITE_SCALE - 9600), 0, 1);
    if (elitePct <= 0) return candidate;
    const pull = elitePct * (0.45 + (0.55 * rel));
    const calibrated = clampValue(candidate + ((COMPOSITE_SCALE - candidate) * pull), 1, COMPOSITE_SCALE);
    if (calibrated >= COMPOSITE_SCALE) {
      const sameTopPlayer =
        !!playerName &&
        !!topNonPickName &&
        normalizeForLookup(playerName) === normalizeForLookup(topNonPickName);
      return sameTopPlayer ? COMPOSITE_SCALE : (COMPOSITE_SCALE - 1);
    }
    return calibrated;
  }

  function computeMetaValueForPlayer(playerName, opts = {}) {
    // Default output is fully adjusted so site-wide displays stay on the same basis.
    // Use { rawOnly: true } for internal model-building paths that must stay unadjusted.
    const rawOnly = !!opts?.rawOnly;
    const allowFrontendCompositeFallback = (opts?.allowFrontendCompositeFallback !== false);
    if (!loadedData || !loadedData.players) return null;
    const lookupPlayerData = (name) => {
      if (!name || !loadedData?.players) return { name: '', data: null };
      const canonical = resolveCanonicalPlayerName(name);
      if (!canonical) return { name: '', data: null };
      return { name: canonical, data: loadedData.players[canonical] || null };
    };

    // Keep pick valuation identical across rankings + trade calculator.
    const pickInfo = parsePickToken(playerName);
    const direct = lookupPlayerData(playerName);
    if (pickInfo) {
      const directComp = Number(direct?.data?._composite);
      if (isFinite(directComp) && directComp > 0) {
        const raw = Number(direct?.data?._rawComposite);
        const pickComposite = computeCanonicalCompositeFromSiteValues(direct.data || {}, {
          isPick: true,
          playerName,
          playerPos: 'PICK',
          pickValuesCanonical: !!(direct?.data?.__canonical),
        });
        const siteDetails = pickComposite?.siteDetails || {};
        return {
          metaValue: Math.round(directComp),
          rawMarketValue: Math.round(isFinite(raw) && raw > 0 ? raw : (pickComposite?.rawCompositeValue || directComp)),
          siteCount: Math.max(1, Number(direct?.data?._sites) || Number(pickComposite?.siteCount) || Object.keys(siteDetails).length || 1),
          siteDetails,
          cv: 0,
        };
      }
      const pickData = resolvePickSiteValues(pickInfo);
      if (pickData) {
        const pickResult = computeMetaFromSiteValues(pickData, { isPick: true, playerName });
        if (pickResult && pickResult.metaValue > 0) return pickResult;
        const ktcVal = Number(pickData.ktc);
        if (isFinite(ktcVal) && ktcVal > 0) {
          return {
            metaValue: Math.round(ktcVal),
            rawMarketValue: Math.round(ktcVal),
            siteCount: 1,
            siteDetails: { ktc: Math.round(ktcVal) },
            cv: 0,
          };
        }
      }
      return null;
    }

    let pData = direct?.data || null;
    if (!pData) return null;

    const playerIsTE = isPlayerTE(playerName);
    const playerPos = (getPlayerPosition(playerName) || '').toUpperCase();
    const playerIsIdp = IDP_POSITIONS.has(playerPos);
    const hasBackendCanonicalMap = !!(
      pData &&
      typeof pData._canonicalSiteValues === 'object' &&
      Object.keys(pData._canonicalSiteValues).length
    );
    const backendCanonicalSites = hasBackendCanonicalMap
      ? Object.fromEntries(Object.entries(pData._canonicalSiteValues).filter(([,v]) => Number.isFinite(Number(v)) && Number(v) > 0).map(([k,v]) => [k, Math.round(Number(v))]))
      : null;

    const buildValueOutput = (rawValue, base = {}) => {
      const raw = clampValue(Math.round(Number(rawValue) || 0), 1, COMPOSITE_SCALE);
      if (rawOnly) {
        return {
          ...base,
          metaValue: raw,
          rawMarketValue: raw,
          scoringAdjustedValue: raw,
          scarcityAdjustedValue: raw,
          finalAdjustedValue: raw,
          valueDelta: 0,
          authoritySource: String(base?.authoritySource || 'backend_raw'),
        };
      }
      const adjPos = playerPos || (getPlayerPosition(playerName) || '');
      const precomputed = getPrecomputedAdjustmentBundle(direct?.data, raw, adjPos, direct?.name || playerName);
      const adjBundle = precomputed || computeFinalAdjustedValue(raw, adjPos, direct?.name || playerName, {
        siteCount: Number(base?.siteCount || 0),
        cv: Number(base?.cv),
        siteDetails: base?.siteDetails || {},
      });
      return {
        ...base,
        metaValue: clampValue(Math.round(Number(adjBundle?.finalAdjustedValue) || raw), 1, COMPOSITE_SCALE),
        rawMarketValue: raw,
        baselineBucket: adjBundle?.scoring?.baselineBucket || null,
        scoringMultiplierRaw: adjBundle?.scoring?.leagueMultiplier ?? adjBundle?.scoring?.rawLeagueMultiplier ?? 1,
        scoringMultiplierEffective: adjBundle?.scoring?.effectiveMultiplier ?? 1,
        rawLeagueMultiplier: adjBundle?.scoring?.rawLeagueMultiplier ?? 1,
        shrunkLeagueMultiplier: adjBundle?.scoring?.shrunkLeagueMultiplier ?? 1,
        adjustmentStrength: adjBundle?.scoring?.adjustmentStrength ?? getLAMStrength(),
        scarcityBucket: adjBundle?.scarcity?.scarcityBucket || null,
        scarcityMultiplierRaw: adjBundle?.scarcity?.scarcityMultiplierRaw ?? 1,
        scarcityMultiplierEffective: adjBundle?.scarcity?.scarcityMultiplierEffective ?? 1,
        scarcityStrength: adjBundle?.scarcity?.scarcityStrength ?? getScarcityStrength(),
        replacementRank: adjBundle?.scarcity?.replacementRank ?? 0,
        replacementValue: adjBundle?.scarcity?.replacementValue ?? 0,
        valueAboveReplacement: adjBundle?.scarcity?.valueAboveReplacement ?? 0,
        marketReliabilityScore: adjBundle?.marketReliability?.score ?? 0,
        marketReliabilityLabel: adjBundle?.marketReliability?.label ?? '',
        effectiveMultiplier: adjBundle?.combinedMultiplier ?? 1,
        scoringAdjustedValue: adjBundle?.scoringAdjustedValue ?? raw,
        scarcityAdjustedValue: adjBundle?.scarcityAdjustedValue ?? raw,
        finalAdjustedValue: adjBundle?.finalAdjustedValue ?? raw,
        valueDelta: adjBundle?.valueDelta ?? 0,
        authoritySource: String(base?.authoritySource || (precomputed ? 'backend_adjusted' : 'frontend_adjusted_fallback')),
      };
    };

    const backendRawComposite = Number(pData?._rawComposite ?? pData?._rawMarketValue ?? pData?._composite);
    if (Number.isFinite(backendRawComposite) && backendRawComposite > 0) {
      return buildValueOutput(backendRawComposite, {
        siteCount: Math.max(1, Number(pData?._sites) || Object.keys(backendCanonicalSites || {}).length || 1),
        siteDetails: backendCanonicalSites || (pData?.__canonical ? { __canonical: 'yes' } : {}),
        cv: Number(pData?._marketDispersionCV ?? 0) || 0,
        authoritySource: 'backend',
      });
    }

    if (!allowFrontendCompositeFallback) {
      return null;
    }

    // Explicit fallback: only used when backend did not provide authoritative
    // raw composite fields for this player.
    const composite = computeCanonicalCompositeFromSiteValues(pData, {
      playerName,
      playerPos,
      playerIsTE,
      playerIsIdp,
      isPick: false,
    });

    if (!composite) {
      const preComp = Number(pData._composite);
      if (isFinite(preComp) && preComp > 0) {
        const preRaw = Number(pData._rawComposite);
        const fallbackRaw = clampValue(Math.round(isFinite(preRaw) && preRaw > 0 ? preRaw : preComp), 1, COMPOSITE_SCALE);
        return buildValueOutput(fallbackRaw, {
          siteCount: Math.max(1, Number(pData._sites) || 1),
          siteDetails: pData.__canonical ? { __canonical: 'yes' } : {},
          cv: 0,
          authoritySource: 'legacy_composite_fallback',
        });
      }
      return null;
    }

    return buildValueOutput(composite.rawCompositeValue, {
      siteCount: composite.siteCount,
      siteDetails: composite.siteDetails,
      cv: composite.cv,
      authoritySource: 'frontend_composite_fallback',
    });
  }
