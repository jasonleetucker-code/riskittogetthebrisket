/*
 * Runtime Module: 30-more-surfaces.js
 * Trades history, waiver, league edge, and roster dashboard surfaces.
 * Extracted from legacy monolithic inline runtime to keep live behavior intact.
 */

  // ── TRADE HISTORY GRADES ──
  async function buildTradeGrades() {
    const card = document.getElementById('tradeGradesCard');
    const div = document.getElementById('tradeGrades');
    if (!card || !div || !loadedData) return;
    const trades = filterTradesToRollingWindow(loadedData.sleeper?.trades);
    if (!trades || !trades.length) { card.style.display = 'none'; return; }

    div.innerHTML = '<div style="color:var(--subtext);font-size:0.72rem;">Loading backend-authoritative trade grades…</div>';
    card.style.display = 'block';
    try {
      const analysis = await analyzeSleeperTradeHistory();
      const diagnostics = analysis?.diagnostics || {};
      const analyzed = Array.isArray(analysis?.analyzed) ? analysis.analyzed : [];
      if (!analyzed.length) {
        const backendUnavailable = String(diagnostics?.authority || '').includes('unavailable');
        div.innerHTML = backendUnavailable
          ? '<div style="color:var(--amber);font-size:0.72rem;">Trade grades unavailable: backend trade scoring authority is currently unavailable.</div>'
          : '<div style="color:var(--subtext);font-size:0.72rem;">No trades found.</div>';
        card.style.display = 'block';
        return;
      }

      let html = '';
      const fallbackUsed = Number(diagnostics?.summary?.fallbackUsed || 0);
      if (fallbackUsed > 0) {
        html += `<div style="border:1px solid var(--amber);background:rgba(246,194,62,0.12);border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:0.68rem;color:var(--amber);">Backend authority scored these trades, but ${fallbackUsed} unresolved assets used explicit fallback values.</div>`;
      }
      for (const entry of analyzed.slice(0, 15)) {
        const trade = entry?.trade || {};
        const date = entry?.date || '?';
        const sideTotals = Array.isArray(entry?.sides) ? entry.sides : [];
        if (!sideTotals.length) continue;
        const maxTotal = Math.max(...sideTotals.map(s => Number(s?.weighted || 0)));
        const minTotal = Math.min(...sideTotals.map(s => Number(s?.weighted || 0)));
        const pctGap = maxTotal > 0 ? ((maxTotal - minTotal) / maxTotal) * 100 : 0;

        let tradeHtml = `<div style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px;margin-bottom:10px;">`;
        tradeHtml += `<div style="font-size:0.68rem;color:var(--subtext);margin-bottom:6px;">Week ${trade.week} · ${date}</div>`;
        for (const side of sideTotals) {
          const sideTotal = Number(side?.weighted || 0);
          const isWinner = sideTotals.length > 1 && sideTotal === maxTotal && pctGap > 3;
          const borderColor = isWinner ? 'var(--green)' : (sideTotal === minTotal && pctGap > 3 ? 'var(--red)' : 'var(--border)');
          tradeHtml += `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-left:3px solid ${borderColor};padding-left:8px;margin:4px 0;">`;
          tradeHtml += `<span style="font-weight:600;min-width:100px;font-size:0.72rem;">${side.team}</span>`;
          tradeHtml += `<span style="flex:1;font-size:0.68rem;color:var(--subtext);">got: ${side.items.map(i => i.name).join(', ')}</span>`;
          tradeHtml += `<span style="font-family:var(--mono);font-size:0.72rem;font-weight:600;">${Math.round(sideTotal).toLocaleString()}</span>`;
          tradeHtml += `</div>`;
        }

        if (pctGap > 3 && sideTotals.length >= 2) {
          const sorted = [...sideTotals].sort((a, b) => Number(b.weighted || 0) - Number(a.weighted || 0));
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
    } catch (err) {
      div.innerHTML = '<div style="color:var(--red);font-size:0.72rem;">Trade grades unavailable due to backend scoring error.</div>';
      card.style.display = 'block';
      console.error('[Trade Grades] Failed to render backend-authoritative grades.', err);
    }
  }

  // ── TRADE HISTORY PAGE (Trades Tab) ──
  let tradeHistoryBuildSeq = 0;
  async function buildTradeHistoryPage(opts = {}) {
    const runId = ++tradeHistoryBuildSeq;
    const shouldRenderMobilePreview = !!opts?.renderMobilePreview;
    const syncMobilePreview = () => {
      if (!shouldRenderMobilePreview) return;
      if (typeof renderMobileMoreTradesPreview === 'function') renderMobileMoreTradesPreview();
    };
    const listDiv = document.getElementById('tradeHistoryList');
    const statsCard = document.getElementById('tradeStatsCard');
    const statsDiv = document.getElementById('tradeStats');
    if (!listDiv) return;

    if (!loadedData || !loadedData.sleeper?.trades?.length) {
      tradeHistoryRenderCache = [];
      listDiv.innerHTML = '<div class="card"><p style="color:var(--subtext);padding:12px;">No trade data available. Load dynasty data with a Sleeper league.</p></div>';
      if (statsCard) statsCard.style.display = 'none';
      syncMobilePreview();
      return;
    }

    listDiv.innerHTML = '<div class="card"><p style="color:var(--subtext);padding:12px;">Scoring historical trades via backend authority…</p></div>';
    try {
      const analysis = await analyzeSleeperTradeHistory();
      if (runId !== tradeHistoryBuildSeq) return;
    const windowDays = Number(analysis?.windowDays || getTradeHistoryWindowDays());
    const analyzed = Array.isArray(analysis?.analyzed) ? analysis.analyzed : [];
    const teamScores = analysis?.teamScores || {};
      const diagnostics = analysis?.diagnostics || {};
    if (!analyzed.length) {
      tradeHistoryRenderCache = [];
        const backendUnavailable = String(diagnostics?.authority || '').includes('unavailable');
        listDiv.innerHTML = backendUnavailable
          ? '<div class="card"><p style="color:var(--amber);padding:12px;">Historical trade scoring unavailable: backend authority is not responding.</p></div>'
          : `<div class="card"><p style="color:var(--subtext);padding:12px;">No completed trades found in the last ${windowDays} days.</p></div>`;
      if (statsCard) statsCard.style.display = 'none';
        syncMobilePreview();
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
      let statsHtml = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">';
      for (const [teamName, s] of sorted) {
        const netSign = s.totalGain >= 0 ? '+' : '';
        const netColor = s.totalGain >= 0 ? 'var(--green)' : 'var(--red)';
        const record = `${s.won}W-${s.lost}L`;
        statsHtml += `<div style="border:1px solid var(--border);border-radius:6px;padding:8px 12px;">`;
        statsHtml += `<div style="font-weight:700;font-size:0.78rem;">${teamName}</div>`;
        statsHtml += `<div style="font-family:var(--mono);font-size:0.68rem;color:var(--subtext);">${s.trades} trades · ${record}</div>`;
        statsHtml += `<div style="font-family:var(--mono);font-size:0.72rem;font-weight:600;color:${netColor};">${netSign}${Math.round(Math.pow(Math.abs(s.totalGain), 1/alpha)).toLocaleString()} net value</div>`;
        statsHtml += `</div>`;
      }
      statsHtml += '</div>';
      statsDiv.innerHTML = statsHtml;
      statsCard.style.display = 'block';
    }

    // ── Trade List ──
    let listHtml = '';
      const fallbackRows = Number(diagnostics?.summary?.fallbackUsed || 0);
      const skippedTrades = Number(diagnostics?.tradesSkipped || 0);
      if (fallbackRows > 0) {
        listHtml += `<div class="card" style="border-color:var(--amber);background:rgba(246,194,62,0.12);"><p style="color:var(--amber);padding:10px 12px;font-size:0.72rem;">Backend authority scored this history, but ${fallbackRows} unresolved assets used explicit fallback values.</p></div>`;
      }
      if (skippedTrades > 0) {
        listHtml += `<div class="card" style="border-color:var(--red);background:rgba(231,76,60,0.12);"><p style="color:var(--red);padding:10px 12px;font-size:0.72rem;">${skippedTrades} historical trades were skipped because backend authority scoring was unavailable for those rows.</p></div>`;
      }
    for (let idx = 0; idx < filtered.length; idx++) {
      const a = filtered[idx];
      listHtml += `<div class="card" style="margin-bottom:10px;padding:12px;">`;
      listHtml += `<div style="font-size:0.68rem;color:var(--subtext);margin-bottom:8px;">Week ${a.trade.week} · ${a.date}</div>`;

      for (const side of a.sides) {
        const isWinner = side === a.winner && a.pctGap >= 3;
        const isLoser = side === a.loser && a.pctGap >= 3;
        const grade = isWinner ? a.winnerGrade : isLoser ? a.loserGrade : { grade: 'A', color: 'var(--green)', label: 'Fair' };
        const borderColor = isWinner ? 'var(--green)' : isLoser ? 'var(--red)' : 'var(--border)';

        listHtml += `<div style="border-left:3px solid ${borderColor};padding:6px 10px;margin:4px 0;display:flex;align-items:flex-start;gap:8px;">`;
        listHtml += `<div style="min-width:90px;">`;
        listHtml += `<div style="font-weight:700;font-size:0.72rem;">${side.team}</div>`;
        listHtml += `<div style="font-weight:800;font-size:0.82rem;color:${grade.color};">${grade.grade}</div>`;
        listHtml += `<div style="font-size:0.58rem;color:var(--subtext);">${grade.label}</div>`;
        listHtml += `</div>`;

        listHtml += `<div style="flex:1;">`;
        listHtml += `<div style="font-size:0.68rem;color:var(--subtext);margin-bottom:2px;">Received:</div>`;
        listHtml += `<div style="display:flex;flex-wrap:wrap;gap:4px;">`;
        for (const item of side.items) {
          const posC = item.isPick ? 'var(--amber)' :
            ({'QB':'#e74c3c','RB':'#27ae60','WR':'#3498db','TE':'#e67e22'}[item.pos] || '#9b59b6');
          const posLabel = item.isPick ? 'PICK' : item.pos;
          listHtml += `<span style="font-size:0.66rem;padding:2px 6px;border:1px solid var(--border);border-radius:4px;">`;
          listHtml += `<span style="color:${posC};font-weight:700;font-size:0.58rem;">${posLabel}</span> `;
          listHtml += `${item.name} <span style="font-family:var(--mono);color:var(--subtext);">${item.val.toLocaleString()}</span>`;
          listHtml += `</span>`;
        }
        listHtml += `</div>`;
        const pkgDelta = Number(side.packageDeltaPct || 0);
        const pkgSign = pkgDelta >= 0 ? '+' : '';
        listHtml += `<div style="font-family:var(--mono);font-size:0.66rem;margin-top:3px;">Linear: ${Math.round(side.linear).toLocaleString()} · Package-adj: ${Math.round(side.weighted).toLocaleString()} (${pkgSign}${pkgDelta.toFixed(1)}%)</div>`;
        listHtml += `</div>`;
        listHtml += `</div>`;
      }

      if (a.pctGap >= 3) {
        listHtml += `<div style="font-size:0.66rem;margin-top:6px;padding-top:6px;border-top:1px solid var(--border);color:var(--subtext);">`;
        listHtml += `${a.winner.team} won by ${a.pctGap.toFixed(1)}% (package-adjusted)`;
        listHtml += `</div>`;
      } else {
        listHtml += `<div style="font-size:0.66rem;margin-top:6px;padding-top:6px;border-top:1px solid var(--border);color:var(--green);font-weight:600;">Fair trade (within 3%)</div>`;
      }
      listHtml += `<div style="margin-top:8px;display:flex;justify-content:flex-end;">`;
      listHtml += `<button class="mobile-chip-btn primary" onclick="openHistoricalTradeInBuilder(${idx})">Open Builder</button>`;
      listHtml += `</div>`;
      listHtml += `</div>`;
    }

    listDiv.innerHTML = listHtml || '<div class="card"><p style="color:var(--subtext);padding:12px;">No trades match the filter.</p></div>';
      syncMobilePreview();
    } catch (err) {
      if (runId !== tradeHistoryBuildSeq) return;
      tradeHistoryRenderCache = [];
      listDiv.innerHTML = '<div class="card"><p style="color:var(--red);padding:12px;">Historical trade scoring failed. Backend authority is required for this view.</p></div>';
      if (statsCard) statsCard.style.display = 'none';
      syncMobilePreview();
      console.error('[Trade History] Failed to build backend-authoritative analysis.', err);
    }
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
      div.innerHTML = '<div style="color:var(--subtext);font-size:0.72rem;">No high-value unrostered players found.</div>';
      card.style.display = 'block';
      return;
    }

    const POS_C = {QB:'#e74c3c',RB:'#27ae60',WR:'#3498db',TE:'#e67e22',LB:'#9b59b6',DL:'#9b59b6',DE:'#9b59b6',DT:'#9b59b6',EDGE:'#9b59b6',CB:'#16a085',S:'#16a085',DB:'#16a085'};
    let html = '<div style="display:flex;flex-wrap:wrap;gap:6px;">';
    for (const p of top) {
      const posC = POS_C[(p.pos || '').toUpperCase()] || 'var(--subtext)';
      html += `<div style="display:flex;align-items:center;gap:6px;padding:5px 10px;border:1px solid var(--border);border-radius:6px;font-size:0.72rem;">`;
      html += `<span style="color:${posC};font-weight:700;font-family:var(--mono);font-size:0.62rem;">${p.pos}</span>`;
      html += `<span style="font-weight:600;">${p.name}</span>`;
      html += `<span style="font-family:var(--mono);color:var(--subtext);">${p.meta.toLocaleString()}</span>`;
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
      html += `<div style="width:${sellPct}%;height:10px;background:var(--red);border-radius:2px;min-width:${t.sellEdge > 0 ? 2 : 0}px;" title="SELL edge: ${t.sellEdge}%"></div>`;
      html += `<span style="font-size:0.6rem;color:var(--red);font-family:var(--mono);min-width:35px;">${t.sellCount}S</span>`;
      html += `<div style="width:${buyPct}%;height:10px;background:var(--green);border-radius:2px;min-width:${t.buyEdge > 0 ? 2 : 0}px;" title="BUY edge: ${t.buyEdge}%"></div>`;
      html += `<span style="font-size:0.6rem;color:var(--green);font-family:var(--mono);">${t.buyCount}B</span>`;
      html += `</div></div>`;

      // Show top exploitable players for this team
      if (t.topSells.length || t.topBuys.length) {
        html += `<div style="font-size:0.62rem;color:var(--subtext);padding-left:140px;">`;
        if (t.topSells.length) {
          html += `<span style="color:var(--red);">Overvalued: ${t.topSells.map(p => `${p.name} +${p.pct.toFixed(0)}%`).join(', ')}</span>`;
        }
        if (t.topSells.length && t.topBuys.length) html += ' · ';
        if (t.topBuys.length) {
          html += `<span style="color:var(--green);">Undervalued: ${t.topBuys.map(p => `${p.name} ${p.pct.toFixed(0)}%`).join(', ')}</span>`;
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

  const TRADE_SUGGESTIONS_V2_SESSION_KEY = 'dynasty_trade_suggestions_v2';
  const TRADE_SUGGESTIONS_V2_MIN_VALUE = 140;
  const SUGGESTION_GROUPS = ['QB','RB','WR','TE','DL','LB','DB'];
  const SUGGESTION_MODE_REALISM = new Set(['aggressive', 'balanced', 'highly_realistic']);
  const SUGGESTION_MODE_STRATEGY = new Set(['contender', 'rebuilder', 'neutral']);
  const TRADE_SUGGESTIONS_MAX_RESULTS = 3;
  const SUGGESTION_DIAG_MAX = 220;
  const BB_VOLATILITY_KEYS = ['high', 'spike', 'boom', 'volatile'];
  const __tradeSuggestionsV2 = {
    state: null,
    exclusionView: null,
    diagnostics: null,
  };

  function _cloneTradeSuggestionState(state) {
    if (!state || typeof state !== 'object') return null;
    return JSON.parse(JSON.stringify(state));
  }

  function _normalizeStrategyMode(raw) {
    const val = String(raw || 'neutral').trim().toLowerCase();
    return SUGGESTION_MODE_STRATEGY.has(val) ? val : 'neutral';
  }

  function _normalizeRealismMode(raw) {
    const val = String(raw || 'balanced').trim().toLowerCase().replace(/\s+/g, '_');
    return SUGGESTION_MODE_REALISM.has(val) ? val : 'balanced';
  }

  function _normalizeExclusionSet(arr) {
    if (!Array.isArray(arr)) return [];
    const out = [];
    const seen = new Set();
    arr.forEach(item => {
      const nk = normalizeForLookup(String(item || ''));
      if (!nk || seen.has(nk)) return;
      seen.add(nk);
      out.push(nk);
    });
    return out;
  }

  function getDefaultTradeSuggestionsV2State() {
    return {
      opponentTeam: '',
      realismMode: 'balanced',
      strategyMode: 'neutral',
      exclusions: {
        ourPlayers: [],
        ourPicks: [],
        theirPlayers: [],
        theirPicks: [],
      },
      lastOutput: null,
    };
  }

  function loadTradeSuggestionsV2State() {
    if (__tradeSuggestionsV2.state) return _cloneTradeSuggestionState(__tradeSuggestionsV2.state);
    let parsed = null;
    try {
      const raw = sessionStorage.getItem(TRADE_SUGGESTIONS_V2_SESSION_KEY);
      if (raw) parsed = JSON.parse(raw);
    } catch (_) {
      parsed = null;
    }
    const base = getDefaultTradeSuggestionsV2State();
    if (!parsed || typeof parsed !== 'object') {
      __tradeSuggestionsV2.state = base;
      return _cloneTradeSuggestionState(base);
    }
    const next = {
      ...base,
      opponentTeam: String(parsed.opponentTeam || ''),
      realismMode: _normalizeRealismMode(parsed.realismMode),
      strategyMode: _normalizeStrategyMode(parsed.strategyMode),
      exclusions: {
        ourPlayers: _normalizeExclusionSet(parsed.exclusions?.ourPlayers),
        ourPicks: _normalizeExclusionSet(parsed.exclusions?.ourPicks),
        theirPlayers: _normalizeExclusionSet(parsed.exclusions?.theirPlayers),
        theirPicks: _normalizeExclusionSet(parsed.exclusions?.theirPicks),
      },
      lastOutput: parsed.lastOutput && typeof parsed.lastOutput === 'object' ? parsed.lastOutput : null,
    };
    __tradeSuggestionsV2.state = next;
    return _cloneTradeSuggestionState(next);
  }

  function saveTradeSuggestionsV2State(nextState) {
    const base = getDefaultTradeSuggestionsV2State();
    const merged = {
      ...base,
      ...(nextState || {}),
      realismMode: _normalizeRealismMode(nextState?.realismMode),
      strategyMode: _normalizeStrategyMode(nextState?.strategyMode),
      exclusions: {
        ourPlayers: _normalizeExclusionSet(nextState?.exclusions?.ourPlayers),
        ourPicks: _normalizeExclusionSet(nextState?.exclusions?.ourPicks),
        theirPlayers: _normalizeExclusionSet(nextState?.exclusions?.theirPlayers),
        theirPicks: _normalizeExclusionSet(nextState?.exclusions?.theirPicks),
      },
      lastOutput: nextState?.lastOutput || null,
    };
    __tradeSuggestionsV2.state = merged;
    try {
      sessionStorage.setItem(TRADE_SUGGESTIONS_V2_SESSION_KEY, JSON.stringify(merged));
    } catch (_) {}
    return _cloneTradeSuggestionState(merged);
  }

  function _isBestBallContext() {
    if (typeof getBestBallContextDetails === 'function') {
      return !!getBestBallContextDetails().active;
    }
    const v = loadedData?.sleeper?.leagueSettings?.best_ball;
    if (v === true || v === 1 || String(v).toLowerCase() === 'true') return true;
    return true;
  }

  function _getAssetConfidenceScore(raw) {
    const a = Number(raw?.marketReliabilityScore);
    if (Number.isFinite(a) && a > 0) return clampValue(a, 0.20, 1.00);
    const b = Number(raw?.marketConfidence);
    if (Number.isFinite(b) && b > 0) return clampValue(b, 0.20, 1.00);
    const fit = Number(raw?.formatFitConfidence);
    if (Number.isFinite(fit) && fit > 0) return clampValue(fit, 0.20, 1.00);
    return 0.45;
  }

  function _isLowConfidenceAsset(asset) {
    return Number(asset?.confidence || 0) < 0.58 || Number(asset?.sourceCoverage || 0) <= 1;
  }

  function _parseAssetYearsExp(name) {
    const p = loadedData?.players?.[name];
    const years = Number(p?._yearsExp);
    return Number.isFinite(years) && years >= 0 ? years : null;
  }

  function _isVolatileBestBallAsset(name) {
    const p = loadedData?.players?.[name];
    const vf = String(p?._formatFitVolatilityFlag || '').toLowerCase();
    if (vf && vf !== 'none' && vf !== 'false' && vf !== '0') return true;
    const tags = p?._formatFitScoringTags;
    if (Array.isArray(tags) && tags.some(tag => BB_VOLATILITY_KEYS.some(k => String(tag).toLowerCase().includes(k)))) return true;
    return false;
  }

  function _isRookieAsset(name) {
    const p = loadedData?.players?.[name];
    return !!isRookiePlayerName(name, p);
  }

  function _isAgingAsset(asset) {
    if (!asset || asset.type !== 'player') return false;
    const y = Number(asset.yearsExp);
    if (!Number.isFinite(y)) return false;
    if (asset.group === 'QB') return y >= 9;
    if (asset.isIdp) return y >= 7;
    return y >= 6;
  }

  function _assetListFromTeam(team, sideLabel, exclusions) {
    const out = [];
    if (!team || !Array.isArray(team.players)) return out;
    const posMap = loadedData?.sleeper?.positions || {};
    const seen = new Set();
    const pushAsset = (label, forcedPick = false) => {
      const cleanLabel = String(label || '').trim();
      if (!cleanLabel) return;
      const key = normalizeForLookup(cleanLabel);
      if (!key || seen.has(key)) return;
      seen.add(key);
      const isPick = forcedPick || !!parsePickToken(cleanLabel);
      const exclusionBucket = isPick
        ? (sideLabel === 'ours' ? exclusions.ourPicks : exclusions.theirPicks)
        : (sideLabel === 'ours' ? exclusions.ourPlayers : exclusions.theirPlayers);
      if (exclusionBucket.has(key)) return;
      const tiv = getTradeItemValue(cleanLabel);
      const value = Number(tiv?.metaValue || 0);
      if (!Number.isFinite(value) || value <= TRADE_SUGGESTIONS_V2_MIN_VALUE) return;
      const resolved = String(tiv?.resolvedName || cleanLabel).trim() || cleanLabel;
      const pData = loadedData?.players?.[resolved] || loadedData?.players?.[cleanLabel] || null;
      const raw = Math.max(1, Math.round(Number(tiv?.rawMarketValue ?? value) || value));
      const scoring = Math.max(1, Math.round(Number(tiv?.scoringAdjustedValue ?? raw) || raw));
      const scarcity = Math.max(1, Math.round(Number(tiv?.scarcityAdjustedValue ?? scoring) || scoring));
      const full = Math.max(1, Math.round(Number(tiv?.finalAdjustedValue ?? value) || value));
      const pos = isPick ? 'PICK' : String((posMap[resolved] || posMap[cleanLabel] || getPlayerPosition(resolved) || getPlayerPosition(cleanLabel) || '')).toUpperCase();
      const group = isPick ? 'PICKS' : posGroup(pos);
      const confidence = _getAssetConfidenceScore({
        marketReliabilityScore: Number(tiv?.marketReliabilityScore),
        marketConfidence: Number(tiv?.marketConfidence),
        formatFitConfidence: Number(tiv?.formatFitConfidence),
      });
      const sourceCoverage = Math.max(0, Number(tiv?.siteCount || pData?._sites || 0));
      out.push({
        id: `${isPick ? 'pick' : 'player'}:${key}`,
        key,
        label: cleanLabel,
        resolvedName: resolved,
        type: isPick ? 'pick' : 'player',
        teamName: team.name,
        side: sideLabel,
        value,
        rawValue: raw,
        scoringAdjustedValue: scoring,
        scarcityAdjustedValue: scarcity,
        fullValue: full,
        position: pos || (isPick ? 'PICK' : ''),
        group,
        isIdp: !isPick && ['DL','LB','DB'].includes(group),
        isOffense: !isPick && ['QB','RB','WR','TE'].includes(group),
        confidence,
        sourceCoverage,
        yearsExp: _parseAssetYearsExp(resolved) ?? _parseAssetYearsExp(cleanLabel),
        rookie: !isPick && _isRookieAsset(resolved),
        volatilityFlag: !isPick && _isVolatileBestBallAsset(resolved),
        formatFitTags: Array.isArray(pData?._formatFitScoringTags) ? pData._formatFitScoringTags.slice(0, 6) : [],
      });
    };

    team.players.forEach(p => {
      if (!p) return;
      if (parsePickToken(p)) {
        pushAsset(p, true);
      } else {
        const pos = String(posMap[p] || getPlayerPosition(p) || '').toUpperCase();
        if (isKickerPosition(pos)) return;
        pushAsset(p, false);
      }
    });
    if (Array.isArray(team.picks)) {
      team.picks.forEach(p => pushAsset(p, true));
    }
    return out.sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
  }

  function _buildNeedsFromAssets(assets, leagueAvgByGroup) {
    const totals = {};
    SUGGESTION_GROUPS.concat(['PICKS']).forEach(g => { totals[g] = 0; });
    (assets || []).forEach(a => {
      const g = a.group || 'Other';
      if (totals[g] == null) totals[g] = 0;
      totals[g] += Number(a.value || 0);
    });
    const ratio = {};
    Object.keys(totals).forEach(g => {
      const avg = Number(leagueAvgByGroup?.[g] || 0);
      ratio[g] = avg > 0 ? (Number(totals[g] || 0) / avg) : 1;
    });
    const needs = SUGGESTION_GROUPS.slice().sort((a, b) => ratio[a] - ratio[b]);
    const surplus = SUGGESTION_GROUPS.slice().sort((a, b) => ratio[b] - ratio[a]);
    return {
      totals,
      ratio,
      needs,
      surplus,
      needTop2: needs.slice(0, 2),
      surplusTop2: surplus.slice(0, 2),
      idpTotal: ['DL','LB','DB'].reduce((s, g) => s + Number(totals[g] || 0), 0),
      offenseTotal: ['QB','RB','WR','TE'].reduce((s, g) => s + Number(totals[g] || 0), 0),
    };
  }

  function _inferTeamPosture(team) {
    if (!team) return 'neutral';
    const tiers = typeof getTeamTier === 'function' ? getTeamTier(sleeperTeams || []) : [];
    const match = tiers.find(t => String(t?.name || '').toLowerCase() === String(team.name || '').toLowerCase());
    if (!match) return 'neutral';
    if (match.tier === 'contender') return 'contender';
    if (match.tier === 'rebuilder') return 'rebuilder';
    return 'neutral';
  }

  function _getRealismConfig(mode) {
    const resolved = _normalizeRealismMode(mode);
    if (resolved === 'aggressive') {
      return {
        mode: resolved,
        minEdgePct: 0.025,
        maxEdgePct: 0.19,
        minPlausibility: 46,
        maxPiecesPerSide: 5,
        maxIncomingPieces: 3,
        candidateCap: 18,
        weights: { ourEdge: 0.34, theirFit: 0.15, ourFit: 0.18, market: 0.14, package: 0.11, confidence: 0.08 },
      };
    }
    if (resolved === 'highly_realistic') {
      return {
        mode: resolved,
        minEdgePct: 0.008,
        maxEdgePct: 0.075,
        minPlausibility: 68,
        maxPiecesPerSide: 4,
        maxIncomingPieces: 3,
        candidateCap: 15,
        weights: { ourEdge: 0.18, theirFit: 0.22, ourFit: 0.16, market: 0.24, package: 0.14, confidence: 0.06 },
      };
    }
    return {
      mode: 'balanced',
      minEdgePct: 0.015,
      maxEdgePct: 0.12,
      minPlausibility: 57,
      maxPiecesPerSide: 4,
      maxIncomingPieces: 3,
      candidateCap: 16,
      weights: { ourEdge: 0.26, theirFit: 0.18, ourFit: 0.16, market: 0.20, package: 0.12, confidence: 0.08 },
    };
  }

  function _strategyScoreMultiplier(strategyMode, ourNeeds, asset, incoming) {
    const strategy = _normalizeStrategyMode(strategyMode);
    if (!asset) return 1;
    let mult = 1;
    if (strategy === 'contender') {
      if (incoming) {
        if (asset.type === 'pick') mult *= 0.78;
        if (asset.type === 'player' && _isAgingAsset(asset)) mult *= 1.08;
        if (asset.type === 'player' && ourNeeds.needTop2.includes(asset.group)) mult *= 1.12;
      } else {
        if (asset.type === 'pick') mult *= 1.12;
        if (asset.type === 'player' && ourNeeds.needTop2.includes(asset.group)) mult *= 0.68;
      }
    } else if (strategy === 'rebuilder') {
      if (incoming) {
        if (asset.type === 'pick') mult *= 1.25;
        if (asset.type === 'player' && (asset.rookie || Number(asset.yearsExp || 99) <= 2)) mult *= 1.18;
        if (_isAgingAsset(asset)) mult *= 0.70;
      } else {
        if (asset.type === 'pick') mult *= 0.72;
        if (asset.type === 'player' && _isAgingAsset(asset)) mult *= 1.12;
      }
    }
    return mult;
  }

  function _scoreCandidateAsset(asset, ctx) {
    if (!asset) return -1e9;
    const { isIncoming, ourNeeds, theirNeeds, strategyMode, bestBallActive } = ctx;
    let score = Number(asset.value || 0);
    if (isIncoming) {
      if (ourNeeds.needTop2.includes(asset.group)) score *= 1.26;
      if (ourNeeds.surplusTop2.includes(asset.group)) score *= 0.92;
      if (bestBallActive && asset.volatilityFlag) score *= 1.08;
    } else {
      if (ourNeeds.surplusTop2.includes(asset.group)) score *= 1.24;
      if (ourNeeds.needTop2.includes(asset.group)) score *= 0.70;
      if (_isLowConfidenceAsset(asset)) score *= 1.06;
      if (asset.value > 8200) score *= 0.70;
    }
    if (!isIncoming && theirNeeds.needTop2.includes(asset.group)) score *= 1.12;
    score *= _strategyScoreMultiplier(strategyMode, ourNeeds, asset, isIncoming);
    return score;
  }

  function _pickCandidatesByMode(assets, cap, ctx) {
    const ranked = (assets || [])
      .map(a => ({ ...a, __candidateScore: _scoreCandidateAsset(a, ctx) }))
      .filter(a => Number.isFinite(a.__candidateScore) && a.__candidateScore > 0)
      .sort((a, b) => b.__candidateScore - a.__candidateScore || b.value - a.value)
      .slice(0, Math.max(6, cap || 12))
      .map(a => {
        const clone = { ...a };
        delete clone.__candidateScore;
        return clone;
      });
    return ranked;
  }

  function _buildAssetCombos(assets, maxCount, opts = {}) {
    const source = Array.isArray(assets) ? assets : [];
    const maxCombos = Math.max(20, Number(opts.maxCombos || 280));
    const minTotal = Math.max(0, Number(opts.minTotal || 0));
    const maxTotal = Number.isFinite(Number(opts.maxTotal)) ? Number(opts.maxTotal) : Number.POSITIVE_INFINITY;
    const out = [];
    const stack = [];
    const n = source.length;

    function dfs(start, total) {
      if (stack.length > 0 && total >= minTotal && total <= maxTotal) {
        out.push({
          assets: stack.slice(),
          total,
        });
        if (out.length >= maxCombos) return;
      }
      if (stack.length >= maxCount) return;
      for (let i = start; i < n; i += 1) {
        const a = source[i];
        const nextTotal = total + Number(a.value || 0);
        if (nextTotal > maxTotal * 1.3) continue;
        stack.push(a);
        dfs(i + 1, nextTotal);
        stack.pop();
        if (out.length >= maxCombos) return;
      }
    }
    dfs(0, 0);
    return out;
  }

  function _weightedMeanConfidence(assets) {
    const list = Array.isArray(assets) ? assets : [];
    let numer = 0;
    let denom = 0;
    list.forEach(a => {
      const w = Math.max(1, Number(a.value || 0));
      const c = clampValue(Number(a.confidence || 0.45), 0.2, 1);
      numer += c * w;
      denom += w;
    });
    return denom > 0 ? (numer / denom) : 0.45;
  }

  function _countFringeAssets(assets) {
    return (assets || []).filter(a => Number(a?.value || 0) < 700).length;
  }

  function _scoreMarketPlausibility(ourSend, theirSend, edgePct, realismCfg) {
    const ourTotal = ourSend.reduce((s, a) => s + Number(a.value || 0), 0);
    const theirTotal = theirSend.reduce((s, a) => s + Number(a.value || 0), 0);
    const maxSide = Math.max(ourTotal, theirTotal, 1);
    const gapPct = Math.abs(theirTotal - ourTotal) / maxSide;
    let score = 100 - (gapPct * 540);
    score -= Math.max(0, (ourSend.length - 3) * 10);
    score -= Math.max(0, (theirSend.length - 2) * 10);
    if (edgePct > realismCfg.maxEdgePct) score -= (edgePct - realismCfg.maxEdgePct) * 420;
    if (edgePct < realismCfg.minEdgePct) score -= (realismCfg.minEdgePct - edgePct) * 300;
    const lowConfCenterpiece = [...ourSend, ...theirSend]
      .sort((a, b) => b.value - a.value)
      .slice(0, 2)
      .some(a => _isLowConfidenceAsset(a));
    if (lowConfCenterpiece) score -= 14;
    return clampValue(score, 0, 100);
  }

  function _scorePackageRealism(ourSend, theirSend) {
    const pieces = ourSend.length + theirSend.length;
    const fringe = _countFringeAssets(ourSend) + _countFringeAssets(theirSend);
    let score = 88;
    score -= Math.max(0, pieces - 4) * 9;
    score -= Math.max(0, fringe - 1) * 10;
    if (ourSend.length >= 3 && theirSend.length >= 3) score -= 10;
    if ((ourSend.length >= 2 && theirSend.length === 1) || (theirSend.length >= 2 && ourSend.length === 1)) score += 6;
    return clampValue(score, 0, 100);
  }

  function _scoreFit(assetsIn, assetsOut, needs, strategyMode, bestBallActive) {
    let score = 50;
    assetsIn.forEach(a => {
      if (needs.needTop2.includes(a.group)) score += 8;
      if (needs.surplusTop2.includes(a.group)) score -= 4;
      if (a.type === 'pick' && strategyMode === 'rebuilder') score += 7;
      if (a.type === 'pick' && strategyMode === 'contender') score -= 5;
      if (_isAgingAsset(a) && strategyMode === 'rebuilder') score -= 7;
      if (_isAgingAsset(a) && strategyMode === 'contender') score += 3;
      if (bestBallActive && a.volatilityFlag) score += 4;
    });
    assetsOut.forEach(a => {
      if (needs.needTop2.includes(a.group)) score -= 6;
      if (needs.surplusTop2.includes(a.group)) score += 3;
      if (a.type === 'pick' && strategyMode === 'contender') score += 4;
      if (a.type === 'pick' && strategyMode === 'rebuilder') score -= 5;
    });
    return clampValue(score, 0, 100);
  }

  function _scoreConfidence(ourSend, theirSend) {
    const allAssets = (ourSend || []).concat(theirSend || []);
    const mean = _weightedMeanConfidence(allAssets);
    let score = clampValue(mean * 100, 0, 100);
    const thinCenterpiece = allAssets
      .sort((a, b) => b.value - a.value)
      .slice(0, 2)
      .some(a => Number(a.sourceCoverage || 0) <= 1);
    if (thinCenterpiece) score -= 18;
    return clampValue(score, 0, 100);
  }

  function _scoreSuggestion(trade, ctx) {
    const ourTotal = Number(trade.ourTotal || 0);
    const theirTotal = Number(trade.theirTotal || 0);
    const maxSide = Math.max(ourTotal, theirTotal, 1);
    const edgePct = (theirTotal - ourTotal) / maxSide;
    const ourEdgeScore = clampValue(50 + (edgePct * 320), 0, 100);
    const theirFitScore = _scoreFit(trade.ourSend, trade.theirSend, ctx.theirNeeds, ctx.theirStrategy, ctx.bestBallActive);
    const ourFitScore = _scoreFit(trade.theirSend, trade.ourSend, ctx.ourNeeds, ctx.ourStrategy, ctx.bestBallActive);
    const marketPlausibilityScore = _scoreMarketPlausibility(trade.ourSend, trade.theirSend, edgePct, ctx.realismCfg);
    const packageRealismScore = _scorePackageRealism(trade.ourSend, trade.theirSend);
    const confidenceScore = _scoreConfidence(trade.ourSend, trade.theirSend);
    const w = ctx.realismCfg.weights;
    const weighted =
      (ourEdgeScore * w.ourEdge) +
      (theirFitScore * w.theirFit) +
      (ourFitScore * w.ourFit) +
      (marketPlausibilityScore * w.market) +
      (packageRealismScore * w.package) +
      (confidenceScore * w.confidence);
    return {
      edgePct,
      scores: {
        ourEdgeScore: Math.round(ourEdgeScore * 10) / 10,
        theirFitScore: Math.round(theirFitScore * 10) / 10,
        ourFitScore: Math.round(ourFitScore * 10) / 10,
        marketPlausibilityScore: Math.round(marketPlausibilityScore * 10) / 10,
        packageRealismScore: Math.round(packageRealismScore * 10) / 10,
        confidenceScore: Math.round(confidenceScore * 10) / 10,
      },
      suggestionScore: Math.round(weighted * 10) / 10,
    };
  }

  function _suggestionTradeKey(ourSend, theirSend) {
    const left = (ourSend || []).map(a => a.id).sort().join('|');
    const right = (theirSend || []).map(a => a.id).sort().join('|');
    return `${left}=>${right}`;
  }

  function _deriveArchetypeTags(suggestion, ctx) {
    const tags = [];
    const reasons = [];
    const ourSend = suggestion.ourSend || [];
    const theirSend = suggestion.theirSend || [];
    const ourPicks = ourSend.filter(a => a.type === 'pick').length;
    const theirPicks = theirSend.filter(a => a.type === 'pick').length;
    const sentAging = ourSend.filter(a => _isAgingAsset(a));
    const recvAging = theirSend.filter(a => _isAgingAsset(a));
    const recvYoung = theirSend.filter(a => a.type === 'player' && (a.rookie || Number(a.yearsExp || 99) <= 2));
    const recvVolatile = theirSend.filter(a => a.volatilityFlag);
    if (ourSend.length >= 2 && theirSend.length === 1 && suggestion.theirTotal >= suggestion.ourTotal * 0.92) {
      tags.push('consolidation');
      reasons.push('Packaging depth into one stronger asset.');
    }
    if ((ourPicks > 0 && recvAging.length > 0) || (theirPicks > 0 && sentAging.length > 0)) {
      tags.push('veteran-for-picks');
      reasons.push('Trade shape moves veteran production against draft capital.');
    }
    if (sentAging.length > 0 && (theirPicks > 0 || recvYoung.length > 0)) {
      tags.push('sell aging');
      reasons.push('Moves aging production into insulated youth/picks.');
    }
    const lowConfRecv = theirSend.filter(a => _isLowConfidenceAsset(a) && a.type === 'player' && a.value >= 1800);
    if (lowConfRecv.length > 0 && suggestion.scores.marketPlausibilityScore >= ctx.realismCfg.minPlausibility - 8) {
      tags.push('buy low');
      reasons.push('Targets discounted assets with rebound paths.');
    }
    const ourIdpBefore = Number(ctx.ourNeeds.idpTotal || 0);
    const ourIdpAfter = ourIdpBefore
      - ourSend.filter(a => a.isIdp).reduce((s, a) => s + Number(a.value || 0), 0)
      + theirSend.filter(a => a.isIdp).reduce((s, a) => s + Number(a.value || 0), 0);
    const idpLeagueAvg = Number(ctx.leagueAvgByGroup?.DL || 0) + Number(ctx.leagueAvgByGroup?.LB || 0) + Number(ctx.leagueAvgByGroup?.DB || 0);
    const beforeGap = Math.abs(ourIdpBefore - idpLeagueAvg);
    const afterGap = Math.abs(ourIdpAfter - idpLeagueAvg);
    if (Math.abs(beforeGap - afterGap) > 500 && afterGap < beforeGap) {
      tags.push('IDP correction');
      reasons.push('Improves IDP balance vs league replacement pressure.');
    }
    if (ctx.bestBallActive && recvVolatile.length > 0) {
      tags.push('best-ball upside move');
      reasons.push('Adds spike-week volatility that best-ball can auto-capture.');
    }
    return { tags: Array.from(new Set(tags)).slice(0, 3), reasons };
  }

  function _buildSendabilityNarratives(suggestion, ctx) {
    const tags = suggestion.archetypeTags || [];
    const need = ctx.ourNeeds.needTop2[0] || 'starter';
    let helpsUs = '';
    let helpsThem = '';
    if (tags.includes('consolidation')) {
      helpsUs = `Helps us consolidate depth into a stronger ${need} starter without overpaying in total value.`;
    } else if (ctx.ourStrategy === 'rebuilder') {
      helpsUs = 'Helps us shift value into younger insulation and pick runway while keeping upside intact.';
    } else if (ctx.ourStrategy === 'contender') {
      helpsUs = `Helps us add immediate lineup utility at ${need} for a playoff build.`;
    } else {
      helpsUs = `Helps us improve roster fit at ${need} while preserving a positive calculator edge.`;
    }

    if (tags.includes('sell aging')) {
      helpsThem = 'Might appeal because they can convert aging production into younger or longer-horizon value.';
    } else if (ctx.theirStrategy === 'contender') {
      helpsThem = `Might work if they are pushing to contend and want usable weekly points at ${ctx.theirNeeds.needTop2[0] || 'a thin spot'}.`;
    } else if (ctx.theirStrategy === 'rebuilder') {
      helpsThem = 'Might appeal if they are retooling since they receive insulation via picks/younger profiles.';
    } else {
      helpsThem = `Could be sendable because it addresses their ${ctx.theirNeeds.needTop2[0] || 'lineup'} need with plausible market balance.`;
    }
    return { helpsUs, helpsThem };
  }

  function _findLikelyCounter(suggestion, ctx) {
    const edgePct = Number(suggestion.edgePct || 0);
    const plaus = Number(suggestion.scores?.marketPlausibilityScore || 0);
    const theirFit = Number(suggestion.scores?.theirFitScore || 0);
    if (edgePct <= ctx.realismCfg.minEdgePct + 0.01 && plaus >= ctx.realismCfg.minPlausibility && theirFit >= 57) {
      return null;
    }

    const usedOur = new Set((suggestion.ourSend || []).map(a => a.id));
    const availableUpgrades = ctx.ourCandidatePool.filter(a => !usedOur.has(a.id));
    const pickInDeal = (suggestion.ourSend || []).find(a => a.type === 'pick');
    if (pickInDeal) {
      const betterPick = availableUpgrades
        .filter(a => a.type === 'pick' && a.value > pickInDeal.value && a.value <= pickInDeal.value + 900)
        .sort((a, b) => a.value - b.value)[0];
      if (betterPick) {
        return {
          type: 'pick_upgrade',
          note: `They may ask for your ${betterPick.label} instead of ${pickInDeal.label}.`,
          adjustment: {
            replaceOut: pickInDeal.label,
            withOut: betterPick.label,
          },
        };
      }
    }

    const weakestOut = (suggestion.ourSend || []).slice().sort((a, b) => a.value - b.value)[0];
    if (weakestOut) {
      const swap = availableUpgrades
        .filter(a =>
          a.type === weakestOut.type &&
          (a.group === weakestOut.group || ctx.theirNeeds.needTop2.includes(a.group)) &&
          a.value > weakestOut.value &&
          a.value <= weakestOut.value + 1000
        )
        .sort((a, b) => a.value - b.value)[0];
      if (swap) {
        return {
          type: 'secondary_swap',
          note: `They may prefer ${swap.label} instead of ${weakestOut.label} for a cleaner positional fit.`,
          adjustment: {
            replaceOut: weakestOut.label,
            withOut: swap.label,
          },
        };
      }
    }

    const fringeOut = (suggestion.ourSend || []).find(a => Number(a.value || 0) < 500);
    if (fringeOut && suggestion.ourSend.length >= 3) {
      return {
        type: 'cleaner_shape',
        note: `They may ask to remove ${fringeOut.label} and keep this as a cleaner core package.`,
        adjustment: {
          removeOut: fringeOut.label,
        },
      };
    }
    return null;
  }

  function _generateTradeSuggestionsCore(params) {
    const myTeam = params?.myTeam;
    const oppTeam = params?.opponentTeam;
    if (!myTeam || !oppTeam) return { suggestions: [], diagnostics: { reason: 'missing_team' } };
    const realismCfg = _getRealismConfig(params.realismMode);
    const bestBallActive = _isBestBallContext();
    const exclusions = params.exclusions || {
      ourPlayers: new Set(), ourPicks: new Set(), theirPlayers: new Set(), theirPicks: new Set(),
    };

    const ourAssets = _assetListFromTeam(myTeam, 'ours', exclusions);
    const theirAssets = _assetListFromTeam(oppTeam, 'theirs', exclusions);
    const leagueAvgByGroup = params.leagueAvgByGroup || {};
    const ourNeeds = _buildNeedsFromAssets(ourAssets.filter(a => a.type === 'player'), leagueAvgByGroup);
    const theirNeeds = _buildNeedsFromAssets(theirAssets.filter(a => a.type === 'player'), leagueAvgByGroup);
    const ourStrategy = _normalizeStrategyMode(params.strategyMode === 'neutral' ? _inferTeamPosture(myTeam) : params.strategyMode);
    const theirStrategy = _inferTeamPosture(oppTeam);

    const candidateCtxOut = { isIncoming: false, ourNeeds, theirNeeds, strategyMode: ourStrategy, bestBallActive };
    const candidateCtxIn = { isIncoming: true, ourNeeds, theirNeeds, strategyMode: ourStrategy, bestBallActive };
    const ourCandidatePool = _pickCandidatesByMode(ourAssets, realismCfg.candidateCap, candidateCtxOut);
    const theirCandidatePool = _pickCandidatesByMode(theirAssets, realismCfg.candidateCap, candidateCtxIn);
    const maxSend = realismCfg.maxPiecesPerSide;
    const maxReceive = Math.min(realismCfg.maxIncomingPieces, realismCfg.maxPiecesPerSide);
    const ourCombos = _buildAssetCombos(ourCandidatePool, maxSend, { maxCombos: 420 });
    const theirCombos = _buildAssetCombos(theirCandidatePool, maxReceive, { maxCombos: 260 });
    const rejections = { edgeLow: 0, edgeHigh: 0, plausibility: 0, confidence: 0, package: 0 };
    const kept = [];
    const seen = new Set();
    const hardCap = SUGGESTION_DIAG_MAX;

    const scoreCtx = { ourNeeds, theirNeeds, ourStrategy, theirStrategy, realismCfg, bestBallActive };
    for (const recv of theirCombos) {
      const recvTotal = Number(recv.total || 0);
      if (recvTotal <= 0) continue;
      for (const send of ourCombos) {
        const sendTotal = Number(send.total || 0);
        if (sendTotal <= 0) continue;
        const trade = {
          ourSend: send.assets,
          theirSend: recv.assets,
          ourTotal: sendTotal,
          theirTotal: recvTotal,
        };
        if (trade.ourSend.length > 5 || trade.theirSend.length > 5) continue;
        const scored = _scoreSuggestion(trade, scoreCtx);
        const edgePct = Number(scored.edgePct || 0);
        if (edgePct < realismCfg.minEdgePct) { rejections.edgeLow += 1; continue; }
        if (edgePct > realismCfg.maxEdgePct) { rejections.edgeHigh += 1; continue; }
        if (scored.scores.marketPlausibilityScore < realismCfg.minPlausibility) { rejections.plausibility += 1; continue; }
        if (scored.scores.packageRealismScore < 42) { rejections.package += 1; continue; }
        if (scored.scores.confidenceScore < 36) { rejections.confidence += 1; continue; }
        const key = _suggestionTradeKey(trade.ourSend, trade.theirSend);
        if (seen.has(key)) continue;
        seen.add(key);
        const tagInfo = _deriveArchetypeTags({ ...trade, ...scored }, {
          ...scoreCtx,
          leagueAvgByGroup,
        });
        const suggestion = {
          ...trade,
          ...scored,
          archetypeTags: tagInfo.tags,
          archetypeReasons: tagInfo.reasons,
        };
        const narratives = _buildSendabilityNarratives(suggestion, scoreCtx);
        suggestion.helpsUs = narratives.helpsUs;
        suggestion.helpsThem = narratives.helpsThem;
        kept.push(suggestion);
        if (kept.length >= hardCap) break;
      }
      if (kept.length >= hardCap) break;
    }

    kept.sort((a, b) => b.suggestionScore - a.suggestionScore || b.edgePct - a.edgePct);
    const top = kept.slice(0, TRADE_SUGGESTIONS_MAX_RESULTS).map((s, idx) => {
      const counter = _findLikelyCounter(s, {
        realismCfg,
        ourNeeds,
        theirNeeds,
        ourCandidatePool,
      });
      return {
        ...s,
        rank: idx + 1,
        likelyCounter: counter,
      };
    });

    const diagnostics = {
      realismMode: realismCfg.mode,
      strategyMode: params.strategyMode,
      effectiveOurStrategy: ourStrategy,
      inferredTheirStrategy: theirStrategy,
      bestBallActive,
      candidateCounts: {
        ourAssets: ourAssets.length,
        theirAssets: theirAssets.length,
        ourCandidatePool: ourCandidatePool.length,
        theirCandidatePool: theirCandidatePool.length,
        ourCombos: ourCombos.length,
        theirCombos: theirCombos.length,
      },
      rejectionCounts: rejections,
      selectedCount: top.length,
      selectedScores: top.map(s => ({
        score: s.suggestionScore,
        edgePct: Number((s.edgePct * 100).toFixed(2)),
        market: s.scores.marketPlausibilityScore,
        package: s.scores.packageRealismScore,
        confidence: s.scores.confidenceScore,
      })),
      archetypeSummary: top.map(s => ({
        rank: s.rank,
        tags: s.archetypeTags,
      })),
    };
    return {
      suggestions: top,
      diagnostics,
      context: {
        ourNeeds,
        theirNeeds,
        ourCandidatePool,
        theirCandidatePool,
        realismCfg,
        ourStrategy,
        theirStrategy,
        bestBallActive,
      },
    };
  }

  function _valueTone(v) {
    if (!Number.isFinite(v)) return 'var(--subtext)';
    if (v > 0) return 'var(--green)';
    if (v < 0) return 'var(--red)';
    return 'var(--subtext)';
  }

  function _renderSuggestionAssetsHtml(assets) {
    return (assets || []).map(a => {
      const pos = a.type === 'pick' ? 'PICK' : (a.position || a.group || '?');
      return `<div class="tsv2-asset"><span style="font-family:var(--mono);font-size:0.62rem;color:var(--subtext);">${pos}</span><span>${a.label}</span><code>${Math.round(a.value || 0).toLocaleString()}</code></div>`;
    }).join('');
  }

  function _renderTradeSuggestionsV2Results(out, uiCtx) {
    const resultDiv = document.getElementById('tradeSuggestionsV2Results');
    if (!resultDiv) return;
    const suggestions = Array.isArray(out?.suggestions) ? out.suggestions : [];
    if (!suggestions.length) {
      resultDiv.innerHTML = '<div class="tt-note">No plausible suggestions passed the current realism/strategy filters. Try changing mode or clearing exclusions.</div>';
      return;
    }
    let html = '';
    suggestions.forEach(s => {
      const edgePct = Number((Number(s.edgePct || 0) * 100).toFixed(1));
      const edgeVal = Math.round(Number(s.theirTotal || 0) - Number(s.ourTotal || 0));
      html += '<div class="tsv2-suggestion-card">';
      html += '<div class="tsv2-headline">';
      html += `<strong>Suggestion #${s.rank}</strong>`;
      html += '<div class="tsv2-tag-wrap">';
      (s.archetypeTags || []).forEach(tag => { html += `<span class="tsv2-tag">${tag}</span>`; });
      if (!(s.archetypeTags || []).length) html += '<span class="tsv2-tag">balanced offer</span>';
      html += '</div>';
      html += '</div>';
      html += '<div class="tsv2-trade-grid">';
      html += `<div class="tsv2-side"><h5>You Send (${uiCtx?.myTeamName || 'Us'})</h5>${_renderSuggestionAssetsHtml(s.ourSend)}</div>`;
      html += `<div class="tsv2-side"><h5>You Receive (${uiCtx?.opponentTeam || 'Them'})</h5>${_renderSuggestionAssetsHtml(s.theirSend)}</div>`;
      html += '</div>';
      html += '<div class="tsv2-metrics">';
      html += `<div class="tsv2-metric">Calc Edge<span class="v" style="color:${_valueTone(edgeVal)}">${edgeVal > 0 ? '+' : ''}${edgeVal.toLocaleString()} (${edgePct > 0 ? '+' : ''}${edgePct}%)</span></div>`;
      html += `<div class="tsv2-metric">Market Plausibility<span class="v">${Number(s.scores.marketPlausibilityScore).toFixed(1)}</span></div>`;
      html += `<div class="tsv2-metric">Package Realism<span class="v">${Number(s.scores.packageRealismScore).toFixed(1)}</span></div>`;
      html += `<div class="tsv2-metric">Confidence<span class="v">${Number(s.scores.confidenceScore).toFixed(1)}</span></div>`;
      html += '</div>';
      html += `<div class="tsv2-why"><strong>Why it helps us:</strong> ${s.helpsUs}</div>`;
      html += `<div class="tsv2-why"><strong>Why it might help them:</strong> ${s.helpsThem}</div>`;
      if (s.likelyCounter?.note) {
        html += `<div class="tsv2-counter"><strong>Likely Counter:</strong> ${s.likelyCounter.note}</div>`;
      } else {
        html += '<div class="tsv2-counter"><strong>Likely Counter:</strong> No clean small counter identified under current realism/exclusion settings.</div>';
      }
      html += '</div>';
    });

    const diag = out?.diagnostics || {};
    html += '<details style="margin-top:8px;"><summary style="cursor:pointer;font-size:0.68rem;color:var(--subtext);">Suggestion diagnostics</summary>';
    html += `<div class="tsv2-diag">${JSON.stringify(diag, null, 2)}</div>`;
    html += '</details>';
    resultDiv.innerHTML = html;
  }

  function _getSuggestionStateFromDom() {
    const state = loadTradeSuggestionsV2State();
    const opponent = document.getElementById('tradeSuggestionsOpponent')?.value || state.opponentTeam || '';
    const realismMode = _normalizeRealismMode(document.getElementById('tradeSuggestionsRealism')?.value || state.realismMode);
    const strategyMode = _normalizeStrategyMode(document.getElementById('tradeSuggestionsStrategy')?.value || state.strategyMode);
    return {
      ...state,
      opponentTeam: opponent,
      realismMode,
      strategyMode,
    };
  }

  function _createExclusionBucketSets(exclusions) {
    return {
      ourPlayers: new Set(_normalizeExclusionSet(exclusions?.ourPlayers)),
      ourPicks: new Set(_normalizeExclusionSet(exclusions?.ourPicks)),
      theirPlayers: new Set(_normalizeExclusionSet(exclusions?.theirPlayers)),
      theirPicks: new Set(_normalizeExclusionSet(exclusions?.theirPicks)),
    };
  }

  function _renderExclusionColumn(title, searchId, listId, bucketKey, assets, selectedSet) {
    const listItems = (assets || []).map(a => {
      const checked = selectedSet.has(a.key) ? 'checked' : '';
      const pos = a.type === 'pick' ? 'PICK' : (a.position || a.group || '?');
      return `<label class="tsv2-check" data-filter-item="${a.label.toLowerCase().replace(/"/g, '&quot;')}"><input type="checkbox" ${checked} onchange="toggleTradeSuggestionExclusion('${bucketKey}','${a.key}',this.checked)"><span>${a.label}</span><small>${pos} ${Math.round(a.value || 0).toLocaleString()}</small></label>`;
    }).join('');
    return `
      <div class="tsv2-exclusion-col">
        <h4>${title}</h4>
        <input id="${searchId}" type="text" placeholder="Search..." oninput="renderTradeSuggestionExclusionChecks()">
        <div id="${listId}" class="tsv2-checks">${listItems || '<div class="tt-note">No assets available.</div>'}</div>
      </div>
    `;
  }

  function _renderTradeSuggestionsV2Exclusions(myTeam, oppTeam, state) {
    const wrap = document.getElementById('tradeSuggestionsExclusions');
    if (!wrap || !myTeam || !oppTeam) {
      if (wrap) wrap.innerHTML = '';
      return;
    }
    const ex = _createExclusionBucketSets(state?.exclusions || {});
    const empty = { ourPlayers: new Set(), ourPicks: new Set(), theirPlayers: new Set(), theirPicks: new Set() };
    const ourAll = _assetListFromTeam(myTeam, 'ours', empty);
    const theirAll = _assetListFromTeam(oppTeam, 'theirs', empty);
    const byType = (list, t) => list.filter(a => a.type === t);
    wrap.innerHTML = `<div class="tsv2-exclusion-grid">
      ${_renderExclusionColumn('Exclude Our Players', 'tsv2SearchOurPlayers', 'tsv2ListOurPlayers', 'ourPlayers', byType(ourAll, 'player'), ex.ourPlayers)}
      ${_renderExclusionColumn('Exclude Our Picks', 'tsv2SearchOurPicks', 'tsv2ListOurPicks', 'ourPicks', byType(ourAll, 'pick'), ex.ourPicks)}
      ${_renderExclusionColumn('Exclude Their Players', 'tsv2SearchTheirPlayers', 'tsv2ListTheirPlayers', 'theirPlayers', byType(theirAll, 'player'), ex.theirPlayers)}
      ${_renderExclusionColumn('Exclude Their Picks', 'tsv2SearchTheirPicks', 'tsv2ListTheirPicks', 'theirPicks', byType(theirAll, 'pick'), ex.theirPicks)}
    </div>`;
    __tradeSuggestionsV2.exclusionView = {
      ourAll,
      theirAll,
    };
    renderTradeSuggestionExclusionChecks();
  }

  function renderTradeSuggestionExclusionChecks() {
    const groups = [
      { input: 'tsv2SearchOurPlayers', list: 'tsv2ListOurPlayers' },
      { input: 'tsv2SearchOurPicks', list: 'tsv2ListOurPicks' },
      { input: 'tsv2SearchTheirPlayers', list: 'tsv2ListTheirPlayers' },
      { input: 'tsv2SearchTheirPicks', list: 'tsv2ListTheirPicks' },
    ];
    groups.forEach(g => {
      const q = String(document.getElementById(g.input)?.value || '').trim().toLowerCase();
      const list = document.getElementById(g.list);
      if (!list) return;
      list.querySelectorAll('[data-filter-item]').forEach(node => {
        const text = String(node.getAttribute('data-filter-item') || '');
        node.style.display = (!q || text.includes(q)) ? '' : 'none';
      });
    });
  }

  function toggleTradeSuggestionExclusion(bucket, key, checked) {
    const state = _getSuggestionStateFromDom();
    const validBuckets = ['ourPlayers','ourPicks','theirPlayers','theirPicks'];
    if (!validBuckets.includes(bucket)) return;
    const normalized = normalizeForLookup(key);
    if (!normalized) return;
    const next = new Set(_normalizeExclusionSet(state.exclusions?.[bucket]));
    if (checked) next.add(normalized);
    else next.delete(normalized);
    state.exclusions[bucket] = Array.from(next);
    state.lastOutput = null;
    saveTradeSuggestionsV2State(state);
    const results = document.getElementById('tradeSuggestionsV2Results');
    if (results) {
      results.innerHTML = '<div class="tt-note">Exclusions updated. Click Generate to refresh suggestions.</div>';
    }
  }

  function clearTradeSuggestionExclusions() {
    const state = _getSuggestionStateFromDom();
    state.exclusions = {
      ourPlayers: [],
      ourPicks: [],
      theirPlayers: [],
      theirPicks: [],
    };
    saveTradeSuggestionsV2State(state);
    generateTradeSuggestionsV2();
  }

  function _collectLeagueAvgByGroupForSuggestions() {
    const teams = Array.isArray(sleeperTeams) ? sleeperTeams : [];
    const empty = { ourPlayers: new Set(), ourPicks: new Set(), theirPlayers: new Set(), theirPicks: new Set() };
    const totals = {};
    SUGGESTION_GROUPS.concat(['PICKS']).forEach(g => { totals[g] = []; });
    teams.forEach(t => {
      const list = _assetListFromTeam(t, 'ours', empty);
      const byGroup = {};
      SUGGESTION_GROUPS.concat(['PICKS']).forEach(g => { byGroup[g] = 0; });
      list.forEach(a => {
        if (byGroup[a.group] == null) byGroup[a.group] = 0;
        byGroup[a.group] += Number(a.value || 0);
      });
      Object.keys(byGroup).forEach(g => totals[g].push(byGroup[g]));
    });
    const avg = {};
    Object.keys(totals).forEach(g => {
      const vals = totals[g];
      avg[g] = vals.length ? (vals.reduce((s, v) => s + v, 0) / vals.length) : 0;
    });
    return avg;
  }

  function _sanitizeSuggestionExclusionsForTeams(state, myTeam, oppTeam) {
    const next = _cloneTradeSuggestionState(state) || getDefaultTradeSuggestionsV2State();
    const empty = { ourPlayers: new Set(), ourPicks: new Set(), theirPlayers: new Set(), theirPicks: new Set() };
    const ourAssets = _assetListFromTeam(myTeam, 'ours', empty);
    const theirAssets = _assetListFromTeam(oppTeam, 'theirs', empty);
    const ourPlayerKeys = new Set(ourAssets.filter(a => a.type === 'player').map(a => a.key));
    const ourPickKeys = new Set(ourAssets.filter(a => a.type === 'pick').map(a => a.key));
    const theirPlayerKeys = new Set(theirAssets.filter(a => a.type === 'player').map(a => a.key));
    const theirPickKeys = new Set(theirAssets.filter(a => a.type === 'pick').map(a => a.key));
    next.exclusions.ourPlayers = _normalizeExclusionSet(next.exclusions.ourPlayers).filter(k => ourPlayerKeys.has(k));
    next.exclusions.ourPicks = _normalizeExclusionSet(next.exclusions.ourPicks).filter(k => ourPickKeys.has(k));
    next.exclusions.theirPlayers = _normalizeExclusionSet(next.exclusions.theirPlayers).filter(k => theirPlayerKeys.has(k));
    next.exclusions.theirPicks = _normalizeExclusionSet(next.exclusions.theirPicks).filter(k => theirPickKeys.has(k));
    return next;
  }

  function _renderTradeSuggestionsV2Surface(myTeamName) {
    const card = document.getElementById('tradeSuggestionsV2Card');
    const results = document.getElementById('tradeSuggestionsV2Results');
    const oppSel = document.getElementById('tradeSuggestionsOpponent');
    const realismSel = document.getElementById('tradeSuggestionsRealism');
    const strategySel = document.getElementById('tradeSuggestionsStrategy');
    if (!card || !results || !oppSel || !realismSel || !strategySel || !myTeamName || !Array.isArray(sleeperTeams) || !sleeperTeams.length) {
      if (card) card.style.display = 'none';
      return;
    }
    const myTeam = sleeperTeams.find(t => t.name === myTeamName);
    if (!myTeam) {
      card.style.display = 'none';
      return;
    }
    const state = loadTradeSuggestionsV2State();
    const opponents = sleeperTeams.filter(t => t.name !== myTeamName);
    if (!opponents.length) {
      card.style.display = 'none';
      return;
    }
    const lastOpp = opponents.some(t => t.name === state.opponentTeam) ? state.opponentTeam : opponents[0].name;
    oppSel.innerHTML = opponents.map(t => `<option value="${t.name}">${t.name}</option>`).join('');
    oppSel.value = lastOpp;
    realismSel.value = _normalizeRealismMode(state.realismMode);
    strategySel.value = _normalizeStrategyMode(state.strategyMode);
    const oppTeam = sleeperTeams.find(t => t.name === lastOpp);
    const sanitized = _sanitizeSuggestionExclusionsForTeams({ ...state, opponentTeam: lastOpp }, myTeam, oppTeam);
    saveTradeSuggestionsV2State(sanitized);
    _renderTradeSuggestionsV2Exclusions(myTeam, oppTeam, sanitized);
    card.style.display = 'block';
    if (sanitized?.lastOutput?.suggestions?.length) {
      _renderTradeSuggestionsV2Results(sanitized.lastOutput, {
        myTeamName,
        opponentTeam: lastOpp,
      });
    } else {
      results.innerHTML = '<div class="tt-note">Choose settings and click Generate to build 2-3 sendable trades.</div>';
    }
  }

  function onTradeSuggestionControlChange() {
    const state = _getSuggestionStateFromDom();
    const myTeamName = document.getElementById('rosterMyTeam')?.value || localStorage.getItem('dynasty_my_team') || '';
    const myTeam = sleeperTeams.find(t => t.name === myTeamName);
    const oppTeam = sleeperTeams.find(t => t.name === state.opponentTeam);
    if (myTeam && oppTeam) {
      const sanitized = _sanitizeSuggestionExclusionsForTeams(state, myTeam, oppTeam);
      sanitized.lastOutput = null;
      saveTradeSuggestionsV2State(sanitized);
      _renderTradeSuggestionsV2Exclusions(myTeam, oppTeam, sanitized);
    } else {
      state.lastOutput = null;
      saveTradeSuggestionsV2State(state);
    }
    const results = document.getElementById('tradeSuggestionsV2Results');
    if (results) {
      results.innerHTML = '<div class="tt-note">Settings updated. Click Generate to refresh suggestions.</div>';
    }
  }

  function generateTradeSuggestionsV2() {
    const myTeamName = document.getElementById('rosterMyTeam')?.value || localStorage.getItem('dynasty_my_team') || '';
    const myTeam = sleeperTeams.find(t => t.name === myTeamName);
    const state = _getSuggestionStateFromDom();
    const oppTeam = sleeperTeams.find(t => t.name === state.opponentTeam);
    if (!myTeam || !oppTeam) {
      const results = document.getElementById('tradeSuggestionsV2Results');
      if (results) results.innerHTML = '<div class="tt-note">Select your team and an opponent team first.</div>';
      return;
    }
    const sanitized = _sanitizeSuggestionExclusionsForTeams(state, myTeam, oppTeam);
    const leagueAvgByGroup = _collectLeagueAvgByGroupForSuggestions();
    const exclusions = _createExclusionBucketSets(sanitized.exclusions);
    const out = _generateTradeSuggestionsCore({
      myTeam,
      opponentTeam: oppTeam,
      realismMode: sanitized.realismMode,
      strategyMode: sanitized.strategyMode,
      exclusions,
      leagueAvgByGroup,
    });
    __tradeSuggestionsV2.diagnostics = out.diagnostics;
    window.lastTradeSuggestionDiagnostics = out.diagnostics;
    sanitized.lastOutput = out;
    saveTradeSuggestionsV2State(sanitized);
    _renderTradeSuggestionsV2Exclusions(myTeam, oppTeam, sanitized);
    _renderTradeSuggestionsV2Results(out, {
      myTeamName,
      opponentTeam: oppTeam.name,
    });
  }

  function getTradeSuggestionsV2State() {
    return _cloneTradeSuggestionState(loadTradeSuggestionsV2State());
  }

  function setTradeSuggestionExclusions(nextExclusions) {
    const state = _getSuggestionStateFromDom();
    state.exclusions = {
      ourPlayers: _normalizeExclusionSet(nextExclusions?.ourPlayers),
      ourPicks: _normalizeExclusionSet(nextExclusions?.ourPicks),
      theirPlayers: _normalizeExclusionSet(nextExclusions?.theirPlayers),
      theirPicks: _normalizeExclusionSet(nextExclusions?.theirPicks),
    };
    saveTradeSuggestionsV2State(state);
  }

  window.__tradeSuggestionV2TestApi = {
    normalizeRealismMode: _normalizeRealismMode,
    normalizeStrategyMode: _normalizeStrategyMode,
    getRealismConfig: _getRealismConfig,
    deriveArchetypeTags: (s, c) => _deriveArchetypeTags(s, c),
    findLikelyCounter: (s, c) => _findLikelyCounter(s, c),
    generateCore: _generateTradeSuggestionsCore,
  };

  function buildRosterDashboard() {
    const container = document.getElementById('rosterRankings');
    if (!container) return;

    if (!loadedData || !sleeperTeams.length) {
      container.innerHTML = '<p style="color:var(--subtext);font-size:0.8rem;padding:12px;">Load dynasty data with Sleeper league to see roster rankings.</p>';
      document.getElementById('tradeTargetsCard').style.display = 'none';
      const suggestionsCard = document.getElementById('tradeSuggestionsV2Card');
      if (suggestionsCard) suggestionsCard.style.display = 'none';
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
    // Checkboxes
    let html = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;align-items:center;">';
    html += '<span style="font-size:0.68rem;color:var(--subtext);font-weight:600;">Show:</span>';
    ALL_GROUPS.forEach(g => {
      const checked = activeGroups.has(g) ? 'checked' : '';
      const color = POS_GROUP_COLORS[g] || 'var(--subtext)';
      html += `<label style="display:flex;align-items:center;gap:3px;font-size:0.68rem;cursor:pointer;">`;
      html += `<input type="checkbox" id="rosterFilter_${g}" ${checked} onchange="buildRosterDashboard()" style="width:13px;height:13px;accent-color:${color};">`;
      html += `<span style="color:${color};font-weight:700;">${g}</span></label>`;
    });
    const lensLabel = valueMode === 'full' ? 'Players + Picks' : valueMode === 'players' ? 'Players only' : 'Starters only';
    html += `<span style="margin-left:auto;font-size:0.66rem;color:var(--subtext);font-family:var(--mono);">Lens: ${lensLabel}</span>`;
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
    const suggestionsCard = document.getElementById('tradeSuggestionsV2Card');
    if (!myTeamName || !targetsCard || !targetsDiv) {
      if (targetsCard) targetsCard.style.display = 'none';
      if (suggestionsCard) suggestionsCard.style.display = 'none';
      return;
    }

    const myTeam = teams.find(t => t.name === myTeamName);
    if (!myTeam) {
      targetsCard.style.display = 'none';
      if (suggestionsCard) suggestionsCard.style.display = 'none';
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

    // Summary
    targetsHtml += '<div style="font-size:0.75rem;color:var(--subtext);margin-bottom:14px;">';
    targetsHtml += `<strong>${myTeamName}</strong> — `;
    targetsHtml += `Strongest: <span style="color:${POS_GROUP_COLORS[strongest[0]]};font-weight:600">${strongest[0]}</span> (${(myStrengths[strongest[0]]*100).toFixed(0)}% of avg) · `;
    targetsHtml += `Weakest: <span style="color:${POS_GROUP_COLORS[weakest[0]]};font-weight:600">${weakest[0]}</span> (${(myStrengths[weakest[0]]*100).toFixed(0)}% of avg)`;
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
              theirNeed = `needs ${worstPos}`;
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
    _renderTradeSuggestionsV2Surface(myTeamName);

    // Build additional roster features
    buildTradeGrades();
    buildWaiverWire();
  }
