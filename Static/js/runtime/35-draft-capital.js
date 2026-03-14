/*
 * Runtime Module: 35-draft-capital.js
 * Draft capital auction-dollar breakdown, pick ownership from Sleeper,
 * rookie values from KTC, pick value curve from the draft data spreadsheet.
 */

  let _draftCapitalData = null;
  let _draftCapitalLoaded = false;

  function buildDraftCapital() {
    if (_draftCapitalLoaded && _draftCapitalData) {
      renderDraftCapital(_draftCapitalData);
      return;
    }
    const loading = document.getElementById('draftCapitalLoading');
    if (loading) loading.style.display = 'block';

    fetch('/api/draft-capital')
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          if (loading) loading.textContent = 'Error: ' + data.error;
          return;
        }
        _draftCapitalData = data;
        _draftCapitalLoaded = true;
        renderDraftCapital(data);
      })
      .catch(err => {
        if (loading) loading.textContent = 'Failed to load draft capital: ' + err.message;
      });
  }

  function renderDraftCapital(data) {
    const loading = document.getElementById('draftCapitalLoading');
    const teamsDiv = document.getElementById('draftCapitalTeams');
    const picksDiv = document.getElementById('draftCapitalPicks');
    const picksCard = document.getElementById('draftCapitalPicksCard');
    if (loading) loading.style.display = 'none';
    if (!teamsDiv || !picksDiv) return;

    // ── Team totals bar chart ──
    const maxDollars = Math.max(...data.teamTotals.map(t => t.auctionDollars));
    let teamsHtml = '<div style="display:grid;gap:8px;">';
    for (const team of data.teamTotals) {
      const pct = maxDollars > 0 ? (team.auctionDollars / maxDollars * 100) : 0;
      const teamPicks = data.picks.filter(p => p.currentOwner === team.team);
      const pickCount = teamPicks.length;
      const pickLabels = teamPicks.map(p => {
        const label = p.pick;
        return p.isTraded ? label + '*' : label;
      }).join(', ');
      teamsHtml += `
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="min-width:110px;font-size:0.78rem;font-weight:600;white-space:nowrap;">${team.team}</span>
          <div style="flex:1;background:var(--bg-soft);border-radius:4px;height:24px;position:relative;overflow:hidden;">
            <div style="width:${pct}%;height:100%;background:var(--cyan);border-radius:4px;transition:width 0.3s;"></div>
          </div>
          <span style="min-width:40px;text-align:right;font-family:var(--mono);font-size:0.78rem;font-weight:700;">$${team.auctionDollars}</span>
          <span style="min-width:30px;text-align:right;font-family:var(--mono);font-size:0.68rem;color:var(--subtext);">${pickCount}pk</span>
        </div>
        <div style="font-size:0.62rem;color:var(--muted);margin-left:120px;margin-top:-4px;">${pickLabels}</div>
      `;
    }
    teamsHtml += '</div>';
    teamsHtml += `<div style="margin-top:12px;font-size:0.68rem;color:var(--subtext);">Total budget: $${data.totalBudget} across ${data.numTeams} teams, ${data.draftRounds} rounds (${data.season}). * = traded pick.</div>`;
    teamsDiv.innerHTML = teamsHtml;
    teamsDiv.style.display = 'block';

    // ── Picks by round table ──
    let picksHtml = '';
    for (let round = 1; round <= data.draftRounds; round++) {
      const roundPicks = data.picks.filter(p => p.round === round);
      const roundTotal = roundPicks.reduce((s, p) => s + p.dollarValue, 0);
      picksHtml += `<div style="margin-bottom:16px;">`;
      picksHtml += `<div style="font-weight:700;font-size:0.78rem;margin-bottom:6px;">Round ${round} <span style="color:var(--subtext);font-weight:400;">($${roundTotal})</span></div>`;
      picksHtml += `<div class="table-scroll"><table>`;
      picksHtml += `<thead><tr>
        <th style="width:60px;">Pick</th>
        <th style="width:40px;">$</th>
        <th>Owner</th>
        <th>From</th>
        <th>Rookie</th>
        <th style="width:50px;">Pos</th>
        <th style="width:70px;">KTC Value</th>
      </tr></thead><tbody>`;

      for (const pick of roundPicks) {
        const tradedStyle = pick.isTraded ? 'background:var(--amber-soft);' : '';
        const fromCol = pick.isTraded
          ? `<span style="color:var(--amber);font-weight:600;">${pick.originalOwner}</span>`
          : '<span style="color:var(--muted);">—</span>';
        const rookieName = pick.rookieName || '<span style="color:var(--muted);">—</span>';
        const rookiePos = pick.rookiePos || '';
        const rookieVal = pick.rookieKtcValue ? pick.rookieKtcValue.toLocaleString() : '';

        picksHtml += `<tr style="${tradedStyle}">
          <td style="font-family:var(--mono);font-weight:600;">${pick.pick}</td>
          <td style="font-family:var(--mono);font-weight:700;color:var(--green);">$${pick.dollarValue}</td>
          <td style="font-weight:600;">${pick.currentOwner}</td>
          <td>${fromCol}</td>
          <td>${rookieName}</td>
          <td style="font-size:0.68rem;color:var(--subtext);">${rookiePos}</td>
          <td style="font-family:var(--mono);font-size:0.72rem;">${rookieVal}</td>
        </tr>`;
      }
      picksHtml += '</tbody></table></div></div>';
    }
    picksDiv.innerHTML = picksHtml;
    if (picksCard) picksCard.style.display = 'block';
  }
