/*
 * Runtime Module: 30-more-surfaces.js
 * Trades history, waiver, league edge, and roster dashboard surfaces.
 * Extracted from legacy monolithic inline runtime to keep live behavior intact.
 */

  // ── TRADE HISTORY GRADES ──
  function buildTradeGrades() {
    const card = document.getElementById('tradeGradesCard');
    const div = document.getElementById('tradeGrades');
    if (!card || !div || !loadedData) return;
    const trades = filterTradesToRollingWindow(loadedData.sleeper?.trades);
    if (!trades || !trades.length) { card.style.display = 'none'; return; }

    let html = '';
    for (const trade of trades.slice(0, 15)) {
      const ts = normalizeTradeTimestampMs(trade.timestamp);
      const date = ts ? new Date(ts).toLocaleDateString() : '?';
      let tradeHtml = `<div style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px;margin-bottom:10px;">`;
      tradeHtml += `<div style="font-size:0.68rem;color:var(--subtext);margin-bottom:6px;">Week ${trade.week} · ${date}</div>`;

      let sideTotals = [];
      for (const side of trade.sides) {
        let gotTotal = 0, gotItems = [];
        for (const rawItem of getTradeSideItemLabels(side?.got)) {
          const tiv = getTradeItemValue(rawItem);
          const val = tiv.metaValue;
          const safeVal = Number.isFinite(val) ? Math.max(0, Number(val)) : 0;
          gotTotal += safeVal;
          const itemName = tiv.displayName || rawItem;
          const pos = tiv.isPick ? '' : (getPlayerPosition(tiv.resolvedName || itemName) || '');
          gotItems.push({ name: itemName, val: safeVal, pos, isPick: tiv.isPick });
        }
        sideTotals.push({ team: side.team, total: gotTotal, items: gotItems });
      }

      // Determine winner
      const maxTotal = Math.max(...sideTotals.map(s => s.total));
      const minTotal = Math.min(...sideTotals.map(s => s.total));
      const pctGap = maxTotal > 0 ? ((maxTotal - minTotal) / maxTotal) * 100 : 0;

      for (const side of sideTotals) {
        const isWinner = sideTotals.length > 1 && side.total === maxTotal && pctGap > 3;
        const borderColor = isWinner ? 'var(--green)' : (side.total === minTotal && pctGap > 3 ? 'var(--red)' : 'var(--border)');
        tradeHtml += `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-left:3px solid ${borderColor};padding-left:8px;margin:4px 0;">`;
        tradeHtml += `<span style="font-weight:600;min-width:100px;font-size:0.72rem;">${side.team}</span>`;
        tradeHtml += `<span style="flex:1;font-size:0.68rem;color:var(--subtext);">got: ${side.items.map(i => i.name).join(', ')}</span>`;
        tradeHtml += `<span style="font-family:var(--mono);font-size:0.72rem;font-weight:600;">${side.total.toLocaleString()}</span>`;
        tradeHtml += `</div>`;
      }

      if (pctGap > 3 && sideTotals.length >= 2) {
        const sorted = [...sideTotals].sort((a, b) => b.total - a.total);
        const grade = pctGap < 8 ? 'B' : pctGap < 15 ? 'C' : pctGap < 25 ? 'D' : 'F';
        const gradeColor = {B:'var(--green)',C:'var(--amber)',D:'var(--red)',F:'var(--red)'}[grade];
        tradeHtml += `<div style="font-size:0.68rem;margin-top:4px;"><span style="font-weight:700;color:${gradeColor};">Grade: ${grade}</span> — ${sorted[0].team} won by ${pctGap.toFixed(0)}%</div>`;
      } else {
        tradeHtml += `<div style="font-size:0.68rem;margin-top:4px;color:var(--green);font-weight:600;">Fair trade (within 3%)</div>`;
      }
      tradeHtml += `</div>`;
      html += tradeHtml;
    }

    div.innerHTML = html || '<div style="color:var(--subtext);font-size:0.72rem;">No trades found.</div>';
    card.style.display = 'block';
  }

  // ── TRADE HISTORY PAGE (Trades Tab) ──
  function buildTradeHistoryPage() {
    const listDiv = document.getElementById('tradeHistoryList');
    const statsCard = document.getElementById('tradeStatsCard');
    const statsDiv = document.getElementById('tradeStats');
    if (!listDiv) return;

    if (!loadedData || !loadedData.sleeper?.trades?.length) {
      tradeHistoryRenderCache = [];
      listDiv.innerHTML = '<div class="card"><p style="color:var(--subtext);padding:12px;">No trade data available. Load dynasty data with a Sleeper league.</p></div>';
      if (statsCard) statsCard.style.display = 'none';
      return;
    }

    const analysis = analyzeSleeperTradeHistory();
    const windowDays = Number(analysis?.windowDays || getTradeHistoryWindowDays());
    const analyzed = Array.isArray(analysis?.analyzed) ? analysis.analyzed : [];
    const teamScores = analysis?.teamScores || {};
    if (!analyzed.length) {
      tradeHistoryRenderCache = [];
      listDiv.innerHTML = `<div class="card"><p style="color:var(--subtext);padding:12px;">No completed trades found in the last ${windowDays} days.</p></div>`;
      if (statsCard) statsCard.style.display = 'none';
      return;
    }
    const teamFilter = document.getElementById('tradeTeamFilter')?.value || '';
    const alpha = parseFloat(document.getElementById('alphaSlider')?.value) || 1.075;

    // Filter by team if set
    let filtered = analyzed;
    if (teamFilter) {
      filtered = analyzed.filter(a => a.sides.some(s => s.team === teamFilter));
    }
    tradeHistoryRenderCache = filtered.slice();

    // ── Stats Card: Trade Winners & Losers ──
    if (statsDiv && statsCard) {
      const sorted = Object.entries(teamScores).sort((a, b) => b[1].totalGain - a[1].totalGain);
      let statsHtml = '<div class="section-head"><span class="section-head-title">Trade Winners & Losers</span></div>';
      statsHtml += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">';
      for (const [teamName, s] of sorted) {
        const netSign = s.totalGain >= 0 ? '+' : '';
        const netColor = s.totalGain >= 0 ? 'var(--green)' : 'var(--red)';
        const record = `${s.won}W-${s.lost}L`;
        const borderLeftColor = s.totalGain >= 0 ? 'var(--green)' : s.totalGain < -50 ? 'var(--red)' : 'var(--border)';
        statsHtml += `<div style="border:1px solid var(--border);border-left:3px solid ${borderLeftColor};border-radius:6px;padding:10px 14px;">`;
        statsHtml += `<div style="font-weight:700;font-size:0.78rem;">${teamName}</div>`;
        statsHtml += `<div style="font-family:var(--mono);font-size:0.68rem;color:var(--subtext);margin:2px 0;">${s.trades} trades · ${record}</div>`;
        statsHtml += `<div style="font-family:var(--mono);font-size:0.75rem;font-weight:700;color:${netColor};">${netSign}${Math.round(Math.pow(Math.abs(s.totalGain), 1/alpha)).toLocaleString()} net value</div>`;
        statsHtml += `</div>`;
      }
      statsHtml += '</div>';
      statsDiv.innerHTML = statsHtml;
      statsCard.style.display = 'block';
    }

    // ── Trade List ──
    let listHtml = '';
    for (let idx = 0; idx < filtered.length; idx++) {
      const a = filtered[idx];
      const cardBorder = a.pctGap >= 3
        ? (a.winner === a.sides[0] ? 'trade-history-winner' : 'trade-history-loser')
        : 'trade-history-fair';
      listHtml += `<div class="trade-history-card ${cardBorder}">`;
      listHtml += `<div class="trade-history-card-header">`;
      listHtml += `<span>Week ${a.trade.week} · ${a.date}</span>`;
      if (a.pctGap >= 3) {
        listHtml += `<span class="stat-pill stat-pill-green"><span class="stat-pill-label">${a.winner.team} won by</span> <span class="stat-pill-val">${a.pctGap.toFixed(1)}%</span></span>`;
      } else {
        listHtml += `<span class="stat-pill stat-pill-green"><span class="stat-pill-val">Fair trade</span></span>`;
      }
      listHtml += `</div>`;

      listHtml += `<div class="trade-history-sides">`;
      for (const side of a.sides) {
        const isWinner = side === a.winner && a.pctGap >= 3;
        const isLoser = side === a.loser && a.pctGap >= 3;
        const grade = isWinner ? a.winnerGrade : isLoser ? a.loserGrade : { grade: 'A', color: 'var(--green)', label: 'Fair' };

        listHtml += `<div class="trade-history-side">`;
        listHtml += `<div class="trade-history-side-label" style="display:flex;align-items:center;gap:6px;">`;
        listHtml += `<span>${side.team}</span>`;
        listHtml += `<span style="font-size:0.72rem;font-weight:800;color:${grade.color};">${grade.grade}</span>`;
        listHtml += `<span style="font-size:0.52rem;color:var(--subtext);font-weight:400;">${grade.label}</span>`;
        listHtml += `</div>`;

        listHtml += `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px;">`;
        for (const item of side.items) {
          const posC = item.isPick ? 'var(--amber)' :
            ({'QB':'#e74c3c','RB':'#27ae60','WR':'#3498db','TE':'#e67e22'}[item.pos] || '#9b59b6');
          const posLabel = item.isPick ? 'PICK' : item.pos;
          listHtml += `<span style="font-size:0.66rem;padding:2px 6px;border:1px solid var(--border);border-radius:4px;background:var(--bg-soft);">`;
          listHtml += `<span style="color:${posC};font-weight:700;font-size:0.58rem;">${posLabel}</span> `;
          listHtml += `${item.name} <span style="font-family:var(--mono);color:var(--subtext);">${item.val.toLocaleString()}</span>`;
          listHtml += `</span>`;
        }
        listHtml += `</div>`;
        listHtml += `<div style="font-family:var(--mono);font-size:0.62rem;color:var(--subtext);">Total: ${Math.round(side.weighted).toLocaleString()}</div>`;
        listHtml += `</div>`;
      }
      listHtml += `</div>`;

      listHtml += `<div style="margin-top:8px;display:flex;justify-content:flex-end;">`;
      listHtml += `<button class="mobile-chip-btn primary" onclick="openHistoricalTradeInBuilder(${idx})">Open Builder</button>`;
      listHtml += `</div>`;
      listHtml += `</div>`;
    }

    listDiv.innerHTML = listHtml || '<div class="card"><p style="color:var(--subtext);padding:12px;">No trades match the filter.</p></div>';
  }

  // ── WAIVER WIRE GEMS ──
  function buildWaiverWire() {
    const card = document.getElementById('waiverWireCard');
    const div = document.getElementById('waiverWire');
    if (!card || !div || !loadedData || !sleeperTeams.length) { if (card) card.style.display = 'none'; return; }

    // Get all rostered player names
    const rosteredSet = new Set();
    sleeperTeams.forEach(t => t.players.forEach(p => rosteredSet.add(p.toLowerCase())));

    // Find unrostered players with high composite values
    const unrostered = [];
    for (const name of Object.keys(loadedData.players)) {
      if (rosteredSet.has(name.toLowerCase())) continue;
      // Skip draft picks
      if (parsePickToken(name)) continue;
      const result = computeMetaValueForPlayer(name);
      if (!result || result.metaValue < 500) continue;
      const pos = getPlayerPosition(name) || '';
      // Skip kickers
      if (isKickerPosition(pos)) continue;
      // Skip rookies
      const pData = loadedData.players[name];
      const team = pData?.team || (loadedData.sleeper?.positions?.[name] ? '' : '');
      if (isRookiePlayerName(name, pData)) continue;
      // Check if player has no NFL team (likely a rookie prospect)
      const sleeperPos = loadedData.sleeper?.positions || {};
      const playerTeam = loadedData.sleeper?.teams?.find(t => t.players.some(p => p.toLowerCase() === name.toLowerCase()));
      // If player isn't on any Sleeper roster AND isn't in the NFL player db, they're likely a rookie
      const isKnownNFL = Object.keys(sleeperPos).some(k => k.toLowerCase() === name.toLowerCase());
      if (!isKnownNFL && !playerTeam) continue;
      unrostered.push({ name, meta: result.metaValue, pos, sites: result.siteCount });
    }

    unrostered.sort((a, b) => b.meta - a.meta);
    const top = unrostered.slice(0, 25);

    if (!top.length) {
      div.innerHTML = '<div style="color:var(--subtext);font-size:0.72rem;">No high-value free agents found — your league is well-managed.</div>';
      card.style.display = 'block';
      return;
    }

    const POS_C = {QB:'#e74c3c',RB:'#27ae60',WR:'#3498db',TE:'#e67e22',LB:'#9b59b6',DL:'#9b59b6',DE:'#9b59b6',DT:'#9b59b6',EDGE:'#9b59b6',CB:'#16a085',S:'#16a085',DB:'#16a085'};
    let html = `<div style="font-size:0.68rem;color:var(--subtext);margin-bottom:8px;">Players not on any roster with meaningful trade value. Higher value = bigger opportunity.</div>`;
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;">';
    for (const p of top) {
      const posC = POS_C[(p.pos || '').toUpperCase()] || 'var(--subtext)';
      const sitesLabel = p.sites >= 5 ? '' : p.sites >= 3 ? '' : ` · <span style="color:var(--amber);font-size:0.58rem;">${p.sites} src</span>`;
      html += `<div style="display:flex;align-items:center;gap:6px;padding:5px 10px;border:1px solid var(--border);border-radius:6px;font-size:0.72rem;">`;
      html += `<span style="color:${posC};font-weight:700;font-family:var(--mono);font-size:0.62rem;">${p.pos}</span>`;
      html += `<span style="font-weight:600;">${p.name}</span>`;
      html += `<span style="font-family:var(--mono);color:var(--subtext);">${p.meta.toLocaleString()}${sitesLabel}</span>`;
      html += `</div>`;
    }
    html += '</div>';
    div.innerHTML = html;
    card.style.display = 'block';
  }

  // ── LEAGUE-WIDE EDGE MAP ──
  function buildLeagueEdge() {
    const card = document.getElementById('leagueEdgeCard');
    const div = document.getElementById('leagueEdge');
    if (!card || !div || !loadedData || !sleeperTeams.length) { if (card) card.style.display = 'none'; return; }

    const myTeamName = document.getElementById('rosterMyTeam')?.value || '';

    // For each team, sum up market-vs-model edge for their players
    const teamEdges = [];
    for (const team of sleeperTeams) {
      let totalBuyEdge = 0, totalSellEdge = 0, buyCount = 0, sellCount = 0;
      const topBuys = [], topSells = [];

      for (const pName of team.players) {
        if (parsePickToken(pName)) continue;
        const edge = getPlayerEdge(pName);
        if (!edge) continue;
        const pctDiff = edge.pctDiff; // legacy sign: positive = market overvalues (SELL), negative = BUY
        if (pctDiff > MIN_EDGE_PCT) {
          totalSellEdge += pctDiff;
          sellCount++;
          topSells.push({ name: pName, pct: pctDiff });
        } else if (pctDiff < -MIN_EDGE_PCT) {
          totalBuyEdge += Math.abs(pctDiff);
          buyCount++;
          topBuys.push({ name: pName, pct: pctDiff });
        }
      }

      topSells.sort((a, b) => b.pct - a.pct);
      topBuys.sort((a, b) => a.pct - b.pct);

      teamEdges.push({
        name: team.name,
        isMe: team.name === myTeamName,
        sellEdge: Math.round(totalSellEdge),
        buyEdge: Math.round(totalBuyEdge),
        sellCount, buyCount,
        topSells: topSells.slice(0, 3),
        topBuys: topBuys.slice(0, 3),
      });
    }

    // Sort by most exploitable (highest SELL edge = most overvalued by market)
    teamEdges.sort((a, b) => b.sellEdge - a.sellEdge);
    const maxEdge = Math.max(1, ...teamEdges.map(t => Math.max(t.sellEdge, t.buyEdge)));

    let html = '';
    for (const t of teamEdges) {
      const isMe = t.isMe;
      const rowBg = isMe ? 'rgba(200, 56, 3, 0.08)' : '';
      const sellPct = Math.round((t.sellEdge / maxEdge) * 100);
      const buyPct = Math.round((t.buyEdge / maxEdge) * 100);

      html += `<div style="padding:8px 10px;border-bottom:1px solid var(--border-dim);background:${rowBg};${isMe ? 'border-left:3px solid var(--cyan);' : ''}">`;
      html += `<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">`;
      html += `<span style="font-weight:600;min-width:130px;font-size:0.73rem;">${t.name}${isMe ? ' ⭐' : ''}</span>`;
      html += `<div style="flex:1;display:flex;gap:4px;align-items:center;">`;
      html += `<div style="width:${sellPct}%;height:10px;background:var(--red);border-radius:2px;min-width:${t.sellEdge > 0 ? 2 : 0}px;" title="Market overvalues ${t.sellCount} of their players by avg ${t.sellEdge}%"></div>`;
      html += `<span style="font-size:0.6rem;color:var(--red);font-family:var(--mono);min-width:35px;" title="${t.sellCount} overvalued players">${t.sellCount} sell</span>`;
      html += `<div style="width:${buyPct}%;height:10px;background:var(--green);border-radius:2px;min-width:${t.buyEdge > 0 ? 2 : 0}px;" title="Market undervalues ${t.buyCount} of their players by avg ${t.buyEdge}%"></div>`;
      html += `<span style="font-size:0.6rem;color:var(--green);font-family:var(--mono);" title="${t.buyCount} undervalued players">${t.buyCount} buy</span>`;
      html += `</div></div>`;

      // Show top exploitable players for this team
      if (t.topSells.length || t.topBuys.length) {
        html += `<div style="font-size:0.62rem;color:var(--subtext);padding-left:140px;">`;
        if (t.topSells.length) {
          html += `<span style="color:var(--red);">Market overvalues: ${t.topSells.map(p => `${p.name} +${p.pct.toFixed(0)}%`).join(', ')}</span>`;
        }
        if (t.topSells.length && t.topBuys.length) html += ' · ';
        if (t.topBuys.length) {
          html += `<span style="color:var(--green);">Market undervalues: ${t.topBuys.map(p => `${p.name} ${p.pct.toFixed(0)}%`).join(', ')}</span>`;
        }
        html += `</div>`;
      }
      html += `</div>`;
    }

    div.innerHTML = html;
    card.style.display = 'block';
  }

  // ── ROSTER STRENGTH DASHBOARD ──
  const POS_GROUP_COLORS = {
    QB: '#e74c3c',
    RB: '#27ae60',
    WR: '#3498db',
    TE: '#e67e22',
    DL: '#9b59b6',
    LB: '#8e44ad',
    DB: '#16a085',
    PICKS: '#f39c12',
    Other: '#7f8c8d',
  };
  const IDP_POS = new Set(['EDGE','DT','DL','DE','LB','CB','S','DB']);

  function posGroup(pos) {
    if (!pos) return 'Other';
    const p = pos.toUpperCase();
    if (['QB','RB','WR','TE'].includes(p)) return p;
    if (['DL','DE','DT','EDGE','NT'].includes(p)) return 'DL';
    if (['LB','OLB','ILB'].includes(p)) return 'LB';
    if (['DB','CB','S','FS','SS'].includes(p)) return 'DB';
    return 'Other';
  }

  const STARTER_SLOTS_BY_GROUP = {
    QB: 2,
    RB: 3,
    WR: 4,
    TE: 2,
    DL: 2,
    LB: 2,
    DB: 2,
  };

  function getRosterValueMode() {
    const mode = document.getElementById('rosterValueMode')?.value || 'full';
    return ['full', 'players', 'starters'].includes(mode) ? mode : 'full';
  }

  function sumTopN(values, n) {
    if (!Array.isArray(values) || n <= 0) return 0;
    return values
      .filter(v => isFinite(v) && v > 0)
      .sort((a, b) => b - a)
      .slice(0, n)
      .reduce((s, v) => s + v, 0);
  }

  function estimatePickAssetValue(pName) {
    const pickInfo = parsePickToken(pName);
    if (!pickInfo) return 0;
    const direct = computeMetaValueForPlayer(pName);
    if (direct && direct.metaValue > 0) return direct.metaValue;
    const pData = resolvePickSiteValues(pickInfo);
    if (!pData) return 0;
    const pickResult = computeMetaFromSiteValues(pData, { isPick: true, playerName: pName });
    if (pickResult && pickResult.metaValue > 0) return pickResult.metaValue;
    const ktcVal = Number(pData.ktc);
    if (isFinite(ktcVal) && ktcVal > 0) return ktcVal;
    let sum = 0;
    let cnt = 0;
    for (const v of Object.values(pData)) {
      if (typeof v === 'number' && isFinite(v) && v > 0) {
        sum += v;
        cnt++;
      }
    }
    return cnt ? (sum / cnt) : 0;
  }

  function buildTeamValueBreakdown(team, playerMeta, allGroups, valueMode) {
    const byGroup = {};
    allGroups.forEach(g => { byGroup[g] = 0; });
    const playerDetails = [];
    const buckets = { QB: [], RB: [], WR: [], TE: [], DL: [], LB: [], DB: [] };
    let pickValue = 0;
    const teamPlayers = Array.isArray(team.players) ? team.players : [];
    const teamPicks = Array.isArray(team.picks) ? team.picks : [];
    const hasExplicitPicks = teamPicks.length > 0;

    for (const pName of teamPlayers) {
      if (parsePickToken(pName)) {
        // Backward-compat: old payloads may have picks mixed into players.
        if (!hasExplicitPicks && valueMode === 'full') pickValue += estimatePickAssetValue(pName);
        continue;
      }

      const key = pName.toLowerCase();
      const pm = playerMeta[key];
      if (!pm) continue;
      playerDetails.push(pm);

      if (valueMode !== 'starters') {
        if (byGroup[pm.group] !== undefined) byGroup[pm.group] += pm.meta;
      }
      if (buckets[pm.group]) buckets[pm.group].push(pm.meta);
    }

    if (valueMode === 'full' && hasExplicitPicks) {
      for (const pickName of teamPicks) {
        if (parsePickToken(pickName)) pickValue += estimatePickAssetValue(pickName);
      }
    }

    if (valueMode === 'starters') {
      Object.keys(buckets).forEach(g => {
        byGroup[g] = sumTopN(buckets[g], STARTER_SLOTS_BY_GROUP[g] || 0);
      });
    }

    byGroup.PICKS = valueMode === 'full' ? pickValue : 0;
    const total = allGroups.reduce((s, g) => s + (byGroup[g] || 0), 0);

    return { total, byGroup, playerDetails };
  }

  function populateRosterTeamDropdown() {
    const sel = document.getElementById('rosterMyTeam');
    if (!sel) return;
    sel.innerHTML = '<option value="">— select your team —</option>';
    sleeperTeams.forEach(team => {
      const opt = document.createElement('option');
      opt.value = team.name;
      opt.textContent = team.name;
      sel.appendChild(opt);
    });
    const preferred = resolvePreferredTeamName({
      teams: sleeperTeams,
      savedTeam: localStorage.getItem('dynasty_my_team') || '',
      profileTeam: getProfile()?.teamName || '',
    });
    if (preferred) sel.value = preferred;
  }

  function buildRosterDashboard() {
    const container = document.getElementById('rosterRankings');
    if (!container) return;

    if (!loadedData || !sleeperTeams.length) {
      container.innerHTML = '<p style="color:var(--subtext);font-size:0.8rem;padding:12px;">Load dynasty data with Sleeper league to see roster rankings.</p>';
      document.getElementById('tradeTargetsCard').style.display = 'none';
      return;
    }

    const myTeamName = document.getElementById('rosterMyTeam')?.value || localStorage.getItem('dynasty_my_team') || '';
    const ALL_GROUPS = ['QB','RB','WR','TE','DL','LB','DB','PICKS'];
    const valueMode = getRosterValueMode();

    // Read which groups are checked (default: all offense + picks)
    const activeGroups = new Set();
    ALL_GROUPS.forEach(g => {
      const cb = document.getElementById('rosterFilter_' + g);
      if (!cb) { // First render - default on for offense
        if (['QB','RB','WR','TE','PICKS'].includes(g)) activeGroups.add(g);
      } else if (cb.checked) {
        activeGroups.add(g);
      }
    });

    // Compute MetaValue for every player
    const playerMeta = buildRosterPlayerMetaMap();

    // Build team summaries
    const teams = sleeperTeams.map(team => {
      const breakdown = buildTeamValueBreakdown(team, playerMeta, ALL_GROUPS, valueMode);

      return {
        name: team.name,
        roster_id: team.roster_id,
        total: breakdown.total,
        byGroup: breakdown.byGroup,
        playerCount: team.players.length,
        pickCount: Array.isArray(team.picks) ? team.picks.length : 0,
        players: breakdown.playerDetails,
      };
    });

    // Sort by sum of ACTIVE groups only
    teams.forEach(t => {
      t.activeTotal = 0;
      activeGroups.forEach(g => { t.activeTotal += t.byGroup[g] || 0; });
    });
    teams.sort((a, b) => b.activeTotal - a.activeTotal);
    const maxTotal = teams[0]?.total || 1;
    const maxActiveTotal = teams[0]?.activeTotal || 1;

    // Group averages for strength/weakness
    const groupTotals = {};
    ALL_GROUPS.forEach(g => groupTotals[g] = []);
    teams.forEach(t => {
      ALL_GROUPS.forEach(g => groupTotals[g].push(t.byGroup[g] || 0));
    });
    const groupAvg = {};
    for (const [g, vals] of Object.entries(groupTotals)) {
      groupAvg[g] = vals.length ? vals.reduce((a,b) => a+b, 0) / vals.length : 0;
    }

    // ── Render ──
    // Section header
    let html = '<div class="section-head">';
    html += '<span class="section-head-title">Power Rankings</span>';
    const lensLabel = valueMode === 'full' ? 'Players + Picks' : valueMode === 'players' ? 'Players only' : 'Starters only';
    html += `<span class="section-head-badge">${lensLabel}</span>`;
    html += '</div>';

    // Position filter bar
    html += '<div class="filter-bar">';
    html += '<span style="font-weight:600;color:var(--subtext);">Positions:</span>';
    const offGroups = ['QB','RB','WR','TE','PICKS'];
    const defGroups = ['DL','LB','DB'];
    ALL_GROUPS.forEach(g => {
      const checked = activeGroups.has(g) ? 'checked' : '';
      const color = POS_GROUP_COLORS[g] || 'var(--subtext)';
      const sep = g === 'DL' ? '<span style="width:1px;height:16px;background:var(--border);margin:0 2px;"></span>' : '';
      html += sep;
      html += `<label style="display:flex;align-items:center;gap:3px;font-size:0.68rem;cursor:pointer;">`;
      html += `<input type="checkbox" id="rosterFilter_${g}" ${checked} onchange="buildRosterDashboard()" style="width:13px;height:13px;accent-color:${color};">`;
      html += `<span style="color:${color};font-weight:700;">${g}</span></label>`;
    });
    html += '</div>';

    // Legend
    html += '<div class="roster-legend">';
    ALL_GROUPS.forEach(g => {
      if (!activeGroups.has(g)) return;
      const color = POS_GROUP_COLORS[g] || 'var(--subtext)';
      html += `<div class="roster-legend-item"><div class="roster-legend-swatch" style="background:${color}"></div>${g}</div>`;
    });
    html += '</div>';

    // Header
    html += '<div class="roster-header">';
    html += '<div style="width:28px">#</div>';
    html += '<div style="width:140px">Team</div>';
    html += '<div style="width:65px;text-align:right">Total</div>';
    html += '<div style="flex:1">Position Breakdown</div>';
    html += '</div>';

    // Team rows
    teams.forEach((team, idx) => {
      const isMyTeam = team.name === myTeamName;
      html += `<div class="roster-team-row${isMyTeam ? ' my-team' : ''}">`;
      html += `<div class="roster-rank">${idx + 1}</div>`;
      const pickLabel = team.pickCount ? `, ${team.pickCount} picks` : '';
      html += `<div class="roster-name" title="${team.name} (${team.playerCount} players${pickLabel})">${team.name}</div>`;
      html += `<div class="roster-total">${Math.round(team.activeTotal).toLocaleString()}</div>`;

      // Stacked bar (only active groups)
      html += '<div class="roster-bar-wrap">';
      ALL_GROUPS.forEach(g => {
        if (!activeGroups.has(g)) return;
        const gVal = team.byGroup[g] || 0;
        if (gVal <= 0) return;
        const pct = (gVal / maxActiveTotal) * 100;
        const label = pct > 4 ? `${g} ${Math.round(gVal / 1000)}k` : '';
        html += `<div class="roster-bar-seg" style="width:${pct.toFixed(1)}%;background:${POS_GROUP_COLORS[g]}" title="${g}: ${Math.round(gVal).toLocaleString()}">${label}</div>`;
      });
      html += '</div>'; // bar-wrap
      html += '</div>'; // row
    });

    container.innerHTML = html;

    // ── TRADE TARGET FINDER ──
    const targetsCard = document.getElementById('tradeTargetsCard');
    const targetsDiv = document.getElementById('tradeTargets');
    if (!myTeamName || !targetsCard || !targetsDiv) {
      if (targetsCard) targetsCard.style.display = 'none';
      return;
    }

    const myTeam = teams.find(t => t.name === myTeamName);
    if (!myTeam) {
      targetsCard.style.display = 'none';
      return;
    }

    // Find weakest offensive position group relative to league average
    const offGroups = ['QB','RB','WR','TE'];
    const myStrengths = {};
    offGroups.forEach(g => {
      myStrengths[g] = groupAvg[g] > 0 ? (myTeam.byGroup[g] || 0) / groupAvg[g] : 1;
    });

    // Sort by weakness (lowest ratio = most below average)
    const weakest = offGroups.slice().sort((a,b) => myStrengths[a] - myStrengths[b]);
    const strongest = offGroups.slice().sort((a,b) => myStrengths[b] - myStrengths[a]);

    // Find my surplus players (top positions where I'm strong)
    const myPlayerSet = new Set(myTeam.players.map(p => p.name.toLowerCase()));

    let targetsHtml = '';

    // Summary — stronger visual treatment for strength/weakness
    targetsHtml += '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px;">';
    targetsHtml += `<span class="stat-pill stat-pill-green"><span class="stat-pill-label">Strongest</span> <span class="stat-pill-val" style="color:${POS_GROUP_COLORS[strongest[0]]}">${strongest[0]} (${(myStrengths[strongest[0]]*100).toFixed(0)}%)</span></span>`;
    targetsHtml += `<span class="stat-pill stat-pill-red"><span class="stat-pill-label">Weakest</span> <span class="stat-pill-val" style="color:${POS_GROUP_COLORS[weakest[0]]}">${weakest[0]} (${(myStrengths[weakest[0]]*100).toFixed(0)}%)</span></span>`;
    targetsHtml += '</div>';

    // Find trade targets at our two weakest positions from teams that are strong there
    const needPositions = weakest.slice(0, 2);

    for (const needPos of needPositions) {
      const pctOfAvg = (myStrengths[needPos] * 100).toFixed(0);
      targetsHtml += `<div class="trade-target-group">`;
      targetsHtml += `<h4>Need: ${needPos} <span style="font-weight:400;font-size:0.7rem;color:var(--subtext);">(you're at ${pctOfAvg}% of league avg)</span></h4>`;

      // Collect targets: players at needPos from other teams who are above average at that position
      const targets = [];
      for (const otherTeam of teams) {
        if (otherTeam.name === myTeamName) continue;
        const otherStrength = groupAvg[needPos] > 0 ? (otherTeam.byGroup[needPos] || 0) / groupAvg[needPos] : 0;
        // Only target teams that are at or above average at this position (they have surplus)
        if (otherStrength < 1.0) continue;

        for (const p of otherTeam.players) {
          if (p.group !== needPos) continue;
          // Filter to mid-tier tradeable range — not their QB1 or star, not waiver-wire fodder
          // Rough heuristic: MetaValue between 1500 and 7500 is the "tradeable" band
          if (p.meta < 1200 || p.meta > 8000) continue;
          targets.push({
            ...p,
            teamName: otherTeam.name,
            teamStrength: otherStrength,
          });
        }
      }

      // Sort by MetaValue descending, take top 8
      targets.sort((a, b) => b.meta - a.meta);
      const shown = targets.slice(0, 8);

      if (shown.length === 0) {
        targetsHtml += '<div class="tt-note">No clear trade targets — other teams are also thin here.</div>';
      } else {
        for (const t of shown) {
          // Find what the other team is weakest at (potential counter-offer position)
          const otherTeamData = teams.find(tm => tm.name === t.teamName);
          let theirNeed = '';
          if (otherTeamData) {
            let worstRatio = Infinity, worstPos = '';
            for (const g of offGroups) {
              const ratio = groupAvg[g] > 0 ? (otherTeamData.byGroup[g] || 0) / groupAvg[g] : 1;
              if (ratio < worstRatio) { worstRatio = ratio; worstPos = g; }
            }
            if (worstPos && worstRatio < 1.0) {
              theirNeed = `they need ${worstPos}`;
            }
          }

          targetsHtml += '<div class="trade-target-row">';
          targetsHtml += `<div class="tt-pos" style="color:${POS_GROUP_COLORS[needPos]}">${t.pos}</div>`;
          targetsHtml += `<div class="tt-player">${t.name}</div>`;
          targetsHtml += `<div class="tt-meta">${t.meta.toLocaleString()}</div>`;
          targetsHtml += `<div class="tt-team">${t.teamName}${theirNeed ? ' <span style="color:var(--amber);">(' + theirNeed + ')</span>' : ''}</div>`;
          targetsHtml += '</div>';
        }
      }
      targetsHtml += '</div>';
    }

    // Show what I have to offer from my strongest positions
    const surplus = myTeam.players
      .filter(p => strongest.slice(0, 2).includes(p.group) && p.meta >= 1500)
      .sort((a, b) => b.meta - a.meta)
      .slice(0, 6);

    if (surplus.length > 0) {
      targetsHtml += '<div class="trade-target-group">';
      targetsHtml += '<h4 style="color:var(--green)">Your Trade Chips <span style="font-weight:400;font-size:0.7rem;color:var(--subtext);">(surplus from strong positions)</span></h4>';
      for (const p of surplus) {
        targetsHtml += '<div class="trade-target-row">';
        targetsHtml += `<div class="tt-pos" style="color:${POS_GROUP_COLORS[p.group]}">${p.pos}</div>`;
        targetsHtml += `<div class="tt-player">${p.name}</div>`;
        targetsHtml += `<div class="tt-meta">${p.meta.toLocaleString()}</div>`;
        targetsHtml += `<div class="tt-team" style="color:var(--green)">your roster</div>`;
        targetsHtml += '</div>';
      }
      targetsHtml += '</div>';
    }

    targetsDiv.innerHTML = targetsHtml;
    targetsCard.style.display = 'block';

    // Build additional roster features
    buildTradeGrades();
    buildWaiverWire();
  }
