/*
 * Runtime Module: 20-data-and-calculator.js
 * Data caches, trade calculator, recalc, and edge core.
 * Extracted from legacy monolithic inline runtime to keep live behavior intact.
 */

  // ── ANCHORS ──
  function getAnchorPicksUI() {
    const arr = [];
    for (let i=0;i<6;i++) {
      const el = document.getElementById(`anchorPick${i}`);
      const v = el?(el.value||'').trim():'';
      const p = parsePickToken(v);
      arr.push(p&&p.kind==='slot'?`${p.round}.${String(p.slot).padStart(2,'0')}`:null);
    }
    return arr;
  }

  function getPickSettings() {
    return {
      currentYear: parseInt(document.getElementById('pickCurrentYear').value)||2026,
      yearDisc1: parseFloat(document.getElementById('pickYearDisc1').value)||0.85,
      yearDisc2: parseFloat(document.getElementById('pickYearDisc2').value)||0.72,
      tierEarlySlot: (document.getElementById('tierEarlySlot').value||'1.03').trim(),
      tierMidSlot:   (document.getElementById('tierMidSlot').value||'1.06').trim(),
      tierLateSlot:  (document.getElementById('tierLateSlot').value||'1.10').trim(),
      anchorPicks: getAnchorPicksUI(),
      pickDollarMapText: document.getElementById('pickDollarMap').value||''
    };
  }

  function getAnchorVals(siteKey) {
    const arr = [];
    for (let i=0;i<6;i++) {
      const el = document.getElementById(`anchor_${siteKey}_${i}`);
      const v = el?parseFloat(el.value):NaN;
      arr.push(isFinite(v)?v:null);
    }
    return arr;
  }

  function buildAnchorPts(siteKey, s, map) {
    const anchorPicks = s.anchorPicks||[];
    const anchorVals  = getAnchorVals(siteKey);
    const pts = [];
    for (let i=0;i<6;i++) {
      const pk=anchorPicks[i], v=anchorVals[i];
      if (!pk||!isFinite(v)) continue;
      const d=map[pk]; if (!isFinite(d)||d<=0) continue;
      pts.push({d,v});
    }
    pts.sort((a,b)=>b.d-a.d);
    return pts;
  }

  function siteValFromDollars(siteKey, dollars, s, map) {
    if (!isFinite(dollars)||dollars<=0) return null;
    const pts = buildAnchorPts(siteKey, s, map);
    if (!pts.length) return null;
    if (pts.length===1) return pts[0].v*(dollars/pts[0].d);
    let hi, lo;
    if (dollars>=pts[0].d) { hi=pts[0]; lo=pts[1]; }
    else if (dollars<=pts[pts.length-1].d) { hi=pts[pts.length-2]; lo=pts[pts.length-1]; }
    else { for (let i=0;i<pts.length-1;i++) { if (dollars<=pts[i].d&&dollars>=pts[i+1].d) { hi=pts[i]; lo=pts[i+1]; break; } } }
    if (!hi||!lo||!hi.d||!lo.d||!hi.v||!lo.v) return null;
    const alpha = Math.log(lo.v/hi.v)/Math.log(lo.d/hi.d);
    if (!isFinite(alpha)) return null;
    const out = hi.v*Math.pow(dollars/hi.d,alpha);
    return isFinite(out)?out:null;
  }

  // ── SITE CONFIG ──
  let __siteConfigCache = null;
  let __siteConfigDirty = true;

  function markSiteConfigDirty() {
    __siteConfigDirty = true;
    __siteConfigCache = null;
    __canonicalContextCache = null;
    __canonicalContextCacheKey = '';
    __rankCurveCache = null;
    __rankCurveCacheKey = '';
    siteStatsCache = {};
    siteStatsCachePlayersRef = null;
    siteStatsCacheKey = '';
  }

  function bindSiteConfigListeners() {
    sites.forEach(s => {
      ['include_', 'max_', 'weight_', 'tep_'].forEach(prefix => {
        const el = document.getElementById(prefix + s.key);
        if (!el) return;
        if (el.dataset.cfgBound === '1') return;
        const ev = (prefix === 'max_' || prefix === 'weight_') ? 'input' : 'change';
        el.addEventListener(ev, markSiteConfigDirty);
        el.dataset.cfgBound = '1';
      });
    });
  }

  function getSiteConfig() {
    if (!__siteConfigDirty && Array.isArray(__siteConfigCache) && __siteConfigCache.length) {
      return __siteConfigCache;
    }
    __siteConfigCache = sites.map(s => {
      const max = parseFloat((document.getElementById('max_'+s.key)||{}).value);
      const wt  = parseFloat((document.getElementById('weight_'+s.key)||{}).value);
      const inc = document.getElementById('include_'+s.key);
      const tep = document.getElementById('tep_'+s.key);
      const forceNonTep = s.key === 'dynastyDaddy';
      return {
        key: s.key, label: s.label,
        max: (isFinite(max)&&max>0)?max:s.defaultMax,
        include: inc?inc.checked:s.defaultInclude,
        weight: (isFinite(wt)&&wt>0)?wt:1.0,
        tep: forceNonTep ? false : (tep ? tep.checked : (s.tep!==false))
      };
    });
    __siteConfigDirty = false;
    return __siteConfigCache;
  }

  function getKtcMax(cfg) { return (cfg.find(s=>s.key==='ktc')||{max:9999}).max; }

  // ── STORAGE ──
  function persistSettings() {
    const payload = {
      alpha:       document.getElementById('alphaInput').value,
      tolerance:   document.getElementById('toleranceInput').value,
      flockOffset:   document.getElementById('flockOffsetInput').value,
      flockDivisor:  document.getElementById('flockDivisorInput').value,
      flockExponent: document.getElementById('flockExponentInput').value,
      idpAnchor:     document.getElementById('idpAnchorInput').value,
      idpRankOff:    document.getElementById('idpRankOffsetInput').value,
      idpRankDiv:    document.getElementById('idpRankDivisorInput').value,
      idpRankExp:    document.getElementById('idpRankExponentInput').value,
      tepMultiplier: document.getElementById('tepMultiplierInput').value,
      lamStrength: document.getElementById('lamStrengthInput')?.value,
      scarcityStrength: document.getElementById('scarcityStrengthInput')?.value,
      rankingsSortBasis: document.getElementById('rankingsSortBasis')?.value,
      rankingsDataMode: document.getElementById('rankingsDataMode')?.value,
      calculatorValueBasis: document.getElementById('calculatorValueBasis')?.value,
      rankingsShowLamCols: document.getElementById('rankingsShowLamCols')?.checked,
      rankingsShowSiteCols: document.getElementById('rankingsShowSiteCols')?.checked,
      mobilePowerMode: getMobilePowerModeEnabled(),
      edgeHighConfidence: document.getElementById('edgeHighConfidence')?.checked,
      coveragePenalty: document.getElementById('coveragePenaltyToggle')?.checked,
      minCoverage: document.getElementById('minCoverageInput')?.value,
      zScoreEnabled: document.getElementById('zScoreToggle')?.checked,
      zFloor: document.getElementById('zFloorInput')?.value,
      zCeiling: document.getElementById('zCeilingInput')?.value,
      compactMode: document.getElementById('compactToggle')?.checked,
      rosterTeam: document.getElementById('rosterMyTeam')?.value,
      rosterValueMode: document.getElementById('rosterValueMode')?.value,
      breakdownViewMode: document.getElementById('breakdownViewMode')?.value,
      activeTab: activeTabId,
      rankingsExtraFilters,
      siteConfig: getSiteConfig(),
      pickSettings: getPickSettings(),
      anchors: Object.fromEntries(sites.map(s=>[s.key, getAnchorVals(s.key)]))
    };
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload)); } catch(_) {}
  }

  function loadSettings() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY); if (!raw) return;
      const d = JSON.parse(raw);
      const sv = (id,v) => { const el=document.getElementById(id); if(el&&v!=null) el.value=v; };
      sv('alphaInput',d.alpha); sv('toleranceInput',d.tolerance);
      sv('flockOffsetInput',d.flockOffset); sv('flockDivisorInput',d.flockDivisor); sv('flockExponentInput',d.flockExponent);
      sv('idpAnchorInput',d.idpAnchor); sv('idpRankOffsetInput',d.idpRankOff); sv('idpRankDivisorInput',d.idpRankDiv);
      sv('idpRankExponentInput',d.idpRankExp);
      sv('tepMultiplierInput',d.tepMultiplier);
      sv('lamStrengthInput', d.lamStrength);
      sv('scarcityStrengthInput', d.scarcityStrength);
      sv('minCoverageInput', d.minCoverage);
      if (d.rankingsSortBasis) {
        const el = document.getElementById('rankingsSortBasis');
        if (el) el.value = normalizeValueBasis(d.rankingsSortBasis);
      }
      if (d.rankingsDataMode) {
        const el = document.getElementById('rankingsDataMode');
        if (el) el.value = normalizeRankingsDataMode(d.rankingsDataMode);
      }
      if (d.calculatorValueBasis) {
        const el = document.getElementById('calculatorValueBasis');
        if (el) el.value = normalizeValueBasis(d.calculatorValueBasis);
      }
      syncValueBasisControls(d.calculatorValueBasis || d.rankingsSortBasis || 'full');
      if (d.rankingsShowLamCols != null) {
        const el = document.getElementById('rankingsShowLamCols');
        if (el) el.checked = !!d.rankingsShowLamCols;
      }
      if (d.rankingsShowSiteCols != null) {
        const el = document.getElementById('rankingsShowSiteCols');
        if (el) el.checked = !!d.rankingsShowSiteCols;
      } else {
        const el = document.getElementById('rankingsShowSiteCols');
        if (el) el.checked = false;
      }
      if (d.mobilePowerMode != null) {
        const el = document.getElementById('mobilePowerModeToggle');
        if (el) el.checked = !!d.mobilePowerMode;
      }
      syncRankingsSourceColumnToggles();
      if (d.edgeHighConfidence != null) {
        const el = document.getElementById('edgeHighConfidence');
        if (el) el.checked = !!d.edgeHighConfidence;
      }
      if (d.coveragePenalty != null) {
        const el = document.getElementById('coveragePenaltyToggle');
        if (el) el.checked = !!d.coveragePenalty;
      }
      if (d.zScoreEnabled != null) {
        const el = document.getElementById('zScoreToggle');
        if (el) el.checked = !!d.zScoreEnabled;
      }
      sv('zFloorInput', d.zFloor);
      sv('zCeilingInput', d.zCeiling);
      if (d.compactMode != null) {
        const el = document.getElementById('compactToggle');
        if (el) { el.checked = !!d.compactMode; toggleCompactMode(el.checked); }
      }
      if (d.rosterValueMode) {
        const el = document.getElementById('rosterValueMode');
        if (el) el.value = d.rosterValueMode;
      }
      if (d.breakdownViewMode) {
        const el = document.getElementById('breakdownViewMode');
        if (el) el.value = d.breakdownViewMode;
      }
      if (d.rankingsExtraFilters && typeof d.rankingsExtraFilters === 'object') {
        rankingsExtraFilters = {
          picksOnly: !!d.rankingsExtraFilters.picksOnly,
          trendingOnly: !!d.rankingsExtraFilters.trendingOnly,
          ageBucket: d.rankingsExtraFilters.ageBucket || 'ALL',
        };
      }
      // Roster team restored after data loads (in loadJsonData)
      if (Array.isArray(d.siteConfig)) {
        d.siteConfig.forEach(s => {
          const inc=document.getElementById('include_'+s.key), max=document.getElementById('max_'+s.key), wt=document.getElementById('weight_'+s.key), tep=document.getElementById('tep_'+s.key);
          if (inc) inc.checked=!!s.include; if (max&&s.max!=null) max.value=s.max; if (wt&&s.weight!=null) wt.value=s.weight;
          if (tep&&s.tep!=null) tep.checked=(s.key === 'dynastyDaddy') ? false : !!s.tep;
        });
      }
      if (d.pickSettings) {
        const ps=d.pickSettings;
        sv('pickCurrentYear',ps.currentYear); sv('pickYearDisc1',ps.yearDisc1); sv('pickYearDisc2',ps.yearDisc2);
        sv('tierEarlySlot',ps.tierEarlySlot); sv('tierMidSlot',ps.tierMidSlot); sv('tierLateSlot',ps.tierLateSlot);
        if (ps.pickDollarMapText!=null) sv('pickDollarMap',ps.pickDollarMapText);
        if (Array.isArray(ps.anchorPicks)) for(let i=0;i<6;i++) if(ps.anchorPicks[i]) sv(`anchorPick${i}`,ps.anchorPicks[i]);
      }
      if (d.anchors) {
        sites.forEach(s => {
          const arr=d.anchors[s.key]; if (!Array.isArray(arr)) return;
          for(let i=0;i<6;i++) if(arr[i]!=null&&arr[i]!=='') sv(`anchor_${s.key}_${i}`,arr[i]);
        });
      }
      if (d.mobilePowerMode != null) {
        setMobilePowerMode(!!d.mobilePowerMode, { persist: false, refresh: false });
      }
      markSiteConfigDirty();
    } catch(_) {}
  }

  function saveSettingsAndRecalc() {
    computeSiteStats(); persistSettings(); recalculate(); switchTab('calculator');
    const n=document.getElementById('saveNotice');
    if(n){ n.textContent='✓ saved '+new Date().toLocaleTimeString(); setTimeout(()=>{ n.textContent=''; },3000); }
  }

  // ── TABLE INIT ──
  function initSiteConfig() {
    const tbody = document.getElementById('siteConfigBody');
    tbody.innerHTML = '';
    sites.forEach(s => {
      const tr = document.createElement('tr');
      tr.dataset.siteKey = s.key;
      const lockNonTep = s.key === 'dynastyDaddy';
      tr.innerHTML = `
        <td><input type="checkbox" id="include_${s.key}" ${s.defaultInclude?'checked':''}></td>
        <td style="font-weight:600;font-family:var(--mono);font-size:0.75rem;">${s.label}</td>
        <td><input type="number" step="0.01" value="${s.defaultMax}" id="max_${s.key}" style="width:110px"></td>
        <td><input type="number" step="0.1" value="${s.defaultWeight}" id="weight_${s.key}" style="width:80px"></td>
        <td style="text-align:center;"><input type="checkbox" id="tep_${s.key}" ${s.tep!==false?'checked':''} ${lockNonTep ? 'disabled title="Dynasty Daddy treated as non-TEP (TE multiplier applied)."' : ''}></td>
      `;
      tbody.appendChild(tr);
    });
    bindSiteConfigListeners();
    markSiteConfigDirty();
  }

  function syncSiteConfigToLoadedData(data) {
    if (!data) return;
    const present = new Set();
    if (Array.isArray(data.sites)) {
      data.sites.forEach(s => {
        if (s && s.key && Number(s.playerCount) > 0) present.add(s.key);
      });
    }
    if (data.maxValues && typeof data.maxValues === 'object') {
      for (const [k, v] of Object.entries(data.maxValues)) {
        if (isFinite(Number(v)) && Number(v) > 0) present.add(k);
      }
    }

    sites.forEach(s => {
      const row = document.querySelector(`#siteConfigBody tr[data-site-key="${s.key}"]`);
      const inc = document.getElementById('include_' + s.key);
      if (!row || !inc) return;
      const hasData = present.has(s.key);
      row.style.display = hasData ? '' : 'none';
      if (!hasData) {
        row.dataset.autoDisabledByDataSync = '1';
        inc.checked = false;
        inc.disabled = true;
      } else {
        inc.disabled = false;
        if (row.dataset.autoDisabledByDataSync === '1' && s.defaultInclude) {
          inc.checked = true;
        }
        delete row.dataset.autoDisabledByDataSync;
      }
    });
    markSiteConfigDirty();
  }

  function initAnchors() {
    const cont = document.getElementById('anchorPickInputs');
    cont.innerHTML = '';
    const defaults = ['1.01','1.06','1.12','2.06','3.06','4.12'];
    for (let i=0;i<6;i++) {
      const lbl = document.createElement('label');
      lbl.innerHTML = `Anchor ${i+1}<input type="text" id="anchorPick${i}" value="${defaults[i]}" placeholder="1.01">`;
      cont.appendChild(lbl);
    }
    const hdr = document.getElementById('anchorsHeaderRow');
    const body = document.getElementById('anchorsBody');
    hdr.innerHTML = '<th>Site</th>' + Array.from({length:6},(_,i)=>`<th>A${i+1} val</th>`).join('');
    body.innerHTML = '';
    sites.forEach(s => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td style="font-family:var(--mono);font-size:0.72rem;font-weight:500;">${s.label}</td>` +
        Array.from({length:6},(_,i)=>`<td><input type="number" step="1" placeholder="—" id="anchor_${s.key}_${i}" style="width:95px"></td>`).join('');
      body.appendChild(tr);
    });
  }

  function buildPlayersTable() {
    const hdr = document.getElementById('playersHeader');
    hdr.innerHTML = '<th>Player / Pick</th>' + sites.map(s=>`<th class="site-col">${s.label}</th>`).join('') + '<th>Sites</th><th>Value (Full)</th>';
    document.getElementById('playersHeaderClone').innerHTML = hdr.innerHTML;
    const hdrC = document.getElementById('playersHeaderCloneC');
    if (hdrC) hdrC.innerHTML = hdr.innerHTML;
    updateCalculatorValueHeader();
    buildSideBody('A','sideABody');
    buildSideBody('B','sideBBody');
    buildSideBody('C','sideCBody');
  }

  function buildSideBody(side, tbodyId) {
    const tbody = document.getElementById(tbodyId); tbody.innerHTML = '';
    // Start with just 1 empty row
    addPlayerRow(side, tbodyId);
  }

  function createPlayerRow(side, tbodyId) {
    const tr = document.createElement('tr');
    tr.dataset.side = side;

    const nameTd = document.createElement('td');
    nameTd.className = 'name-cell-wrap';
    const nameWrap = document.createElement('div');
    nameWrap.style.cssText = 'display:flex;flex-direction:column;gap:3px;';
    const nameInp = document.createElement('input');
    nameInp.type='text'; nameInp.className='player-name-input'; nameInp.placeholder='Name / Pick token';
    const statusSpan = document.createElement('span');
    statusSpan.className='pick-status'; statusSpan.style.display='none';
    nameWrap.appendChild(nameInp); nameWrap.appendChild(statusSpan);
    // Remove button
    const removeBtn = document.createElement('button');
    removeBtn.className = 'row-remove-btn';
    removeBtn.textContent = '×';
    removeBtn.title = 'Remove row';
    removeBtn.addEventListener('click', () => {
      const tbody = document.getElementById(tbodyId);
      const rows = tbody.querySelectorAll('tr');
      if (rows.length <= 1) {
        // Don't remove last row, just clear it
        tr.querySelectorAll('input').forEach(i => { i.value = ''; });
        tr.querySelector('.sites-used').textContent = '';
        tr.querySelector('.meta-value').innerHTML = '';
        tr.querySelectorAll('.auto-pill').forEach(p => p.textContent = '');
      } else {
        tr.remove();
      }
      scheduleRecalc();
    });
    nameTd.appendChild(nameWrap); nameTd.appendChild(removeBtn); tr.appendChild(nameTd);

    sites.forEach(s => {
      const td = document.createElement('td');
      td.className = 'site-col';
      const wrap = document.createElement('div'); wrap.style.cssText='display:flex;flex-direction:column;';
      const inp = document.createElement('input');
      inp.type='number'; inp.step='1'; inp.className='site-input';
      inp.dataset.siteKey = s.key;
      inp.placeholder = (s.mode==='rank'||s.mode==='idpRank')?'Rank':'—';
      const pill = document.createElement('span');
      pill.className='auto-pill'; pill.dataset.autoFor = s.key;
      wrap.appendChild(inp); wrap.appendChild(pill);
      td.appendChild(wrap); tr.appendChild(td);
      inp.addEventListener('input', scheduleRecalc);
    });

    const usedTd = document.createElement('td'); usedTd.className='sites-used'; tr.appendChild(usedTd);
    const metaTd = document.createElement('td');
    const metaSpan = document.createElement('span'); metaSpan.className='meta-value';
    metaTd.appendChild(metaSpan); tr.appendChild(metaTd);

    nameInp.addEventListener('input', () => {
      updatePickStatus(tr, nameInp.value);
      const val = nameInp.value.trim();
      if (val && !parsePickToken(val)) {
        showAutocomplete(nameInp, val);
      } else {
        hideAutocomplete();
      }
      // Clear entire row when name is deleted
      if (!val) {
        tr.querySelectorAll('.site-input').forEach(inp => { inp.value = ''; });
        const su = tr.querySelector('.sites-used'); if (su) su.textContent = '';
        const mv = tr.querySelector('.meta-value'); if (mv) mv.innerHTML = '';
        const pills = tr.querySelectorAll('.auto-pill'); pills.forEach(p => p.textContent = '');
        tr.dataset.sleeperId = '';
      }
      if (loadedData && val.length > 3) {
        autoFillRow(tr);
      }
      // Auto-add row when typing in the last row
      if (val) {
        const tbody = document.getElementById(tbodyId);
        const rows = tbody.querySelectorAll('tr');
        if (tr === rows[rows.length - 1] && rows.length < MAX_PLAYERS) {
          addPlayerRow(side, tbodyId);
        }
      }
      scheduleRecalc();
    });

    nameInp.addEventListener('keydown', handleNameKeydown);
    nameInp.addEventListener('blur', () => { setTimeout(hideAutocomplete, 200); });

    return tr;
  }

  function addPlayerRow(side, tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    if (rows.length >= MAX_PLAYERS) return;
    const tr = createPlayerRow(side, tbodyId);
    tbody.appendChild(tr);
    return tr;
  }

  function updatePickStatus(row, nameVal) {
    const sp = row.querySelector('.pick-status'); if (!sp) return;
    const name = (nameVal||'').trim();
    if (!name) { sp.style.display='none'; return; }
    const info = parsePickToken(name);
    if (info) {
      sp.style.display='inline-flex';
      sp.className='pick-status pick-ok';
      if (info.kind==='slot') {
        sp.textContent = `✓ ${info.year||''} ${info.round}.${String(info.slot).padStart(2,'0')}`.trim();
      } else {
        sp.textContent = `✓ ${info.year} ${info.tier} ${info.round}${['st','nd','rd','th','th','th'][info.round-1]}`;
      }
    } else if (/^\d/.test(name)) {
      sp.style.display='inline-flex';
      sp.className='pick-status pick-err';
      sp.textContent = '✗ invalid token';
    } else {
      sp.style.display='none';
    }
  }

  function clearPlayers() {
    // Rebuild each side with just 1 empty row
    buildSideBody('A','sideABody');
    buildSideBody('B','sideBBody');
    buildSideBody('C','sideCBody');
    recalculate();
  }

  function swapSides() {
    const aBody = document.getElementById('sideABody');
    const bBody = document.getElementById('sideBBody');
    if (!aBody || !bBody) return;
    const aRows = aBody.querySelectorAll('tr');
    const bRows = bBody.querySelectorAll('tr');
    // Collect all input values from both sides
    const aVals = [], bVals = [];
    aRows.forEach(row => {
      const inputs = row.querySelectorAll('input');
      aVals.push(Array.from(inputs).map(i => i.value));
    });
    bRows.forEach(row => {
      const inputs = row.querySelectorAll('input');
      bVals.push(Array.from(inputs).map(i => i.value));
    });
    // Rebuild both sides with the needed number of rows
    aBody.innerHTML = '';
    const maxA = Math.max(bVals.length, 1);
    for (let i = 0; i < maxA; i++) addPlayerRow('A', 'sideABody');
    bBody.innerHTML = '';
    const maxB = Math.max(aVals.length, 1);
    for (let i = 0; i < maxB; i++) addPlayerRow('B', 'sideBBody');
    // Fill A with B's values
    const newARows = aBody.querySelectorAll('tr');
    newARows.forEach((row, ri) => {
      const inputs = row.querySelectorAll('input');
      inputs.forEach((inp, ci) => {
        inp.value = bVals[ri] && bVals[ri][ci] != null ? bVals[ri][ci] : '';
      });
      const nameInp = row.querySelector('.player-name-input');
      if (nameInp && nameInp.value.trim()) autoFillRow(row);
    });
    // Fill B with A's values
    const newBRows = bBody.querySelectorAll('tr');
    newBRows.forEach((row, ri) => {
      const inputs = row.querySelectorAll('input');
      inputs.forEach((inp, ci) => {
        inp.value = aVals[ri] && aVals[ri][ci] != null ? aVals[ri][ci] : '';
      });
      const nameInp = row.querySelector('.player-name-input');
      if (nameInp && nameInp.value.trim()) autoFillRow(row);
    });
    // Keep team-side context aligned with swapped assets.
    const teamAEl = document.getElementById('teamFilterA');
    const teamBEl = document.getElementById('teamFilterB');
    const teamA = String(teamAEl?.value || '');
    const teamB = String(teamBEl?.value || '');
    if (teamAEl) teamAEl.value = teamB;
    if (teamBEl) teamBEl.value = teamA;
    updateTeamFilter();
    recalculate();
  }

  function clearPlayersFromMobile() {
    clearPlayers();
    // Keep mobile chip workspace in sync immediately for touch feedback.
    renderMobileTradeWorkspace();
    updateMobileTradeTray();
    syncMobileTradeControlState();
  }

  function swapSidesFromMobile() {
    swapSides();
    // Ensure mobile projections + controls reflect swapped teams/assets immediately.
    renderMobileTradeWorkspace();
    updateMobileTradeTray();
    syncMobileTradeControlState();
  }

  function toggleCompactMode(on) {
    const tables = document.querySelectorAll('#tab-calculator .table-scroll table');
    tables.forEach(t => t.classList.toggle('compact-mode', on));
  }

  let multiTeamMode = false;
  function toggleMultiTeam(on) {
    multiTeamMode = on;
    document.getElementById('sideCSection').style.display = on ? 'block' : 'none';
    document.getElementById('tileSideC').style.display = on ? '' : 'none';
    const mobileSideC = document.getElementById('mobileTradeSideCSection');
    if (mobileSideC) mobileSideC.style.display = on ? '' : 'none';
    const mobileToggle = document.getElementById('mobileMultiTeamToggle');
    if (mobileToggle) mobileToggle.checked = !!on;
    document.getElementById('resultTiles').classList.toggle('three-way', on);
    // Hide trade bar + verdict bar in 3-team mode (they're 2-side only)
    document.querySelector('.trade-bar-wrap').style.display = on ? 'none' : '';
    const vb = document.getElementById('verdictBar');
    if (vb) vb.style.display = on ? 'none' : '';
    recalculate();
  }

  // ── LOADED DATA ──
  let loadedData = null;
  let playerNames = [];
  let sleeperTeams = [];
  let teamFilterA = '';
  let teamFilterB = '';
  let teamFilterC = '';
  let playerPositions = {};
  let playerSleeperIds = {};   // canonical player name -> sleeper_id
  let sleeperIdToPlayer = {};  // sleeper_id -> canonical player name
  let ktcIdToPlayer = {};      // ktc playerID -> canonical player name
  let playerNameByNorm = new Map();      // normalized player name -> canonical player name
  let playerPosByNorm = new Map();       // normalized player name -> normalized position
  let normalizeLookupCache = new Map();  // raw lookup token -> normalized lookup token
  let postDataViewsHydrated = false;
  let trendComputeToken = 0;
  let pendingTrendCompute = null;

  function normalizePositionFamily(pos) {
    const up = String(pos || '').trim().toUpperCase();
    if (!up) return '';
    if (['DE','DT','EDGE','NT'].includes(up)) return 'DL';
    if (['CB','S','FS','SS'].includes(up)) return 'DB';
    if (['OLB','ILB'].includes(up)) return 'LB';
    return up;
  }

  function rebuildPlayerLookupCaches() {
    playerNameByNorm = new Map();
    playerPosByNorm = new Map();

    const assignName = (name) => {
      const canonical = String(name || '').trim();
      const norm = normalizeForLookup(canonical);
      if (!canonical || !norm) return;
      if (!playerNameByNorm.has(norm)) playerNameByNorm.set(norm, canonical);
    };
    const assignPos = (name, pos) => {
      const norm = normalizeForLookup(name);
      if (!norm) return;
      const normalizedPos = normalizePositionFamily(pos);
      if (!normalizedPos) return;
      if (!playerPosByNorm.has(norm)) playerPosByNorm.set(norm, normalizedPos);
    };

    for (const name of Object.keys(loadedData?.players || {})) assignName(name);
    for (const [name, pos] of Object.entries(playerPositions || {})) {
      assignName(name);
      assignPos(name, pos);
    }
  }

  function resolveCanonicalPlayerName(name) {
    if (!name || !loadedData?.players) return '';
    const direct = String(name || '').trim();
    if (loadedData.players[direct]) return direct;
    const norm = normalizeForLookup(direct);
    if (!norm) return '';
    return playerNameByNorm.get(norm) || '';
  }

  function resolvePlayerPositionByName(name) {
    const canonical = resolveCanonicalPlayerName(name) || String(name || '').trim();
    if (!canonical) return '';
    const direct = playerPositions?.[canonical];
    if (direct) return normalizePositionFamily(direct);
    const norm = normalizeForLookup(canonical);
    return playerPosByNorm.get(norm) || '';
  }

  function resolvePreferredTeamName(opts = {}) {
    const teams = Array.isArray(opts.teams) ? opts.teams : (Array.isArray(sleeperTeams) ? sleeperTeams : []);
    if (!teams.length) return '';
    const names = teams.map(t => String(t?.name || '').trim()).filter(Boolean);
    if (!names.length) return '';

    const byLower = new Map(names.map(n => [n.toLowerCase(), n]));
    const resolveMatch = (candidate) => {
      const c = String(candidate || '').trim();
      if (!c) return '';
      return byLower.get(c.toLowerCase()) || '';
    };

    const candidates = [
      opts.explicitTeam,
      opts.savedTeam,
      opts.profileTeam,
      DEFAULT_TEAM_NAME,
    ];
    for (const c of candidates) {
      const match = resolveMatch(c);
      if (match) return match;
    }

    return [...names].sort((a, b) => a.localeCompare(b))[0] || names[0];
  }

  function populateTeamDropdowns() {
    const selA = document.getElementById('teamFilterA');
    const selB = document.getElementById('teamFilterB');
    const selC = document.getElementById('teamFilterC');
    const selMyTeam = document.getElementById('rosterMyTeam');

    // Populate calculator team filters
    [selA, selB, selC].forEach(sel => {
      if (!sel) return;
      sel.innerHTML = '<option value="">All players</option>';
      sleeperTeams.forEach(team => {
        const opt = document.createElement('option');
        opt.value = team.name;
        opt.textContent = `${team.name} (${team.players.length})`;
        sel.appendChild(opt);
      });
    });
    // Populate My Team dropdown
    if (selMyTeam) {
      selMyTeam.innerHTML = '<option value="">Select your team</option>';
      sleeperTeams.forEach(team => {
        const opt = document.createElement('option');
        opt.value = team.name;
        opt.textContent = team.name;
        selMyTeam.appendChild(opt);
      });
    }
    // Populate global team selector on calculator page
    const selGlobal = document.getElementById('globalMyTeam');
    if (selGlobal) {
      selGlobal.innerHTML = '<option value="">Select team</option>';
      sleeperTeams.forEach(team => {
        const opt = document.createElement('option');
        opt.value = team.name;
        opt.textContent = team.name;
        selGlobal.appendChild(opt);
      });
    }
    // Populate trade team filter
    const selTrade = document.getElementById('tradeTeamFilter');
    if (selTrade) {
      selTrade.innerHTML = '<option value="">All trades</option>';
      sleeperTeams.forEach(team => {
        const opt = document.createElement('option');
        opt.value = team.name;
        opt.textContent = team.name;
        selTrade.appendChild(opt);
      });
    }

    // Populate Trade Finder opponent dropdown
    const selFinder = document.getElementById('finderOpponentFilter');
    if (selFinder) {
      selFinder.innerHTML = '<option value="all">All Teams</option>';
      sleeperTeams.forEach(team => {
        const opt = document.createElement('option');
        opt.value = team.name;
        opt.textContent = team.name;
        selFinder.appendChild(opt);
      });
    }

    const profileTeam = getProfile()?.teamName || '';
    const savedTeam = localStorage.getItem('dynasty_my_team') || '';
    const preferred = resolvePreferredTeamName({
      teams: sleeperTeams,
      savedTeam,
      profileTeam,
    });
    if (preferred) syncGlobalTeam(preferred);

    // Reset league tab so dropdowns get repopulated on next visit
    _leagueInited = false;
    syncMobileTradeControlState();
  }

  // Sync global team selector across all pages
  function syncGlobalTeam(teamName) {
    const profileTeam = getProfile()?.teamName || '';
    const savedTeam = localStorage.getItem('dynasty_my_team') || '';
    const resolved = resolvePreferredTeamName({
      teams: sleeperTeams,
      explicitTeam: teamName,
      savedTeam,
      profileTeam,
    });
    if (!resolved) return;

    localStorage.setItem('dynasty_my_team', resolved);
    const selRoster = document.getElementById('rosterMyTeam');
    const selGlobal = document.getElementById('globalMyTeam');
    const selTrade = document.getElementById('tradeTeamFilter');
    if (selRoster) selRoster.value = resolved;
    if (selGlobal) selGlobal.value = resolved;
    if (selTrade) selTrade.value = resolved;

    const profile = getProfile();
    if (profile && profile.teamName !== resolved) {
      const team = (Array.isArray(sleeperTeams) ? sleeperTeams : []).find(t => t.name === resolved);
      saveProfile({
        ...profile,
        teamName: resolved,
        rosterId: team?.rosterId ?? team?.roster_id ?? profile.rosterId ?? '',
        savedAt: new Date().toISOString(),
      });
    }
    // Refresh any active tab that depends on team
    checkEdgeGate();
    if (typeof checkFinderGate === 'function') checkFinderGate();
  }

  function updateTeamFilter() {
    teamFilterA = document.getElementById('teamFilterA').value;
    teamFilterB = document.getElementById('teamFilterB').value;
    const selC = document.getElementById('teamFilterC');
    teamFilterC = selC ? selC.value : '';
    // Populate roster panels
    populateRosterPanel('rosterPanelA', teamFilterA, 'sideABody');
    populateRosterPanel('rosterPanelB', teamFilterB, 'sideBBody');
    syncMobileTradeControlState();
    renderMobileRosterPanels({ force: true });
  }

  function populateRosterPanel(panelId, teamName, tbodyId) {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    if (!teamName || !loadedData) { panel.style.display = 'none'; return; }
    const team = sleeperTeams.find(t => t.name === teamName);
    if (!team) { panel.style.display = 'none'; return; }

    // Get composites for all team players and sort by value
    const players = [];
    for (const name of team.players) {
      const result = computeMetaValueForPlayer(name);
      const meta = result ? result.metaValue : 0;
      const pos = getPlayerPosition(name) || '?';
      if (isKickerPosition(pos)) continue;
      players.push({ name, meta: Math.round(meta), pos });
    }
    players.sort((a, b) => b.meta - a.meta);

    const POS_C = {QB:'#e74c3c',RB:'#27ae60',WR:'#3498db',TE:'#e67e22',K:'#999',LB:'#9b59b6',DL:'#9b59b6',DB:'#16a085'};
    let html = '';
    for (const p of players) {
      const posC = POS_C[p.pos] || 'var(--subtext)';
      html += `<div class="roster-panel-item" data-player="${p.name.replace(/"/g,'&quot;')}" data-tbody="${tbodyId}">`;
      html += `<span class="rp-pos" style="color:${posC};">${p.pos}</span>`;
      html += `<span style="font-weight:600;">${p.name}</span>`;
      html += `<span class="rp-val">${p.meta > 0 ? p.meta.toLocaleString() : '—'}</span>`;
      html += `</div>`;
    }
    panel.innerHTML = html;
    panel.style.display = 'block';

    // Add click handlers
    panel.querySelectorAll('.roster-panel-item').forEach(item => {
      item.addEventListener('click', () => {
        const playerName = item.dataset.player;
        const tbody = document.getElementById(item.dataset.tbody);
        if (!tbody || !playerName) return;
        // Find first empty row
        const rows = tbody.querySelectorAll('tr');
        for (const row of rows) {
          const nameInp = row.querySelector('.player-name-input');
          if (nameInp && !nameInp.value.trim()) {
            nameInp.value = playerName;
            autoFillRow(row);
            scheduleRecalc();
            break;
          }
        }
      });
    });
  }

  function getTeamPlayers(teamName) {
    if (!teamName) return null;
    const team = sleeperTeams.find(t => t.name === teamName);
    return team ? new Set(team.players.map(p => p.toLowerCase())) : null;
  }

  function isPlayerTE(name) {
    if (!name) return false;
    return resolvePlayerPositionByName(name) === 'TE';
  }

  function computeMetaFromSiteValues(siteValues, opts = {}) {
    if (!siteValues || typeof siteValues !== 'object') return null;
    const isPick = !!opts.isPick;
    const playerName = opts.playerName || '';
    const playerIsTE = !isPick && isPlayerTE(playerName);
    const playerPos = !isPick ? (getPlayerPosition(playerName) || '').toUpperCase() : '';
    const playerIsIdp = !isPick && IDP_POSITIONS.has(playerPos);
    const pickValuesCanonical = !!(isPick && (opts.pickValuesCanonical || siteValues?.__canonical));
    const composite = computeCanonicalCompositeFromSiteValues(siteValues, {
      playerName,
      playerPos,
      playerIsTE,
      playerIsIdp,
      isPick,
      pickValuesCanonical,
    });
    if (!composite) return null;

    let adjBundle = null;
    let metaValue = composite.rawCompositeValue;
    if (!isPick) {
      const adjPos = playerPos || (getPlayerPosition(playerName) || '');
      adjBundle = computeFinalAdjustedValue(composite.rawCompositeValue, adjPos, playerName, {
        siteCount: composite.siteCount,
        cv: composite.cv,
        siteDetails: composite.siteDetails,
        preferPrecomputed: false,
      });
      metaValue = adjBundle.finalAdjustedValue;
    }
    const rawMarketValue = clampValue(Math.round(adjBundle?.rawMarketValue ?? composite.rawCompositeValue), 1, COMPOSITE_SCALE);

    return {
      metaValue: clampValue(Math.round(metaValue), 1, COMPOSITE_SCALE),
      siteCount: composite.siteCount,
      siteDetails: composite.siteDetails,
      cv: composite.cv,
      rawMarketValue,
      baselineBucket: adjBundle?.scoring?.baselineBucket || null,
      scoringMultiplierRaw: adjBundle?.scoring?.leagueMultiplier ?? 1,
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
      scoringAdjustedValue: adjBundle?.scoringAdjustedValue ?? rawMarketValue,
      scarcityAdjustedValue: adjBundle?.scarcityAdjustedValue ?? rawMarketValue,
      finalAdjustedValue: adjBundle?.finalAdjustedValue ?? rawMarketValue,
      valueDelta: adjBundle?.valueDelta ?? 0,
    };
  }

  function normalizeTradeAssetLabel(asset) {
    if (asset == null) return '';
    if (typeof asset === 'string' || typeof asset === 'number') {
      return String(asset).trim();
    }
    if (typeof asset === 'object') {
      for (const key of ['name', 'label', 'assetLabel', 'displayName', 'playerName', 'asset']) {
        const val = asset?.[key];
        if (val != null && String(val).trim()) return String(val).trim();
      }
      if (asset?.pick != null && String(asset.pick).trim()) return String(asset.pick).trim();
      if (asset?.id != null && String(asset.id).trim()) return String(asset.id).trim();
    }
    return '';
  }

  function getTradeSideItemLabels(items) {
    if (!Array.isArray(items)) return [];
    return items
      .map(normalizeTradeAssetLabel)
      .filter(Boolean);
  }

  let tradeItemValueCache = { key: '', map: new Map() };

  // ── TRADE ITEM VALUE RESOLVER ──
  // Returns { metaValue, isPick } for any trade item (player name or pick token)
  function getTradeItemValue(itemName) {
    const normalizedName = normalizeTradeAssetLabel(itemName);
    if (!normalizedName) return { metaValue: 0, isPick: false, displayName: '' };
    const mode = getCalculatorValueBasis();
    const cacheScope = `${String(loadedData?.scrapeTimestamp || loadedData?.date || '')}|${mode}`;
    if (tradeItemValueCache.key !== cacheScope) {
      tradeItemValueCache = { key: cacheScope, map: new Map() };
    }
    const cacheKey = `${mode}|${normalizeForLookup(normalizedName)}`;
    const cached = tradeItemValueCache.map.get(cacheKey);
    if (cached) return { ...cached };

    const applyTradeMode = (baseResult, isPick, resolvedName = normalizedName) => {
      if (!baseResult) return { metaValue: 0, isPick };
      const raw = Math.max(1, Math.round(Number(baseResult.rawMarketValue ?? baseResult.metaValue) || 0));
      const pos = isPick ? 'PICK' : (getPlayerPosition(resolvedName) || getPlayerPosition(normalizedName) || '');
      const bundle = computeFinalAdjustedValue(raw, pos, resolvedName);
      const selected = Math.max(1, Math.round(getValueByRankingMode(bundle, mode)));
      const out = {
        ...baseResult,
        ...bundle,
        rawMarketValue: raw,
        metaValue: selected,
        isPick,
        displayName: normalizedName,
        resolvedName,
      };
      tradeItemValueCache.map.set(cacheKey, out);
      return { ...out };
    };

    const pickInfo = parsePickToken(normalizedName);
    if (pickInfo) {
      // Trade-history picks can include ownership decoration (e.g., "(from Team X)").
      // Resolve against canonical backend pick labels first so we value the exact traded pick
      // before falling back to inferred/proxy paths.
      const exactLabels = [];
      const seen = new Set();
      const pushLabel = (label) => {
        const s = String(label || '').trim();
        if (!s) return;
        const nk = normalizeForLookup(s);
        if (!nk || seen.has(nk)) return;
        seen.add(nk);
        exactLabels.push(s);
      };
      // Canonical labels first so equivalent pick strings resolve to the same
      // backend pick row/value. Keep original as fallback only.
      getCanonicalPickLookupLabels(pickInfo).forEach(pushLabel);
      pushLabel(normalizedName);
      for (const label of exactLabels) {
        const exact = computeMetaValueForPlayer(label, { rawOnly: true });
        if (exact && exact.metaValue > 0) {
          return applyTradeMode(exact, true, label);
        }
      }

      const directPick = computeMetaValueForPlayer(normalizedName, { rawOnly: true });
      if (directPick && directPick.metaValue > 0) {
        return applyTradeMode(directPick, true, normalizedName);
      }
      const pickData = resolvePickSiteValues(pickInfo);
      if (pickData) {
        const pickResult = computeMetaFromSiteValues(pickData, { isPick: true, playerName: normalizedName });
        if (pickResult && pickResult.metaValue > 0) {
          return applyTradeMode(pickResult, true, normalizedName);
        }

        const ktcVal = Number(pickData.ktc);
        if (isFinite(ktcVal) && ktcVal > 0) {
          return applyTradeMode({
            metaValue: Math.round(ktcVal),
            rawMarketValue: Math.round(ktcVal),
            siteCount: 1,
            siteDetails: { ktc: Math.round(ktcVal) },
          }, true, normalizedName);
        }
      }
      const out = { metaValue: 0, isPick: true, displayName: normalizedName, resolvedName: normalizedName };
      tradeItemValueCache.map.set(cacheKey, out);
      return { ...out };
    }

    const result = computeMetaValueForPlayer(normalizedName, { rawOnly: true });
    if (!result) {
      const out = { metaValue: 0, isPick: false, displayName: normalizedName, resolvedName: normalizedName };
      tradeItemValueCache.map.set(cacheKey, out);
      return { ...out };
    }
    return applyTradeMode(result, false, normalizedName);
  }

  // [NEW] Get player position from any source
  function getPlayerPosition(name) {
    if (!name) return null;
    let pos = resolvePlayerPositionByName(name);
    if (!pos) {
      pos = getRookiePosHint(name);
    }
    if (!pos) return null;
    return normalizePositionFamily(pos);
  }

  function handleJsonLoad(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function(e) {
      try {
        const data = JSON.parse(e.target.result);
        if (!loadJsonData(data)) {
          alert('This file doesn\'t look right — make sure you\'re uploading the player values file.');
          return;
        }
        const btn = document.getElementById('loadDataBtn');
        if (btn) { btn.textContent = '✓ Values Loaded'; setTimeout(() => { btn.textContent = '📊 Import File'; }, 3000); }
        recalculate();
      } catch(err) {
        alert('Couldn\'t read that file. Make sure it\'s the right one.');
      }
    };
    reader.readAsText(file);
    event.target.value = '';
  }

  function normalizeForLookup(s) {
    const raw = String(s || '');
    if (!raw) return '';
    const cached = normalizeLookupCache.get(raw);
    if (cached != null) return cached;
    const normalized = raw.trim().toLowerCase()
      .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
      // Treat hyphenated names and spaced names as equivalent (e.g., Hines-Allen vs Hines Allen).
      .replace(/[-,]/g, ' ')
      .replace(/['\u2018\u2019\u0060\u00B4\u2032.]/g, '')
      .replace(/\s+(jr|sr|ii|iii|iv|v)\.?$/i, '')
      .replace(/\s+/g, ' ');
    if (normalizeLookupCache.size > 20000) normalizeLookupCache.clear();
    normalizeLookupCache.set(raw, normalized);
    return normalized;
  }

  function readJsonStore(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw);
      return parsed == null ? fallback : parsed;
    } catch(_) {
      return fallback;
    }
  }

  function writeJsonStore(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch(_) {}
  }

  function uniqTrimmed(list, max = 50) {
    const out = [];
    const seen = new Set();
    for (const item of (list || [])) {
      const v = String(item || '').trim();
      if (!v) continue;
      const k = v.toLowerCase();
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(v);
      if (out.length >= max) break;
    }
    return out;
  }

  function getRecentPlayers() {
    return uniqTrimmed(readJsonStore(RECENT_PLAYERS_KEY, []), 20);
  }

  function addRecentPlayer(name) {
    if (!name) return;
    const list = getRecentPlayers();
    const norm = normalizeForLookup(name);
    const next = [name, ...list.filter(x => normalizeForLookup(x) !== norm)].slice(0, 20);
    writeJsonStore(RECENT_PLAYERS_KEY, next);
  }

  function getRecentSearches() {
    return uniqTrimmed(readJsonStore(RECENT_SEARCHES_KEY, []), 18);
  }

  function addRecentSearch(query) {
    const q = String(query || '').trim();
    if (!q || q.length < 2) return;
    const list = getRecentSearches();
    const norm = normalizeForLookup(q);
    const next = [q, ...list.filter(x => normalizeForLookup(x) !== norm)].slice(0, 18);
    writeJsonStore(RECENT_SEARCHES_KEY, next);
  }

  function getTradeSideAssets(side, opts = {}) {
    const tbodyId = side === 'A' ? 'sideABody' : side === 'B' ? 'sideBBody' : 'sideCBody';
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return [];
    const includeRowIndex = !!opts.includeRowIndex;
    const out = [];
    tbody.querySelectorAll('tr').forEach((row, rowIndex) => {
      const inp = row.querySelector('.player-name-input');
      const name = String(inp?.value || '').trim();
      if (!name) return;
      const cachedMeta = Number(row.dataset.metaValue);
      const meta = (Number.isFinite(cachedMeta) && cachedMeta > 0)
        ? Math.round(cachedMeta)
        : (() => {
            const result = computeMetaValueForPlayer(name);
            return result?.metaValue && isFinite(result.metaValue) ? Math.round(result.metaValue) : 0;
          })();
      const next = { name, meta };
      if (includeRowIndex) next.rowIndex = rowIndex;
      out.push(next);
    });
    return out;
  }

  function addAssetToTrade(side, name) {
    const canonical = getCanonicalPlayerName(name) || name;
    if (!canonical) return;
    const tbodyId = side === 'A' ? 'sideABody' : side === 'B' ? 'sideBBody' : 'sideCBody';
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    let targetRow = null;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    targetRow = rows.find(r => !String(r.querySelector('.player-name-input')?.value || '').trim()) || null;
    if (!targetRow) {
      targetRow = addPlayerRow(side, tbodyId);
    }
    const inp = targetRow?.querySelector('.player-name-input');
    if (!inp) return;
    inp.value = canonical;
    autoFillRow(targetRow);
    scheduleRecalc();
    switchTab('calculator');
  }

  function removeAssetFromTrade(side, name, rowIndex = null) {
    const tbodyId = side === 'A' ? 'sideABody' : side === 'B' ? 'sideBBody' : 'sideCBody';
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll('tr'));

    if (Number.isInteger(rowIndex) && rowIndex >= 0 && rowIndex < rows.length) {
      const row = rows[rowIndex];
      const inp = row?.querySelector('.player-name-input');
      if (inp) inp.value = '';
      row?.querySelectorAll('.site-input').forEach(si => { si.value = ''; });
      const mv = row?.querySelector('.meta-value'); if (mv) mv.innerHTML = '';
      const su = row?.querySelector('.sites-used'); if (su) su.textContent = '';
      scheduleRecalc();
      return;
    }

    const targetNorm = normalizeForLookup(name);
    for (const row of rows) {
      const inp = row.querySelector('.player-name-input');
      const rowName = String(inp?.value || '').trim();
      if (!rowName) continue;
      if (normalizeForLookup(rowName) !== targetNorm) continue;
      inp.value = '';
      row.querySelectorAll('.site-input').forEach(si => { si.value = ''; });
      const mv = row.querySelector('.meta-value'); if (mv) mv.innerHTML = '';
      const su = row.querySelector('.sites-used'); if (su) su.textContent = '';
      scheduleRecalc();
      return;
    }
  }

  function updateCalculatorEmptyHint() {
    const el = document.getElementById('calculatorEmptyHint');
    if (!el) return;
    const hasData = !!(loadedData && loadedData.players && Object.keys(loadedData.players).length);
    const hasAssets = getTradeSideAssets('A').length || getTradeSideAssets('B').length || getTradeSideAssets('C').length;
    if (!hasData) {
      el.style.display = '';
      el.innerHTML = `
        <strong style="color:var(--text);">No values loaded.</strong>
        Tap <strong>Refresh Values</strong> first, then add players or import a KTC trade URL.
      `;
      return;
    }
    if (!hasAssets) {
      const team = localStorage.getItem('dynasty_my_team') || '';
      el.style.display = '';
      el.innerHTML = `
        <strong style="color:var(--text);">Start your trade.</strong>
        ${team ? `Team context: <strong>${team}</strong>.` : 'Choose your team for roster-aware context.'}
        Add assets in each side, or import directly from KeepTradeCut.
      `;
      return;
    }
    el.style.display = 'none';
    el.textContent = '';
  }

  const mobileRosterPanelState = { A: false, B: false, C: false };
  const mobileRosterPanelCacheKey = { A: '', B: '', C: '' };

  function toggleMobileRosterPanel(side) {
    const key = String(side || '').toUpperCase();
    if (!['A', 'B', 'C'].includes(key)) return;
    mobileRosterPanelState[key] = !mobileRosterPanelState[key];
    if (!mobileRosterPanelState[key]) {
      const panel = document.getElementById(`mobileRosterPanel${key}`);
      if (panel) panel.style.display = 'none';
      return;
    }
    renderMobileRosterPanel(key, { force: true });
  }

  function renderMobileRosterPanel(side, opts = {}) {
    const key = String(side || '').toUpperCase();
    const panel = document.getElementById(`mobileRosterPanel${key}`);
    if (!panel) return;
    const isOpen = !!mobileRosterPanelState[key];
    if (!isOpen) {
      panel.style.display = 'none';
      return;
    }

    const teamName = String(document.getElementById(`teamFilter${key}`)?.value || '').trim();
    if (!teamName) {
      panel.innerHTML = '<div class="mobile-roster-item"><span class="name">Select a team to load roster assets.</span></div>';
      panel.style.display = 'block';
      mobileRosterPanelCacheKey[key] = '';
      return;
    }
    const team = sleeperTeams.find(t => String(t?.name || '') === teamName);
    if (!team) {
      panel.innerHTML = '<div class="mobile-roster-item"><span class="name">Team roster not found.</span></div>';
      panel.style.display = 'block';
      mobileRosterPanelCacheKey[key] = '';
      return;
    }

    const cacheKey = `${teamName}|${getCalculatorValueBasis()}|${team.players?.length || 0}|${Object.keys(loadedData?.players || {}).length}`;
    if (!opts.force && mobileRosterPanelCacheKey[key] === cacheKey) {
      panel.style.display = 'block';
      return;
    }

    const rows = [];
    (team.players || []).forEach(playerName => {
      const pos = getPlayerPosition(playerName) || '';
      if (isKickerPosition(pos)) return;
      const result = getTradeItemValue(playerName);
      const meta = Number(result?.metaValue || 0);
      rows.push({
        name: playerName,
        pos,
        meta: isFinite(meta) ? Math.round(meta) : 0,
      });
    });
    rows.sort((a, b) => b.meta - a.meta || a.name.localeCompare(b.name));

    if (!rows.length) {
      panel.innerHTML = '<div class="mobile-roster-item"><span class="name">No usable assets on this roster.</span></div>';
      panel.style.display = 'block';
      mobileRosterPanelCacheKey[key] = cacheKey;
      return;
    }

    const topRows = rows.slice(0, 28);
    panel.innerHTML = topRows.map(r => `
      <div class="mobile-roster-item">
        <span class="name">${r.name}</span>
        <span class="meta">${r.pos ? `${r.pos} · ` : ''}${r.meta > 0 ? r.meta.toLocaleString() : '—'}</span>
        <button class="mobile-chip-btn" style="padding:2px 8px;font-size:0.64rem;" onclick="addAssetToTrade('${key}','${String(r.name).replace(/'/g, "\\'")}')">Add</button>
      </div>
    `).join('');
    panel.style.display = 'block';
    mobileRosterPanelCacheKey[key] = cacheKey;
  }

  function renderMobileRosterPanels(opts = {}) {
    ['A', 'B', 'C'].forEach(side => renderMobileRosterPanel(side, opts));
  }

  function mirrorSelectOptions(sourceId, targetId) {
    const src = document.getElementById(sourceId);
    const dst = document.getElementById(targetId);
    if (!src || !dst) return;
    const sig = Array.from(src.options).map(o => `${o.value}::${o.textContent}`).join('|');
    if (dst.dataset.optionsSig !== sig) {
      dst.innerHTML = '';
      Array.from(src.options).forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = o.textContent;
        dst.appendChild(opt);
      });
      dst.dataset.optionsSig = sig;
    }
    dst.value = src.value || '';
  }

  function isElementActuallyVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function getMobileKtcImportInputs() {
    return [
      document.getElementById('mobileKtcImportUrl'),
      document.getElementById('mobileKtcImportUrlQuick'),
    ].filter(Boolean);
  }

  function getMobileKtcImportRawValue() {
    const desktopUrl = document.getElementById('ktcImportUrl');
    const mobileInputs = getMobileKtcImportInputs();
    const visibleInputs = mobileInputs.filter(el => isElementActuallyVisible(el));
    for (const el of visibleInputs) {
      const v = String(el?.value || '').trim();
      if (v) return v;
    }
    for (const el of mobileInputs) {
      const v = String(el?.value || '').trim();
      if (v) return v;
    }
    return String(desktopUrl?.value || '').trim();
  }

  function setMobileKtcImportFeedback(message, tone = '') {
    const el = document.getElementById('mobileKtcImportFeedback');
    if (!el) return;
    el.className = `mobile-ktc-import-feedback${tone ? ` ${tone}` : ''}`;
    el.textContent = String(message || '');
  }

  function setMobileKtcImportLoading(isLoading) {
    const on = !!isLoading;
    const buttons = [
      document.getElementById('mobileKtcImportBtn'),
      document.getElementById('mobileKtcImportBtnQuick'),
    ].filter(Boolean);
    buttons.forEach(btn => {
      btn.disabled = on;
      btn.textContent = on ? 'Importing…' : 'Import KTC';
      btn.style.opacity = on ? '0.7' : '';
      btn.style.pointerEvents = on ? 'none' : '';
    });
  }

  function syncMobileKtcImportVisibility() {
    const quickBar = document.getElementById('mobileKtcImportBar');
    const controls = document.getElementById('mobileTradeControls');
    const controlsInput = document.getElementById('mobileKtcImportUrl');
    if (!quickBar) return;

    const controlsVisible = isElementActuallyVisible(controls) && isElementActuallyVisible(controlsInput);
    quickBar.style.display = controlsVisible ? 'none' : '';
  }

  function focusMobileKtcImportInput(opts = {}) {
    syncMobileKtcImportVisibility();
    const mobileInputs = getMobileKtcImportInputs();
    let target = mobileInputs.find(el => isElementActuallyVisible(el)) || mobileInputs[0] || null;
    if (!target) return;
    try {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      target.focus();
      target.select();
    } catch (_) {}
    if (!opts?.preserveFeedback) {
      setMobileKtcImportFeedback('Paste a KeepTradeCut URL, then tap Import KTC.', 'error');
    }
  }

  function syncMobileTradeControlState() {
    mirrorSelectOptions('globalMyTeam', 'mobileGlobalMyTeam');
    mirrorSelectOptions('teamFilterA', 'mobileTeamFilterA');
    mirrorSelectOptions('teamFilterB', 'mobileTeamFilterB');
    mirrorSelectOptions('teamFilterC', 'mobileTeamFilterC');

    const basis = getCalculatorValueBasis();
    const basisSelect = document.getElementById('mobileCalculatorValueBasis');
    if (basisSelect) basisSelect.value = basis;

    const desktopUrl = document.getElementById('ktcImportUrl');
    const desktopRaw = String(desktopUrl?.value || '').trim();
    getMobileKtcImportInputs().forEach(input => {
      if (!String(input.value || '').trim() && desktopRaw) input.value = desktopRaw;
    });
    if (!desktopRaw) {
      const firstMobile = getMobileKtcImportInputs().find(input => String(input?.value || '').trim());
      if (desktopUrl && firstMobile) desktopUrl.value = String(firstMobile.value || '').trim();
    }
    syncMobileKtcImportVisibility();

    const mtDesktop = document.getElementById('multiTeamToggle');
    const mtMobile = document.getElementById('mobileMultiTeamToggle');
    if (mtMobile) mtMobile.checked = !!(mtDesktop?.checked || multiTeamMode);

    const sideC = document.getElementById('mobileTradeSideCSection');
    if (sideC) sideC.style.display = (mtDesktop?.checked || multiTeamMode) ? '' : 'none';

    const analyzeBtn = document.getElementById('mobileTradeAnalyzeBtn');
    const calcTab = document.getElementById('tab-calculator');
    if (analyzeBtn && calcTab) {
      analyzeBtn.textContent = calcTab.classList.contains('mobile-analysis-open') ? 'Hide' : 'Analyze';
    }
    const impactBtn = document.getElementById('mobileTradeImpactBtn');
    const impactPanel = document.getElementById('tradeImpactPanel');
    if (impactBtn && impactPanel) {
      impactBtn.textContent = impactPanel.style.display === 'none' ? 'Impact' : 'Hide Impact';
    }
  }

  function setMobileTradeMyTeam(teamName) {
    syncGlobalTeam(String(teamName || ''));
    syncMobileTradeControlState();
    renderMobileTradeWorkspace();
  }

  function setMobileCalculatorValueBasis(mode) {
    const normalized = String(mode || 'full');
    const desktop = document.getElementById('calculatorValueBasis');
    if (desktop) desktop.value = normalized;
    handleValueBasisChange(normalized, 'calculator');
    syncMobileTradeControlState();
    renderMobileRosterPanels({ force: true });
  }

  function setMobileTeamFilter(side, value) {
    const key = String(side || '').toUpperCase();
    const desktop = document.getElementById(`teamFilter${key}`);
    if (desktop) desktop.value = String(value || '');
    updateTeamFilter();
    scheduleRecalc();
    syncMobileTradeControlState();
    renderMobileRosterPanel(key, { force: true });
  }

  function toggleMultiTeamFromMobile(on) {
    const desktop = document.getElementById('multiTeamToggle');
    if (desktop) desktop.checked = !!on;
    toggleMultiTeam(!!on);
    renderMobileTradeWorkspace();
    updateMobileTradeTray();
    if (on) renderMobileRosterPanel('C', { force: true });
  }

  function importKtcTradeFromMobile() {
    const desktopInp = document.getElementById('ktcImportUrl');
    const raw = getMobileKtcImportRawValue();
    if (!raw) {
      focusMobileKtcImportInput();
      return;
    }
    setMobileKtcImportFeedback('Importing KeepTradeCut trade…', 'loading');
    setMobileKtcImportLoading(true);
    if (desktopInp) desktopInp.value = raw;
    getMobileKtcImportInputs().forEach(input => { input.value = raw; });
    const result = importKtcTradeUrl(raw, { showAlerts: false });
    syncMobileTradeControlState();
    setMobileKtcImportLoading(false);
    if (result?.ok) {
      const importedA = Number(result.importedA || 0);
      const importedB = Number(result.importedB || 0);
      setMobileKtcImportFeedback(`Imported ${importedA} to Side A and ${importedB} to Side B.`, 'success');
    } else {
      const reason = String(result?.error || 'Could not import that KeepTradeCut URL.');
      setMobileKtcImportFeedback(reason, 'error');
      focusMobileKtcImportInput({ preserveFeedback: true });
    }
  }

  const mobileTradeEditorState = {
    side: 'A',
    rowIndex: -1,
  };

  function getTradeTbodyIdForSide(side) {
    const key = String(side || '').toUpperCase();
    return key === 'A' ? 'sideABody' : key === 'B' ? 'sideBBody' : 'sideCBody';
  }

  function getTradeRowByIndex(side, rowIndex) {
    const tbody = document.getElementById(getTradeTbodyIdForSide(side));
    if (!tbody) return null;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    if (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= rows.length) return null;
    return rows[rowIndex];
  }

  function getFirstEmptyTradeRowIndex(side) {
    const tbody = document.getElementById(getTradeTbodyIdForSide(side));
    if (!tbody) return -1;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    return rows.findIndex((row) => !String(row.querySelector('.player-name-input')?.value || '').trim());
  }

  function closeMobileTradeRowEditor() {
    const overlay = document.getElementById('mobileTradeEditorOverlay');
    if (!overlay) return;
    overlay.classList.remove('active');
  }

  function openMobileTradeRowEditor(side, rowIndex, opts = {}) {
    const key = String(side || '').toUpperCase();
    const overlay = document.getElementById('mobileTradeEditorOverlay');
    const title = document.getElementById('mobileTradeEditorTitle');
    const nameInput = document.getElementById('mobileTradeEditorName');
    const siteGrid = document.getElementById('mobileTradeEditorSiteGrid');
    const status = document.getElementById('mobileTradeEditorStatus');
    const removeBtn = document.getElementById('mobileTradeEditorRemoveBtn');
    if (!overlay || !nameInput || !siteGrid || !status) return;

    let resolvedIndex = Number.isInteger(rowIndex) ? rowIndex : -1;
    let row = getTradeRowByIndex(key, resolvedIndex);
    if (!row) {
      const tbodyId = getTradeTbodyIdForSide(key);
      const created = addPlayerRow(key, tbodyId);
      if (created) {
        const rows = Array.from(document.getElementById(tbodyId)?.querySelectorAll('tr') || []);
        resolvedIndex = rows.indexOf(created);
        row = created;
      }
    }
    if (!row) return;

    mobileTradeEditorState.side = key;
    mobileTradeEditorState.rowIndex = resolvedIndex;

    const rowName = String(row.querySelector('.player-name-input')?.value || '').trim();
    nameInput.value = rowName;

    const siteInputs = new Map();
    row.querySelectorAll('.site-input').forEach((inp) => siteInputs.set(inp.dataset.siteKey, inp));
    const cfg = getSiteConfig();
    siteGrid.innerHTML = cfg.map((sc) => {
      const rowInp = siteInputs.get(sc.key);
      const value = String(rowInp?.value ?? '').trim();
      const preview = rowInp?.parentElement?.querySelector('.auto-pill')?.textContent || '';
      const cardClass = sc.include ? 'mobile-trade-editor-site-card' : 'mobile-trade-editor-site-card excluded';
      const mode = String(sc.mode || 'value').toUpperCase();
      const previewText = preview ? String(preview) : 'manual';
      return `
        <label class="${cardClass}">
          <span class="site-head">
            <span>${sc.label}</span>
            <span>${mode} · ${previewText}</span>
          </span>
          <input
            type="number"
            step="1"
            inputmode="numeric"
            data-site-key="${sc.key}"
            placeholder="${mode.includes('RANK') ? 'Rank' : 'Value'}"
            value="${value.replace(/"/g, '&quot;')}"
          >
        </label>
      `;
    }).join('');

    if (title) title.textContent = `Side ${key} · Row ${resolvedIndex + 1}`;
    if (removeBtn) removeBtn.disabled = false;
    const pickInfo = rowName ? parsePickToken(rowName) : null;
    status.textContent = pickInfo
      ? `Pick token detected (${pickInfo.kind === 'slot' ? `${pickInfo.round}.${String(pickInfo.slot || '').padStart(2, '0')}` : `${pickInfo.tier} ${pickInfo.round}`}).`
      : (rowName ? 'Edit site values or run autofill from loaded data.' : 'Set a player/pick token, then apply.');

    overlay.classList.add('active');
    if (opts.focusName !== false) {
      setTimeout(() => {
        try {
          nameInput.focus();
          nameInput.select();
        } catch (_) {}
      }, 40);
    }
  }

  function openMobileTradeRowEditorForSide(side) {
    const key = String(side || '').toUpperCase();
    let rowIndex = getFirstEmptyTradeRowIndex(key);
    if (rowIndex < 0) {
      const tbodyId = getTradeTbodyIdForSide(key);
      const created = addPlayerRow(key, tbodyId);
      if (created) {
        const rows = Array.from(document.getElementById(tbodyId)?.querySelectorAll('tr') || []);
        rowIndex = rows.indexOf(created);
      }
    }
    if (rowIndex >= 0) openMobileTradeRowEditor(key, rowIndex);
  }

  function removeMobileTradeChip(side, rowIndex, name) {
    removeAssetFromTrade(side, name, rowIndex);
    renderMobileTradeWorkspace();
    updateMobileTradeTray();
  }

  function openGlobalSearchFromTradeEditor() {
    const side = String(mobileTradeEditorState.side || 'B').toUpperCase();
    closeMobileTradeRowEditor();
    openGlobalSearchForTrade(side);
  }

  function applyMobileTradeRowEditor(opts = {}) {
    const side = String(mobileTradeEditorState.side || '').toUpperCase();
    const rowIndex = Number(mobileTradeEditorState.rowIndex);
    const row = getTradeRowByIndex(side, rowIndex);
    if (!row) {
      closeMobileTradeRowEditor();
      return;
    }
    const nameInput = document.getElementById('mobileTradeEditorName');
    const siteGrid = document.getElementById('mobileTradeEditorSiteGrid');
    const status = document.getElementById('mobileTradeEditorStatus');
    if (!nameInput || !siteGrid) return;

    const editedName = String(nameInput.value || '').trim();
    const targetNameInput = row.querySelector('.player-name-input');
    if (targetNameInput) {
      targetNameInput.value = editedName;
      targetNameInput.dispatchEvent(new Event('input', { bubbles: true }));
      updatePickStatus(row, editedName);
    }

    siteGrid.querySelectorAll('input[data-site-key]').forEach((editorInput) => {
      const key = editorInput.dataset.siteKey;
      const target = row.querySelector(`.site-input[data-site-key="${key}"]`);
      if (!target) return;
      target.value = String(editorInput.value || '').trim();
      target.dispatchEvent(new Event('input', { bubbles: true }));
    });

    if (opts.autofill && editedName && loadedData) {
      autoFillRow(row);
      if (status) status.textContent = 'Autofill applied from current values.';
    }

    scheduleRecalc();
    renderMobileTradeWorkspace();
    updateMobileTradeTray();

    if (opts.keepOpen) {
      setTimeout(() => openMobileTradeRowEditor(side, rowIndex, { focusName: false }), 0);
      return;
    }
    closeMobileTradeRowEditor();
  }

  function autofillMobileTradeRowEditor() {
    applyMobileTradeRowEditor({ autofill: true, keepOpen: true });
  }

  function removeMobileTradeRowFromEditor() {
    const side = String(mobileTradeEditorState.side || '').toUpperCase();
    const rowIndex = Number(mobileTradeEditorState.rowIndex);
    const tbodyId = getTradeTbodyIdForSide(side);
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    if (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= rows.length) return;
    const row = rows[rowIndex];

    if (rows.length <= 1) {
      row.querySelectorAll('input').forEach((input) => { input.value = ''; });
      const su = row.querySelector('.sites-used'); if (su) su.textContent = '';
      const mv = row.querySelector('.meta-value'); if (mv) mv.innerHTML = '';
      row.querySelectorAll('.auto-pill').forEach((pill) => { pill.textContent = ''; });
      row.dataset.sleeperId = '';
    } else {
      row.remove();
    }

    scheduleRecalc();
    closeMobileTradeRowEditor();
    renderMobileTradeWorkspace();
    updateMobileTradeTray();
  }

  function addMobileTradeRow(side) {
    openMobileTradeRowEditorForSide(side);
  }

  function loadSavedTradeFromMobile(idx) {
    const desktopSel = document.getElementById('savedTradesSelect');
    if (desktopSel) desktopSel.value = String(idx ?? '');
    loadSavedTrade(idx);
  }

  function deleteSavedTradeFromMobile() {
    const mobileSel = document.getElementById('mobileSavedTradesSelect');
    const desktopSel = document.getElementById('savedTradesSelect');
    const idx = String(mobileSel?.value || '');
    if (desktopSel) desktopSel.value = idx;
    deleteSavedTrade();
  }

  function renderMobileTradeWorkspace() {
    const sideA = getTradeSideAssets('A', { includeRowIndex: true });
    const sideB = getTradeSideAssets('B', { includeRowIndex: true });
    const sideC = getTradeSideAssets('C', { includeRowIndex: true });
    const wrapA = document.getElementById('mobileTradeSideA');
    const wrapB = document.getElementById('mobileTradeSideB');
    const wrapC = document.getElementById('mobileTradeSideC');
    const sideCSection = document.getElementById('mobileTradeSideCSection');
    if (!wrapA || !wrapB) return;

    function renderChipList(rows, side) {
      if (!rows.length) {
        return `
          <div class="trade-empty-state">
            <span class="title">No assets yet</span>
            Start with search, import, or roster picks.
            <div class="actions">
              <button class="mobile-chip-btn primary" onclick="openGlobalSearchForTrade('${side}')">Add Asset</button>
              <button class="mobile-chip-btn" onclick="openMobileTradeRowEditorForSide('${side}')">Manual Row</button>
              ${side === 'B' ? '<button class="mobile-chip-btn" onclick="importKtcTradeFromMobile()">Import KTC</button>' : ''}
              <button class="mobile-chip-btn" onclick="showOnboarding()">Choose Team</button>
            </div>
          </div>
        `;
      }
      return rows.map(r => `
        <span class="trade-chip">
          <span class="chip-name">${r.name}</span>
          <span style="font-family:var(--mono);color:var(--subtext);">${r.meta > 0 ? r.meta.toLocaleString() : '—'}</span>
          <button class="chip-edit-btn" aria-label="Edit ${r.name}" onclick="openMobileTradeRowEditor('${side}', ${Number.isInteger(r.rowIndex) ? r.rowIndex : -1})">Edit</button>
          <button class="chip-remove-btn" aria-label="Remove ${r.name}" onclick="removeMobileTradeChip('${side}', ${Number.isInteger(r.rowIndex) ? r.rowIndex : -1}, '${String(r.name).replace(/'/g, "\\'")}')">&times;</button>
        </span>
      `).join('');
    }

    wrapA.innerHTML = renderChipList(sideA, 'A');
    wrapB.innerHTML = renderChipList(sideB, 'B');
    if (wrapC) wrapC.innerHTML = renderChipList(sideC, 'C');
    if (sideCSection) sideCSection.style.display = multiTeamMode ? '' : 'none';
    syncMobileTradeControlState();
    renderMobileRosterPanels();
    updateCalculatorEmptyHint();
    syncMobilePowerModeControls();
  }

  function toggleTradeAnalysisMobile() {
    const tab = document.getElementById('tab-calculator');
    const card = document.getElementById('tradeAnalysisCard');
    if (!card || !tab) return;
    const opening = !tab.classList.contains('mobile-analysis-open');
    tab.classList.toggle('mobile-analysis-open', opening);
    card.style.display = opening ? '' : 'none';
    const btn = document.getElementById('mobileTradeAnalyzeBtn');
    if (btn) btn.textContent = opening ? 'Hide' : 'Analyze';
  }

  function toggleTradeImpactMobile() {
    const panel = document.getElementById('tradeImpactPanel');
    if (!panel) return;
    const opening = panel.style.display === 'none';
    panel.style.display = opening ? '' : 'none';
    const btn = document.getElementById('mobileTradeImpactBtn');
    if (btn) btn.textContent = opening ? 'Hide Impact' : 'Impact';
  }

  function updateMobileTradeTray() {
    const verdictEl = document.getElementById('mobileTradeVerdict');
    const kpisEl = document.getElementById('mobileTradeKpis');
    if (!verdictEl || !kpisEl) return;
    const tA = String(document.getElementById('totalA')?.textContent || '—').trim();
    const tB = String(document.getElementById('totalB')?.textContent || '—').trim();
    const diff = String(document.getElementById('valueAdjustment')?.textContent || '—').trim();
    const verdict = String(document.getElementById('decision')?.textContent || 'Near even').trim();
    verdictEl.textContent = verdict || 'Near even';
    if (multiTeamMode) {
      const tC = String(document.getElementById('totalC')?.textContent || '—').trim();
      kpisEl.textContent = `A ${tA} · B ${tB} · C ${tC}`;
    } else {
      kpisEl.textContent = `A ${tA} · B ${tB} · Gap ${diff}`;
    }
  }

  function serializeTradeDraft() {
    const payload = {
      updatedAt: new Date().toISOString(),
      sideA: getTradeSideAssets('A').map(x => x.name),
      sideB: getTradeSideAssets('B').map(x => x.name),
      sideC: getTradeSideAssets('C').map(x => x.name),
      teamA: document.getElementById('teamFilterA')?.value || '',
      teamB: document.getElementById('teamFilterB')?.value || '',
      teamC: document.getElementById('teamFilterC')?.value || '',
      multiTeam: !!document.getElementById('multiTeamToggle')?.checked,
    };
    return payload;
  }

  function saveTradeDraftState() {
    const draft = serializeTradeDraft();
    const hasAssets = draft.sideA.length || draft.sideB.length || draft.sideC.length;
    if (!hasAssets) {
      try { localStorage.removeItem(TRADE_DRAFT_KEY); } catch(_) {}
      return;
    }
    writeJsonStore(TRADE_DRAFT_KEY, draft);
  }

  function loadTradeDraftState() {
    const d = readJsonStore(TRADE_DRAFT_KEY, null);
    if (!d) return false;
    if (!Array.isArray(d.sideA) && !Array.isArray(d.sideB)) return false;
    populateTradeSide('sideABody', 'A', Array.isArray(d.sideA) ? d.sideA : []);
    populateTradeSide('sideBBody', 'B', Array.isArray(d.sideB) ? d.sideB : []);
    if (Array.isArray(d.sideC) && d.sideC.length) {
      const mt = document.getElementById('multiTeamToggle');
      if (mt && !mt.checked) {
        mt.checked = true;
        toggleMultiTeam(true);
      }
      populateTradeSide('sideCBody', 'C', d.sideC);
    }
    if (d.teamA) {
      const el = document.getElementById('teamFilterA');
      if (el) el.value = d.teamA;
    }
    if (d.teamB) {
      const el = document.getElementById('teamFilterB');
      if (el) el.value = d.teamB;
    }
    if (d.teamC) {
      const el = document.getElementById('teamFilterC');
      if (el) el.value = d.teamC;
    }
    updateTeamFilter();
    recalculate();
    return true;
  }

  function getCanonicalPlayerName(name) {
    if (!name || !loadedData?.players) return null;
    const canonical = resolveCanonicalPlayerName(name);
    return canonical || null;
  }

  function getPlayerNameBySleeperId(sleeperId) {
    const sid = String(sleeperId || '').trim();
    if (!sid) return null;
    if (sleeperIdToPlayer[sid]) return sleeperIdToPlayer[sid];
    if (loadedData?.sleeper?.idToPlayer && loadedData.sleeper.idToPlayer[sid]) {
      return loadedData.sleeper.idToPlayer[sid];
    }
    return null;
  }

  function getSleeperIdForName(name) {
    if (!name) return null;
    const canonical = getCanonicalPlayerName(name);
    if (canonical && playerSleeperIds[canonical]) return String(playerSleeperIds[canonical]);
    if (canonical && loadedData?.sleeper?.playerIds?.[canonical]) {
      return String(loadedData.sleeper.playerIds[canonical]);
    }
    const norm = normalizeForLookup(name);
    for (const [pn, sid] of Object.entries(playerSleeperIds)) {
      if (normalizeForLookup(pn) === norm && sid != null && sid !== '') return String(sid);
    }
    if (loadedData?.sleeper?.playerIds) {
      for (const [pn, sid] of Object.entries(loadedData.sleeper.playerIds)) {
        if (normalizeForLookup(pn) === norm && sid != null && sid !== '') return String(sid);
      }
    }
    return null;
  }

  function lookupPlayer(name) {
    if (!loadedData || !loadedData.players) return null;
    if (loadedData.players[name]) return loadedData.players[name];
    const targetPosHint = getPlayerPosition(name);
    const idMatch = String(name || '').trim();
    if (/^\d+$/.test(idMatch)) {
      const byId = getPlayerNameBySleeperId(idMatch);
      if (byId && loadedData.players[byId]) return loadedData.players[byId];
    }
    const norm = normalizeForLookup(name);
    for (const [pn, vals] of Object.entries(loadedData.players)) {
      if (normalizeForLookup(pn) === norm) return vals;
    }
    const parts = normalizeForLookup(name).split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      const last = parts[parts.length - 1].toLowerCase();
      const firstInit = parts[0][0].toLowerCase();
      const middle = parts.length > 2 ? parts.slice(1, -1).join(' ') : '';
      for (const [pn, vals] of Object.entries(loadedData.players)) {
        const pp = normalizeForLookup(pn).split(/\s+/).filter(Boolean);
        if (!pp.length) continue;
        if (pp.length >= 2 &&
            pp[pp.length-1].toLowerCase() === last &&
            pp[0][0].toLowerCase() === firstInit) {
          // Guard against collapsing distinct players with shared first initial + last token
          // (e.g., "Josh Allen" vs "Josh Hines-Allen").
          if (middle) {
            const candMiddle = pp.length > 2 ? pp.slice(1, -1).join(' ') : '';
            if (candMiddle !== middle) continue;
          }
          // Position safety guard: do not resolve across incompatible positions.
          if (targetPosHint) {
            const candPos = getPlayerPosition(pn);
            if (candPos && candPos !== targetPosHint) continue;
          }
          return vals;
        }
      }
    }
    return null;
  }

  function autoFillRow(row) {
    const nameInp = row.querySelector('.player-name-input');
    if (!nameInp) return;
    const name = nameInp.value.trim();
    if (!name || !loadedData) {
      row.dataset.sleeperId = '';
      return;
    }

    const pickInfo = parsePickToken(name);
    let data = null;

    if (pickInfo) {
      data = resolvePickSiteValues(pickInfo);
    } else {
      data = lookupPlayer(name);
    }
    if (!data) return;

    const siteInps = row.querySelectorAll('.site-input');
    let filled = 0;
    siteInps.forEach(inp => {
      const key = inp.dataset.siteKey;
      if (data[key] != null) {
        inp.value = data[key];
        filled++;
      }
    });

    if (filled > 0) {
      nameInp.style.borderColor = 'var(--green)';
      setTimeout(() => { nameInp.style.borderColor = ''; }, 1500);
    }

    row.dataset.sleeperId = pickInfo ? '' : (getSleeperIdForName(name) || '');
  }

  function decodeUrlValue(raw) {
    let out = String(raw ?? '');
    for (let i = 0; i < 3; i++) {
      try {
        const next = decodeURIComponent(out);
        if (next === out) break;
        out = next;
      } catch (_) {
        break;
      }
    }
    return out;
  }

  function parseLooseObject(raw) {
    if (raw == null) return null;
    if (typeof raw !== 'string') return raw;
    const text = raw.trim();
    if (!text) return '';
    try { return JSON.parse(text); } catch (_) {}
    if (!((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']')))) {
      return text;
    }
    const relaxed = text
      .replace(/\bNone\b/g, 'null')
      .replace(/\bTrue\b/g, 'true')
      .replace(/\bFalse\b/g, 'false')
      .replace(/([{,]\s*)'([^'\\]*(?:\\.[^'\\]*)*)'\s*:/g, '$1"$2":')
      .replace(/:\s*'([^'\\]*(?:\\.[^'\\]*)*)'(\s*[,}])/g, ': "$1"$2')
      .replace(/,\s*'([^'\\]*(?:\\.[^'\\]*)*)'(?=\s*[,}\]])/g, ', "$1"');
    try { return JSON.parse(relaxed); } catch (_) {}
    return text;
  }

  function extractKtcAssets(raw) {
    const val = parseLooseObject(raw);
    if (val == null || val === '') return [];
    if (Array.isArray(val)) {
      return val.flatMap(extractKtcAssets);
    }
    if (typeof val === 'number') return [String(Math.trunc(val))];
    if (typeof val === 'string') {
      const s = decodeUrlValue(val).trim();
      if (!s) return [];
      const parsed = parseLooseObject(s);
      if (parsed !== s && typeof parsed !== 'string') return extractKtcAssets(parsed);
      // KTC calculator URLs often encode sides as delimited strings:
      // teamOne=1550|1766|1587...
      if (/[|,;]/.test(s)) {
        return s
          .split(/[|,;]/)
          .map(t => t.trim())
          .filter(Boolean)
          .flatMap(extractKtcAssets);
      }
      return [s];
    }
    if (typeof val !== 'object') return [];

    // Draft-pick object support (season/round/slot or tier pick objects).
    const season = val.season ?? val.year ?? val.pickYear ?? val.draftYear;
    const round = val.round ?? val.rd ?? val.pickRound ?? val.roundNo;
    const slot = val.pick_no ?? val.pick ?? val.slot ?? val.pickNumber ?? val.overall;
    const tier = String(val.tier ?? val.pickTier ?? val.range ?? '').trim().toLowerCase();
    const typeHint = String(val.assetType ?? val.type ?? val.position ?? val.pos ?? '').trim().toLowerCase();
    const pickLike = ['pick', 'draft_pick', 'future_pick'].includes(typeHint) || !!val.isPick || !!val.is_pick;
    if (season && round && slot && isFinite(Number(slot))) {
      return [`${season} Pick ${round}.${String(slot).padStart(2, '0')}`];
    }
    if (season && round && /^(early|mid|late)$/.test(tier)) {
      return [`${season} ${tier} ${round}`];
    }
    for (const k of ['pickLabel', 'pick_name', 'pickName', 'draft_pick', 'draftPick', 'label', 'assetLabel', 'displayName']) {
      if (val[k] != null) {
        const pickLabel = String(val[k]).trim();
        if (pickLike || parsePickToken(pickLabel)) return [pickLabel];
      }
    }

    for (const key of ['playerIds', 'playerID', 'playerId', 'players', 'assets', 'items', 'ids']) {
      if (val[key] != null) return extractKtcAssets(val[key]);
    }
    for (const key of ['teamOne', 'team1', 'sideA', 'side1', 'teamTwo', 'team2', 'sideB', 'side2']) {
      if (val[key] != null) return extractKtcAssets(val[key]);
    }
    if (pickLike && val.id != null) return [String(val.id)];
    for (const key of ['name', 'playerName', 'player']) {
      if (val[key] != null) return [String(val[key])];
    }
    return [];
  }

  function canonicalizeImportedAsset(asset) {
    if (asset == null) return null;
    let token = decodeUrlValue(String(asset)).trim();
    if (!token) return null;
    token = token.replace(/^['"]+|['"]+$/g, '').trim();
    token = token
      .replace(/\+/g, ' ')
      .replace(/_+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    if (!token) return null;

    function pickOrdinalSuffix(n) {
      const x = Number(n) || 0;
      if (x % 100 >= 11 && x % 100 <= 13) return 'th';
      if (x % 10 === 1) return 'st';
      if (x % 10 === 2) return 'nd';
      if (x % 10 === 3) return 'rd';
      return 'th';
    }

    function canonicalizePickToken(rawPick) {
      const parsed = parsePickToken(rawPick);
      if (!parsed) return null;
      if (parsed.kind === 'slot') {
        const year = Number.isFinite(parsed.year)
          ? parsed.year
          : (parseInt(document.getElementById('pickCurrentYear')?.value) || 2026);
        return `${year} Pick ${parsed.round}.${String(parsed.slot).padStart(2, '0')}`.trim();
      }
      const year = Number.isFinite(parsed.year)
        ? parsed.year
        : (parseInt(document.getElementById('pickCurrentYear')?.value) || 2026);
      const tier = String(parsed.tier || 'mid').toLowerCase();
      const tierLabel = tier.charAt(0).toUpperCase() + tier.slice(1);
      return `${year} ${tierLabel} ${parsed.round}${pickOrdinalSuffix(parsed.round)}`;
    }

    function inferKtcPickLabelById(rawId) {
      const id = parseInt(String(rawId), 10);
      if (!Number.isFinite(id)) return null;
      const tierIdx = { early: 0, mid: 1, late: 2 };
      const idxTier = ['early', 'mid', 'late'];
      const yearBaseVotes = {};
      const slotYearBaseVotes = {};

      for (const [k, label] of Object.entries(ktcIdToPlayer || {})) {
        const pick = parsePickToken(label);
        const kid = parseInt(String(k), 10);
        if (!Number.isFinite(kid)) continue;
        if (!pick || !Number.isFinite(Number(pick.year))) continue;
        const y = Number(pick.year);

        if (pick.kind === 'slot') {
          const rnd = Number(pick.round);
          const slot = Number(pick.slot);
          if (!Number.isFinite(rnd) || !Number.isFinite(slot)) continue;
          const idx = ((rnd - 1) * 12) + (slot - 1);
          if (idx < 0 || idx > 71) continue;
          const base = kid - idx;
          if (!slotYearBaseVotes[y]) slotYearBaseVotes[y] = {};
          slotYearBaseVotes[y][base] = (slotYearBaseVotes[y][base] || 0) + 1;
          continue;
        }

        if (pick.kind === 'tier') {
          const tier = String(pick.tier || '').toLowerCase();
          if (!(tier in tierIdx)) continue;
          const idx = ((Number(pick.round) - 1) * 3) + tierIdx[tier];
          if (idx < 0 || idx > 17) continue;
          const base = kid - idx;
          if (!yearBaseVotes[y]) yearBaseVotes[y] = {};
          yearBaseVotes[y][base] = (yearBaseVotes[y][base] || 0) + 1;
        }
      }

      for (const [yearStr, votes] of Object.entries(slotYearBaseVotes)) {
        const year = Number(yearStr);
        let bestBase = null;
        let bestCnt = 0;
        for (const [bStr, cnt] of Object.entries(votes)) {
          if (cnt > bestCnt) {
            bestCnt = cnt;
            bestBase = Number(bStr);
          }
        }
        // Require multiple anchors to avoid false mapping from sparse noise.
        if (!Number.isFinite(bestBase) || bestCnt < 3) continue;
        const idx = id - bestBase;
        if (idx < 0 || idx > 71) continue;
        const round = Math.floor(idx / 12) + 1;
        const slot = (idx % 12) + 1;
        return `${year} Pick ${round}.${String(slot).padStart(2, '0')}`;
      }

      for (const [yearStr, votes] of Object.entries(yearBaseVotes)) {
        const year = Number(yearStr);
        let bestBase = null;
        let bestCnt = 0;
        for (const [bStr, cnt] of Object.entries(votes)) {
          if (cnt > bestCnt) {
            bestCnt = cnt;
            bestBase = Number(bStr);
          }
        }
        if (!Number.isFinite(bestBase) || bestCnt < 3) continue;
        const idx = id - bestBase;
        if (idx < 0 || idx > 17) continue;
        const round = Math.floor(idx / 3) + 1;
        const tier = idxTier[idx % 3] || 'mid';
        const tierLabel = tier.charAt(0).toUpperCase() + tier.slice(1);
        return `${year} ${tierLabel} ${round}${pickOrdinalSuffix(round)}`;
      }
      return null;
    }

    if (/^-?\d+$/.test(token)) {
      const normalizedId = token.replace(/^-/, '');
      const mapped = ktcIdToPlayer[normalizedId] || ktcIdToPlayer[token];
      if (mapped) {
        const pickMapped = canonicalizePickToken(mapped);
        if (pickMapped) return pickMapped;
        const canonicalMapped = getCanonicalPlayerName(String(mapped));
        if (canonicalMapped) return canonicalMapped;
        return String(mapped);
      }
      const fromSleeperId = getPlayerNameBySleeperId(token);
      if (fromSleeperId) return fromSleeperId;
      const inferredPick = inferKtcPickLabelById(normalizedId);
      if (inferredPick) return inferredPick;
      return null;
    }

    // Normalize common pick labels ("2027 Round 1", "2027 1st").
    token = token.replace(/\bROUND\b/gi, 'Pick').replace(/\s+/g, ' ').trim();
    const canonicalPick = canonicalizePickToken(token);
    if (canonicalPick) return canonicalPick;

    const canonical = getCanonicalPlayerName(token);
    if (canonical) return canonical;
    return null;
  }

  function populateTradeSide(tbodyId, side, assets) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    tbody.innerHTML = '';
    const fill = assets.slice(0, MAX_PLAYERS);
    const rowCount = Math.max(fill.length + 1, 1);
    for (let i = 0; i < rowCount; i++) addPlayerRow(side, tbodyId);
    const rows = tbody.querySelectorAll('tr');
    fill.forEach((name, idx) => {
      const row = rows[idx];
      if (!row) return;
      const inp = row.querySelector('.player-name-input');
      if (!inp) return;
      inp.value = name;
      autoFillRow(row);
    });
  }

  function importKtcTradeUrl(rawOverride = null, opts = {}) {
    const showAlerts = opts?.showAlerts !== false;
    const inp = document.getElementById('ktcImportUrl');
    const raw = String(rawOverride ?? inp?.value ?? '').trim();

    const fail = (message) => {
      const msg = String(message || 'KTC import failed.');
      if (showAlerts) alert(msg);
      return { ok: false, error: msg };
    };

    if (!raw) return { ok: false, error: 'Paste a KeepTradeCut trade URL first.' };
    if (!loadedData?.players) {
      return fail('Load values first, then import the KTC URL.');
    }

    let u;
    try { u = new URL(raw); } catch (_) {
      return fail('That does not look like a valid URL.');
    }
    if (!/keeptradecut\.com$/i.test(u.hostname)) {
      return fail('Please paste a KeepTradeCut trade URL.');
    }

    const params = new URLSearchParams(u.search || '');
    const hash = (u.hash || '').replace(/^#/, '');
    if (hash.includes('=')) {
      const hp = new URLSearchParams(hash);
      hp.forEach((v, k) => params.append(k, v));
    }

    const unresolved = [];
    function sideFrom(value) {
      const out = [];
      for (const rawAsset of extractKtcAssets(value)) {
        const canon = canonicalizeImportedAsset(rawAsset);
        if (canon) out.push(canon);
        else if (rawAsset != null && String(rawAsset).trim()) unresolved.push(String(rawAsset).trim());
      }
      return out;
    }

    const pairs = [
      ['teamOne', 'teamTwo'],
      ['team1', 'team2'],
      ['sideA', 'sideB'],
      ['side1', 'side2'],
      ['teamOneAssets', 'teamTwoAssets'],
      ['teamA', 'teamB'],
    ];
    let sideA = [];
    let sideB = [];

    for (const [aKey, bKey] of pairs) {
      if (!params.has(aKey) || !params.has(bKey)) continue;
      sideA = sideFrom(params.get(aKey));
      sideB = sideFrom(params.get(bKey));
      if (sideA.length || sideB.length) break;
    }

    // Fallback: parse any object-like payload in query/hash values.
    if (!sideA.length && !sideB.length) {
      for (const [k, v] of params.entries()) {
        const parsed = parseLooseObject(decodeUrlValue(v));
        if (!parsed || typeof parsed !== 'object') continue;
        const aRaw = parsed.teamOne ?? parsed.team1 ?? parsed.sideA ?? parsed.side1;
        const bRaw = parsed.teamTwo ?? parsed.team2 ?? parsed.sideB ?? parsed.side2;
        if (aRaw != null && bRaw != null) {
          sideA = sideFrom(aRaw);
          sideB = sideFrom(bRaw);
          if (sideA.length || sideB.length) break;
        }
      }
    }

    // Fallback: hash payloads can be JSON/object-like without key=value fragments.
    if (!sideA.length && !sideB.length && hash && !hash.includes('=')) {
      const parsedHash = parseLooseObject(decodeUrlValue(hash));
      if (parsedHash && typeof parsedHash === 'object') {
        const aRaw = parsedHash.teamOne ?? parsedHash.team1 ?? parsedHash.sideA ?? parsedHash.side1 ?? parsedHash.teamA;
        const bRaw = parsedHash.teamTwo ?? parsedHash.team2 ?? parsedHash.sideB ?? parsedHash.side2 ?? parsedHash.teamB;
        if (aRaw != null && bRaw != null) {
          sideA = sideFrom(aRaw);
          sideB = sideFrom(bRaw);
        }
      }
    }

    if (!sideA.length && !sideB.length) {
      return fail('Could not parse trade assets from that KTC URL.');
    }

    if (unresolved.length) {
      const preview = [...new Set(unresolved)].slice(0, 12);
      console.warn(`[KTC Import] Unresolved assets (${unresolved.length}):`, preview);
    }

    switchTab('calculator');
    populateTradeSide('sideABody', 'A', sideA);
    populateTradeSide('sideBBody', 'B', sideB);
    recalculate();

    if (inp) {
      inp.style.borderColor = 'var(--green)';
      setTimeout(() => { inp.style.borderColor = ''; }, 1200);
    }
    const mobileInputs = [
      document.getElementById('mobileKtcImportUrl'),
      document.getElementById('mobileKtcImportUrlQuick'),
    ].filter(Boolean);
    mobileInputs.forEach((mobileInp) => {
      mobileInp.value = raw;
      mobileInp.style.borderColor = 'var(--green)';
      setTimeout(() => { mobileInp.style.borderColor = ''; }, 1200);
    });
    syncMobileTradeControlState();
    return {
      ok: true,
      importedA: sideA.length,
      importedB: sideB.length,
      unresolved: unresolved.length,
    };
  }

  // Autocomplete dropdown
  function showAutocomplete(input, query) {
    hideAutocomplete();
    if (!loadedData || query.length < 2) return;

    const row = input.closest('tr');
    const tbody = row ? row.closest('tbody') : null;
    const tbodyId = tbody ? tbody.id : '';
    const teamFilter = tbodyId === 'sideABody' ? teamFilterA
                      : tbodyId === 'sideBBody' ? teamFilterB
                      : tbodyId === 'sideCBody' ? teamFilterC
                      : '';
    const teamSet = getTeamPlayers(teamFilter);

    const norm = query.toLowerCase();
    let pool = playerNames;

    let matches;
    if (teamSet) {
      const teamMatches = pool.filter(n => n.toLowerCase().includes(norm) && teamSet.has(n.toLowerCase()));
      const otherMatches = pool.filter(n => n.toLowerCase().includes(norm) && !teamSet.has(n.toLowerCase()));
      matches = [...teamMatches.slice(0, 6), ...otherMatches.slice(0, 2)];
    } else {
      matches = pool.filter(n => n.toLowerCase().includes(norm)).slice(0, 8);
    }
    if (!matches.length) return;

    const dropdown = document.createElement('div');
    dropdown.className = 'autocomplete-dropdown';
    dropdown.id = 'acDropdown';

    matches.forEach((name, idx) => {
      const item = document.createElement('div');
      item.className = 'ac-item';
      if (idx === 0) item.classList.add('ac-active');

      // [NEW] Position badge in autocomplete
      const pos = getPlayerPosition(name);
      const isTeamPlayer = teamSet && teamSet.has(name.toLowerCase());

      if (isTeamPlayer) {
        const star = document.createElement('span');
        star.className = 'ac-team-star';
        star.textContent = '★';
        item.appendChild(star);
      }

      if (pos) {
        const posBadge = document.createElement('span');
        posBadge.className = 'ac-pos';
        posBadge.setAttribute('style', getPosStyle(pos));
        posBadge.textContent = pos;
        item.appendChild(posBadge);
      }

      const nameSpan = document.createElement('span');
      nameSpan.textContent = name;
      item.appendChild(nameSpan);

      // [FIX] Store clean name as data attribute — prevents ★ prefix bug
      item.dataset.playerName = name;

      item.addEventListener('mousedown', (e) => {
        e.preventDefault();
        input.value = e.currentTarget.dataset.playerName;
        hideAutocomplete();
        const row = input.closest('tr');
        if (row) { autoFillRow(row); scheduleRecalc(); }
        // Auto-advance: focus next row's player name input
        if (row && row.nextElementSibling) {
          const nextInput = row.nextElementSibling.querySelector('.player-name-input');
          if (nextInput && !nextInput.value.trim()) {
            setTimeout(() => nextInput.focus(), 50);
          }
        }
      });
      dropdown.appendChild(item);
    });

    const rect = input.getBoundingClientRect();
    dropdown.style.position = 'fixed';
    dropdown.style.left = rect.left + 'px';
    dropdown.style.top = rect.bottom + 2 + 'px';
    dropdown.style.width = Math.max(rect.width, 260) + 'px';
    document.body.appendChild(dropdown);
  }

  function hideAutocomplete() {
    const el = document.getElementById('acDropdown');
    if (el) el.remove();
  }

  function openGlobalSearch(opts = {}) {
    const overlay = document.getElementById('globalSearchOverlay');
    const input = document.getElementById('globalSearchInput');
    if (!overlay || !input) return;
    if (opts.side) globalSearchTargetSide = opts.side;
    overlay.classList.add('active');
    input.value = String(opts.query || '').trim();
    renderGlobalSearchResults(input.value);
    setTimeout(() => input.focus(), 20);
  }

  function openGlobalSearchForTrade(side) {
    globalSearchTargetSide = side || '';
    openGlobalSearch({ side: globalSearchTargetSide });
  }

  function setGlobalSearchTargetSide(side) {
    globalSearchTargetSide = side === 'A' ? 'A' : (side === 'B' ? 'B' : '');
    const body = document.getElementById('globalSearchBody');
    if (body && document.getElementById('globalSearchOverlay')?.classList.contains('active')) {
      renderGlobalSearchResults(document.getElementById('globalSearchInput')?.value || '');
    }
  }

  function closeGlobalSearch() {
    const overlay = document.getElementById('globalSearchOverlay');
    if (overlay) overlay.classList.remove('active');
  }

  function scoreSearchMatch(name, queryNorm) {
    const n = normalizeForLookup(name);
    if (!queryNorm) return 10;
    if (n === queryNorm) return 100;
    if (n.startsWith(queryNorm)) return 85;
    if (n.includes(queryNorm)) return 68;
    const qParts = queryNorm.split(' ').filter(Boolean);
    if (qParts.length && qParts.every(p => n.includes(p))) return 60;
    return 0;
  }

  function getGlobalSearchResults(query, limit = 40) {
    if (!loadedData?.players) return [];
    const q = String(query || '').trim();
    const qNorm = normalizeForLookup(q);
    const source = Object.keys(loadedData.players || {});

    if (!qNorm) {
      const recent = getRecentPlayers().slice(0, 8);
      return recent
        .filter(name => loadedData.players[name] || parsePickToken(name))
        .map(name => ({ name, score: 50 }));
    }

    return source
      .map(name => ({ name, score: scoreSearchMatch(name, qNorm) }))
      .filter(x => x.score > 0)
      .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name))
      .slice(0, limit);
  }

  function addCompareCandidate(name) {
    const KEY = 'dynasty_compare_queue_v1';
    const current = uniqTrimmed(readJsonStore(KEY, []), 2);
    const norm = normalizeForLookup(name);
    const next = [name, ...current.filter(x => normalizeForLookup(x) !== norm)].slice(0, 2);
    writeJsonStore(KEY, next);
  }

  function renderGlobalSearchResults(query) {
    const body = document.getElementById('globalSearchBody');
    if (!body) return;
    if (!loadedData?.players) {
      body.innerHTML = '<div class="gs-meta">Load values first to search assets.</div>';
      return;
    }

    const q = String(query || '').trim();
    const rows = getGlobalSearchResults(q, 42);
    if (!rows.length) {
      body.innerHTML = '<div class="gs-meta">No matching players or picks.</div>';
      return;
    }

    const sideHint = globalSearchTargetSide ? `→ Add defaults to Side ${globalSearchTargetSide}` : '→ Default add target: Side B';
    body.innerHTML = `
      <div class="gs-meta">${q ? `Results for "${q}"` : 'Recent players'} ${sideHint}</div>
      <div class="mobile-row-actions" style="margin-top:2px;">
        <button class="mobile-chip-btn ${globalSearchTargetSide === 'A' ? 'primary' : ''}" onclick="setGlobalSearchTargetSide('A')">Add to Side A</button>
        <button class="mobile-chip-btn ${(!globalSearchTargetSide || globalSearchTargetSide === 'B') ? 'primary' : ''}" onclick="setGlobalSearchTargetSide('B')">Add to Side B</button>
      </div>
      ${rows.map(r => {
        const name = r.name;
        const result = computeMetaValueForPlayer(name);
        const value = (result?.metaValue && isFinite(result.metaValue)) ? Math.round(result.metaValue).toLocaleString() : '—';
        const pos = parsePickToken(name) ? 'PICK' : (getPlayerPosition(name) || '?');
        const trend = (window.playerTrends && window.playerTrends[name]) || 0;
        const trendStr = trend ? `${trend > 0 ? '+' : ''}${trend.toFixed(1)}%` : '—';
        const escaped = String(name).replace(/'/g, "\\'");
        return `
          <div class="gs-result">
            <div class="top">
              <div>
                <div class="gs-name">${name}</div>
                <div class="gs-sub">${pos} · value ${value} · trend ${trendStr}</div>
              </div>
              <span class="mobile-pill">Asset</span>
            </div>
            <div class="gs-actions">
              <button class="mobile-chip-btn primary" onclick="addAssetFromGlobalSearch('${escaped}', globalSearchTargetSide || 'B')">Add Trade</button>
              <button class="mobile-chip-btn" onclick="openAssetFromGlobalSearch('${escaped}')">Open</button>
              <button class="mobile-chip-btn" onclick="compareFromGlobalSearch('${escaped}')">Compare</button>
            </div>
          </div>
        `;
      }).join('')}
    `;
  }

  function addAssetFromGlobalSearch(name, side) {
    addRecentSearch(document.getElementById('globalSearchInput')?.value || '');
    addAssetToTrade(side || globalSearchTargetSide || 'B', name);
    renderMobileTradeWorkspace();
    closeGlobalSearch();
  }

  function openAssetFromGlobalSearch(name) {
    addRecentSearch(document.getElementById('globalSearchInput')?.value || '');
    closeGlobalSearch();
    openPlayerPopup(name);
  }

  function compareFromGlobalSearch(name) {
    addCompareCandidate(name);
    closeGlobalSearch();
    openPlayerPopup(name);
  }

  function handleNameKeydown(e) {
    const dd = document.getElementById('acDropdown');

    // Enter with no dropdown: auto-fill current row and advance
    if (e.key === 'Enter' && !dd) {
      e.preventDefault();
      const row = e.target.closest('tr');
      if (row) { autoFillRow(row); scheduleRecalc(); }
      if (row && row.nextElementSibling) {
        const nextInput = row.nextElementSibling.querySelector('.player-name-input');
        if (nextInput) setTimeout(() => nextInput.focus(), 50);
      }
      return;
    }

    if (!dd) return;
    const items = dd.querySelectorAll('.ac-item');
    const active = dd.querySelector('.ac-active');
    let idx = Array.from(items).indexOf(active);

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (active) active.classList.remove('ac-active');
      idx = (idx + 1) % items.length;
      items[idx].classList.add('ac-active');
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (active) active.classList.remove('ac-active');
      idx = (idx - 1 + items.length) % items.length;
      items[idx].classList.add('ac-active');
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const row = e.target.closest('tr');
      if (active) {
        e.target.value = active.dataset.playerName;
        hideAutocomplete();
        if (row) { autoFillRow(row); scheduleRecalc(); }
      }
      // Advance to next row
      if (row && row.nextElementSibling) {
        const nextInput = row.nextElementSibling.querySelector('.player-name-input');
        if (nextInput) setTimeout(() => nextInput.focus(), 50);
      }
    } else if (e.key === 'Escape') {
      hideAutocomplete();
    }
  }

  // Copy a shareable trade summary to clipboard
  function copyTradePitch() {
    const sides = ['A', 'B', 'C'];
    const sideNames = {A: 'Side A', B: 'Side B — You', C: 'Side C'};
    const multiTeamMode = document.getElementById('multiTeamToggle')?.checked;
    let lines = ['📊 Dynasty Trade Analysis\n'];

    for (const side of (multiTeamMode ? sides : ['A', 'B'])) {
      const tbody = document.getElementById(`side${side}Body`);
      if (!tbody) continue;
      const players = [];
      tbody.querySelectorAll('tr').forEach(row => {
        const nameInp = row.querySelector('.player-name-input');
        const metaEl = row.querySelector('.meta-value');
        const name = (nameInp?.value || '').trim();
        if (!name) return;
        const metaText = (metaEl?.textContent || '').replace(/[^0-9]/g, '');
        const meta = parseInt(metaText) || 0;
        players.push({ name, meta });
      });
      if (!players.length) continue;
      const total = players.reduce((s, p) => s + p.meta, 0);
      lines.push(`${sideNames[side]}:`);
      for (const p of players) {
        lines.push(`  ${p.name} (${p.meta.toLocaleString()})`);
      }
      lines.push(`  Total: ${total.toLocaleString()}\n`);
    }

    const pill = document.getElementById('decision');
    if (pill) lines.push(`Verdict: ${pill.textContent}`);
    const pctEl = document.getElementById('percentDiff');
    if (pctEl && pctEl.textContent !== '–') lines.push(`Difference: ${pctEl.textContent}`);

    const text = lines.join('\n');
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.getElementById('shareTradeBtn');
      if (btn) { btn.textContent = '✓ Copied!'; setTimeout(() => { btn.textContent = '📋 Copy Trade Summary'; }, 2000); }
    }).catch(() => {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = text; document.body.appendChild(ta); ta.select();
      document.execCommand('copy'); document.body.removeChild(ta);
    });
  }

  // Add a suggested player/pick to the first empty row in a side
  function addSuggestionToTrade(side, name) {
    const tbodyId = `side${side}Body`;
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    for (const row of rows) {
      const inp = row.querySelector('.player-name-input');
      if (inp && !inp.value.trim()) {
        inp.value = name;
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        if (loadedData) autoFillRow(row);
        scheduleRecalc();
        row.style.transition = 'background 0.3s';
        row.style.background = 'rgba(200, 56, 3, 0.15)';
        setTimeout(() => { row.style.background = ''; }, 800);
        return;
      }
    }
    // All rows full — add a new one
    const newRow = addPlayerRow(side, tbodyId);
    if (newRow) {
      const inp = newRow.querySelector('.player-name-input');
      if (inp) {
        inp.value = name;
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        if (loadedData) autoFillRow(newRow);
        scheduleRecalc();
      }
    }
  }

  function scheduleRecalc() {
    clearTimeout(recalcTimer);
    recalcTimer = setTimeout(recalculate, 300);
  }

  // ── RECALCULATE ──
  function recalculate() {
    // Site stats are computed on data load and settings save — not here

    const calcValueBasis = getCalculatorValueBasis();
    const alpha     = parseFloat(document.getElementById('alphaInput').value)||DEFAULT_ALPHA;
    const tolerance = parseFloat(document.getElementById('toleranceInput').value)||DEFAULT_TOLERANCE;
    const cctx = getCanonicalValueContext();
    const cfg = cctx.cfg;

    const linTot = {A:0,B:0,C:0}, wtTot = {A:0,B:0,C:0};
    const sideMetaValues = {A:[], B:[], C:[]}; // [NEW] collect for suggestion

    ['sideABody','sideBBody','sideCBody'].forEach(tbodyId => {
      const el = document.getElementById(tbodyId);
      if (!el) return;
      el.querySelectorAll('tr').forEach(row => {
        const side = row.dataset.side;
        const nameInp = row.querySelector('.player-name-input');
        const name = (nameInp?nameInp.value:'').trim();
        const siteInps = Array.from(row.querySelectorAll('.site-input'));
        const anyVal = siteInps.some(i=>i.value!=='');
        if (!name&&!anyVal) {
          const su=row.querySelector('.sites-used'); if(su)su.textContent='';
          const mv=row.querySelector('.meta-value'); if(mv)mv.textContent='';
          row.dataset.metaValue = '';
          return;
        }

        const pickInfo = parsePickToken(name);
        const isPick = !!pickInfo;
        const playerIsTE = !isPick && isPlayerTE(name);
        const rowPos = !isPick ? (getPlayerPosition(name) || '').toUpperCase() : '';
        const rowIsIdp = !isPick && ['DL','DE','DT','LB','DB','CB','S','EDGE'].includes(rowPos);

        // For picks: resolve site values directly from data
        let pickSiteData = null;
        if (isPick) {
          pickSiteData = resolvePickSiteValues(pickInfo);
        }
        const pickValuesCanonical = !!(isPick && pickSiteData && pickSiteData.__canonical);
        const inputSiteValues = {};

        siteInps.forEach(inp => {
          const key = inp.dataset.siteKey;
          const sc = cfg.find(s=>s.key===key);
          if (!sc||!sc.include||!sc.max||sc.max<=0) return;
          const raw = inp.value, v = parseFloat(raw);
          const pill = inp.parentElement.querySelector('.auto-pill');

          if (raw!==''&&isFinite(v)) {
            inputSiteValues[key] = v;
            if (pill) {
              pill.textContent = (playerIsTE && !cctx.siteTep[key] && cctx.tepMultiplier > 1) ? `TEP ×${cctx.tepMultiplier}` : '';
            }
          } else if (isPick && pickSiteData && pickSiteData[key] != null) {
            inputSiteValues[key] = Number(pickSiteData[key]);
            const siteRawPreview = getCanonicalSiteValueForSource(sc, pickSiteData[key], {
              ctx: cctx,
              playerName: name,
              playerData: pickSiteData,
              playerPos: 'PICK',
              playerIsTE: false,
              playerIsIdp: false,
              isPick: true,
              pickValuesCanonical,
            });
            if (pill) pill.textContent = siteRawPreview ? `≈${Math.round(siteRawPreview)}` : '';
          } else {
            if (pill) pill.textContent='';
          }
        });
        const composite = computeCanonicalCompositeFromSiteValues(inputSiteValues, {
          ctx: cctx,
          playerName: name,
          playerPos: rowPos,
          playerIsTE,
          playerIsIdp: rowIsIdp,
          isPick,
          pickValuesCanonical,
        });
        const su = row.querySelector('.sites-used');
        if (su) su.textContent = composite ? String(composite.siteCount) : '';
        if (!composite) {
          row.dataset.metaValue = '';
          return;
        }

        let metaValue = composite.rawCompositeValue;
        const rawMarketValue = composite.rawCompositeValue;
        const adjPos = isPick ? 'PICK' : (rowPos || (getPlayerPosition(name) || ''));
        const adjBundle = computeFinalAdjustedValue(rawMarketValue, adjPos, name, {
          siteCount: composite.siteCount,
          cv: composite.cv,
          siteDetails: composite.siteDetails,
        });
        metaValue = getValueByRankingMode(adjBundle, calcValueBasis);
        if (adjBundle) {
          row.dataset.adjustmentDebug = JSON.stringify({
            rawMarketValue: adjBundle.rawMarketValue,
            marketReliabilityScore: Number(adjBundle.marketReliability?.score ?? 0),
            marketReliabilityLabel: String(adjBundle.marketReliability?.label || ''),
            scoringMultiplierRaw: Number(adjBundle.scoring?.leagueMultiplier ?? 1),
            scoringMultiplierEffective: Number(adjBundle.scoring?.effectiveMultiplier ?? 1),
            scarcityMultiplierRaw: Number(adjBundle.scarcity?.scarcityMultiplierRaw ?? 1),
            scarcityMultiplierEffective: Number(adjBundle.scarcity?.scarcityMultiplierEffective ?? 1),
            scoringAdjustedValue: Number(adjBundle.scoringAdjustedValue ?? adjBundle.rawMarketValue),
            scarcityAdjustedValue: Number(adjBundle.scarcityAdjustedValue ?? adjBundle.rawMarketValue),
            guardrailMin: Number(adjBundle.topEndGuardrail?.minValue ?? 0),
            guardrailMax: Number(adjBundle.topEndGuardrail?.maxValue ?? 0),
            guardrailApplied: !!adjBundle.topEndGuardrail?.applied,
            finalAdjustedValue: Number(adjBundle.finalAdjustedValue ?? adjBundle.rawMarketValue),
            valueDelta: Number(adjBundle.valueDelta ?? 0),
          });
          row.dataset.lamDebug = JSON.stringify({
            baselineBucket: adjBundle.scoring?.baselineBucket,
            rawCompositeValue: adjBundle.scoring?.rawCompositeValue,
            rawLeagueMultiplier: adjBundle.scoring?.rawLeagueMultiplier,
            shrunkLeagueMultiplier: adjBundle.scoring?.shrunkLeagueMultiplier,
            adjustmentStrength: adjBundle.scoring?.adjustmentStrength,
            effectiveMultiplier: adjBundle.scoring?.effectiveMultiplier,
            formatFitSource: adjBundle.scoring?.formatFitSource || '',
            formatFitConfidence: adjBundle.scoring?.formatFitConfidence,
            formatFitRaw: adjBundle.scoring?.formatFitRaw,
            formatFitShrunk: adjBundle.scoring?.formatFitShrunk,
            formatFitFinal: adjBundle.scoring?.formatFitFinal,
            formatFitPPGTest: adjBundle.scoring?.formatFitPPGTest,
            formatFitPPGCustom: adjBundle.scoring?.formatFitPPGCustom,
            formatFitProductionShare: adjBundle.scoring?.formatFitProductionShare,
            finalAdjustedValue: adjBundle.scoringAdjustedValue,
            valueDelta: (adjBundle.scoringAdjustedValue - adjBundle.rawMarketValue),
          });
          row.dataset.scarcityDebug = JSON.stringify({
            scarcityBucket: adjBundle.scarcity?.scarcityBucket,
            scarcityMultiplierRaw: adjBundle.scarcity?.scarcityMultiplierRaw,
            scarcityMultiplierEffective: adjBundle.scarcity?.scarcityMultiplierEffective,
            scarcityStrength: adjBundle.scarcity?.scarcityStrength,
            replacementRank: adjBundle.scarcity?.replacementRank,
            replacementValue: adjBundle.scarcity?.replacementValue,
            valueAboveReplacement: adjBundle.scarcity?.valueAboveReplacement,
            finalScarcityAdjustedValue: adjBundle.scarcityAdjustedValue,
            scarcityDelta: (adjBundle.scarcityAdjustedValue - adjBundle.rawMarketValue),
          });
        } else {
          row.dataset.adjustmentDebug = '';
          row.dataset.lamDebug = '';
          row.dataset.scarcityDebug = '';
        }

        const mvEl = row.querySelector('.meta-value');
        if (mvEl) {
          let display = isFinite(metaValue) ? Math.max(1, Math.round(metaValue)).toLocaleString() : '';
          // Market edge indicator
          if (display && !isPick && loadedData) {
            const edge = getPlayerEdge(name);
            if (edge && Math.abs(edge.edgePct) >= MIN_EDGE_PCT && (edge.signal === 'BUY' || edge.signal === 'SELL')) {
              const sign = edge.edgePct > 0 ? '+' : '';
              const cls = edge.signal === 'SELL' ? 'meta-edge-sell' : 'meta-edge-buy';
              const label = edge.signal;
              const src = edge.externalSource || 'Market';
              display += `<span class="meta-edge ${cls}" title="${src} ${sign}${edge.edgePct.toFixed(0)}% vs projected curve → ${label}">${label} ${sign}${edge.edgePct.toFixed(0)}%</span>`;
            }
          }
          // Trend arrow from previous scrape
          if (display && !isPick && window.playerTrends) {
            const trend = window.playerTrends[name];
            if (trend) {
              const arrow = trend > 0 ? '↗' : '↘';
              const tColor = trend > 0 ? 'var(--green)' : 'var(--red)';
              display += `<span style="display:block;font-size:0.58rem;color:${tColor};font-family:var(--mono);" title="Change since last update">${arrow} ${trend > 0 ? '+' : ''}${trend.toFixed(1)}%</span>`;
            }
          }
          mvEl.innerHTML = display;
        }
        row.dataset.metaValue = isFinite(metaValue) ? String(Math.max(1, Math.round(metaValue))) : '';

        const linear = metaValue;
        const weighted = Math.pow(metaValue, alpha);
        if (!isFinite(linear)||!isFinite(weighted)) return;
        linTot[side]+=linear; wtTot[side]+=weighted;
        sideMetaValues[side].push(Math.round(metaValue)); // [NEW]
      });
    });

    const {A:lA,B:lB,C:lC} = linTot, {A:tA,B:tB,C:tC} = wtTot;

    const linAEl = document.getElementById('linearA'); if (linAEl) linAEl.textContent = lA?lA.toFixed(0):'0';
    const linBEl = document.getElementById('linearB'); if (linBEl) linBEl.textContent = lB?lB.toFixed(0):'0';
    document.getElementById('totalA').textContent  = tA?tA.toFixed(0):'–';
    document.getElementById('totalB').textContent  = tB?tB.toFixed(0):'–';
    const totalCEl = document.getElementById('totalC');
    if (totalCEl) totalCEl.textContent = tC?tC.toFixed(0):'–';

    document.getElementById('sideANote').textContent = lA?`Linear: ${lA.toFixed(0)}`:'';
    document.getElementById('sideBNote').textContent = lB?`Linear: ${lB.toFixed(0)}`:'';
    const sideCNote = document.getElementById('sideCNote');
    if (sideCNote) sideCNote.textContent = lC?`Linear: ${lC.toFixed(0)}`:'';

    const pill = document.getElementById('decision');
    const suggestionEl = document.getElementById('tradeSuggestion');
    const verdictBar = document.getElementById('verdictBar');
    const verdictMarker = document.getElementById('verdictMarker');

    if (multiTeamMode) {
      // ── 3-TEAM MODE ──
      // Hide 2-way-only elements
      document.querySelector('.trade-bar-wrap').style.display = 'none';
      if (verdictBar) verdictBar.style.display = 'none';

      if (!tA && !tB && !tC) {
        ['valueAdjustment','whoAhead','percentDiff'].forEach(id=>document.getElementById(id).textContent='–');
        pill.textContent='–'; pill.className='decision-pill neutral';
        if (suggestionEl) suggestionEl.style.display='none';
        queuePersistSettings(); return;
      }

      const sides = [{name:'Side A',val:tA,cls:'win-a'},{name:'Side B',val:tB,cls:'win-b'},{name:'Side C',val:tC,cls:'win-c'}];
      sides.sort((a,b)=>b.val-a.val);
      const winner = sides[0], second = sides[1], third = sides[2];

      if (winner.val === 0) {
        pill.textContent='–'; pill.className='decision-pill neutral';
        ['valueAdjustment','whoAhead','percentDiff'].forEach(id=>document.getElementById(id).textContent='–');
        queuePersistSettings(); return;
      }

      const gapToSecond = winner.val - second.val;
      const adjGap = Math.pow(gapToSecond, 1/alpha);
      const pctGap = gapToSecond / winner.val;

      if (pctGap < 0.02) {
        pill.textContent = '≈ Even'; pill.className = 'decision-pill even';
      } else {
        pill.textContent = `${winner.name} Wins`; pill.className = `decision-pill ${winner.cls}`;
      }

      document.getElementById('whoAhead').textContent = sides.map(s => `${s.name}: ${s.val.toFixed(0)}`).join(' · ');
      document.getElementById('percentDiff').textContent = `${winner.name} +${(pctGap*100).toFixed(1)}% over ${second.name}`;
      document.getElementById('valueAdjustment').textContent = isFinite(adjGap)?adjGap.toFixed(0):'–';

      if (suggestionEl) {
        if (pctGap > 0.03) {
          suggestionEl.innerHTML = `<strong>${winner.name} gets the most value.</strong> ${third.name} gets the least (${third.val.toFixed(0)}).`;
          suggestionEl.style.display = 'block';
        } else {
          suggestionEl.innerHTML = '<strong>This is a balanced 3-way trade.</strong>';
          suggestionEl.style.display = 'block';
        }
      }

    } else {
      // ── 2-TEAM MODE ──
      // Show trade bar
      document.querySelector('.trade-bar-wrap').style.display = '';

      // Trade bar — proportional fill from each edge
      const total = tA+tB;
      if (total>0) {
        const pctA = Math.max(5, Math.round((tA/total)*50));
        const pctB = Math.max(5, Math.round((tB/total)*50));
        document.getElementById('barA').style.width = pctA + '%';
        document.getElementById('barB').style.width = pctB + '%';
      } else {
        document.getElementById('barA').style.width='0%';
        document.getElementById('barB').style.width='0%';
      }

      if (!tA&&!tB) {
        ['valueAdjustment','whoAhead','percentDiff'].forEach(id=>document.getElementById(id).textContent='–');
        pill.textContent='–'; pill.className='decision-pill neutral';
        if (suggestionEl) suggestionEl.style.display='none';
        if (verdictBar) verdictBar.style.display='none';
        queuePersistSettings(); return;
      }

      const diff = Math.abs(tA-tB);
      const adj  = Math.pow(diff, 1/alpha);
      document.getElementById('valueAdjustment').textContent = isFinite(adj)?adj.toFixed(0):'–';

      let who='Even trade', pct=0;
      if (tA>tB) { pct=diff/tA; who=`Side A +${adj.toFixed(0)} (${(pct*100).toFixed(1)}%)`; }
      else if (tB>tA) { pct=diff/tB; who=`Side B +${adj.toFixed(0)} (${(pct*100).toFixed(1)}%)`; }
      else { who='Even trade (0%)'; }

      document.getElementById('whoAhead').textContent  = who;
      document.getElementById('percentDiff').textContent = (pct*100).toFixed(1)+'%';

      // Verdict: which side wins
      if (pct < 0.02) {
        pill.textContent = '≈ Even Trade'; pill.className = 'decision-pill even';
      } else if (tA > tB) {
        pill.textContent = 'Side A Wins'; pill.className = 'decision-pill win-a';
      } else {
        pill.textContent = 'Side B Wins'; pill.className = 'decision-pill win-b';
      }

      // Verdict gradient bar
      if (verdictBar && verdictMarker) {
        verdictBar.style.display = 'block';
        let markerPct;
        if (tA > tB) {
          markerPct = Math.max(5, 50 - pct * 200);
        } else if (tB > tA) {
          markerPct = Math.min(95, 50 + pct * 200);
        } else {
          markerPct = 50;
        }
        verdictMarker.style.left = markerPct + '%';
      }

      // Trade balancing suggestion with specific players
      if (suggestionEl) {
        const bBehind = tA > tB;
        const aheadSide = tA > tB ? 'A' : 'B';
        const behindSide = tA > tB ? 'B' : 'A';

        if (pct > tolerance) {
          const gap = Math.round(adj);
          const behindTeamName = behindSide === 'A'
            ? document.getElementById('teamFilterA')?.value
            : document.getElementById('teamFilterB')?.value;

          // Find players from the behind-team's roster that could balance
          let candidates = [];
          if (behindTeamName && loadedData) {
            const team = sleeperTeams.find(t => t.name === behindTeamName);
            if (team) {
              // Get players already in the trade on this side
              const sideBody = document.getElementById(`side${behindSide}Body`);
              const alreadyInTrade = new Set();
              if (sideBody) {
                sideBody.querySelectorAll('.player-name-input').forEach(inp => {
                  const n = (inp.value || '').trim().toLowerCase();
                  if (n) alreadyInTrade.add(n);
                });
              }

              for (const pName of team.players) {
                if (alreadyInTrade.has(pName.toLowerCase())) continue;
                const result = computeMetaValueForPlayer(pName);
                if (result && result.metaValue > 0) {
                  // Candidate should roughly close the gap (within 60% to 140% of gap)
                  const metaV = result.metaValue;
                  if (metaV >= gap * 0.6 && metaV <= gap * 1.4) {
                    const pos = getPlayerPosition(pName) || '';
                    candidates.push({ name: pName, meta: metaV, pos, diff: Math.abs(metaV - gap) });
                  }
                }
              }
              // Sort by closest to the gap
              candidates.sort((a, b) => a.diff - b.diff);
              candidates = candidates.slice(0, 5);
            }
          }

          // Also suggest draft picks that could balance
          let pickSuggestions = [];
          // Generate picks from known pick values (PICK_KTC_VALUES + pickAnchors)
          for (const [pickKey, kv] of Object.entries(PICK_KTC_VALUES)) {
            const pickInfo = parsePickToken(pickKey);
            if (!pickInfo) continue;
            const pickData = resolvePickSiteValues(pickInfo);
            if (!pickData) continue;
            // Compute a rough composite from the resolved data
            let total = 0, count = 0;
            for (const [sk, sv] of Object.entries(pickData)) {
              if (typeof sv === 'number' && sv > 0) { total += sv; count++; }
            }
            const pickMeta = count > 0 ? total / count : kv;
            // Normalize pick meta similar to how calculator does it (rough approximation)
            const approxComposite = Math.min(kv, pickMeta); // Use KTC value as proxy
            if (approxComposite >= gap * 0.5 && approxComposite <= gap * 1.5) {
              pickSuggestions.push({ name: pickKey, meta: Math.round(approxComposite), diff: Math.abs(approxComposite - gap) });
            }
          }
          pickSuggestions.sort((a, b) => a.diff - b.diff);
          pickSuggestions = pickSuggestions.slice(0, 3);

          const gapLabel = pct >= 0.20 ? 'significantly ahead' : pct >= 0.10 ? 'ahead' : 'slightly ahead';
          let html = `<strong>Side ${aheadSide} is ${gapLabel} by ~${gap.toLocaleString()}</strong>`;
          html += ` (${(pct*100).toFixed(1)}% gap). `;

          if (candidates.length > 0 || pickSuggestions.length > 0) {
            html += `<span style="color:var(--subtext);">Add one of these to Side ${behindSide} to even it out:</span>`;
            html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">';

            for (const c of candidates) {
              const posColor = {'QB':'#e74c3c','RB':'#27ae60','WR':'#3498db','TE':'#e67e22'}[c.pos] || '#9b59b6';
              html += `<button class="btn btn-ghost btn-sm" style="font-size:0.7rem;padding:4px 10px;border-color:var(--border-bright);" `
                    + `onclick="addSuggestionToTrade('${behindSide}','${c.name.replace(/'/g,"\\'")}')">` 
                    + `<span style="color:${posColor};font-weight:700;margin-right:3px;">${c.pos}</span>`
                    + `${c.name} <span style="color:var(--subtext);">(${c.meta.toLocaleString()})</span></button>`;
            }
            for (const p of pickSuggestions) {
              html += `<button class="btn btn-ghost btn-sm" style="font-size:0.7rem;padding:4px 10px;border-color:var(--border-bright);" `
                    + `onclick="addSuggestionToTrade('${behindSide}','${p.name.replace(/'/g,"\\'")}')">` 
                    + `<span style="color:var(--amber);font-weight:700;margin-right:3px;">PICK</span>`
                    + `${p.name} <span style="color:var(--subtext);">(~${p.meta.toLocaleString()})</span></button>`;
            }
            html += '</div>';
          } else if (!behindTeamName) {
            html += `<span style="color:var(--subtext);">Select a team for Side ${behindSide} to see player suggestions.</span>`;
          } else {
            if (pct < 0.10) {
              html += 'A late-round pick could close this gap.';
            } else if (pct < 0.20) {
              html += 'A mid-tier player or 2nd-round pick could balance this.';
            } else {
              html += 'This needs a significant piece to even out.';
            }
          }
          suggestionEl.innerHTML = html;
          suggestionEl.style.display = 'block';
        } else if (pct > 0.02) {
          suggestionEl.innerHTML = `<strong>Fair trade.</strong> Side ${aheadSide} is slightly ahead (${(pct*100).toFixed(1)}%) but this is within the normal fair range — most leagues would accept this.`;
          suggestionEl.style.display = 'block';
        } else {
          suggestionEl.style.display = 'none';
        }
      }
    }

    // Show/hide trade action buttons
    const hasContent = lA > 0 || lB > 0;
    const shareBtn = document.getElementById('shareTradeBtn');
    if (shareBtn) shareBtn.style.display = hasContent ? '' : 'none';
    const saveBtn = document.getElementById('saveTradeBtn');
    if (saveBtn) saveBtn.style.display = hasContent ? '' : 'none';

    // Compute trade impact simulator
    computeTradeImpact();

    const mobileWorkspace = document.getElementById('mobileTradeWorkspace');
    const shouldRefreshMobileTrade = !!mobileWorkspace && isMobileViewport();
    if (shouldRefreshMobileTrade) {
      renderMobileTradeWorkspace();
      updateMobileTradeTray();
    }
    saveTradeDraftState();
    updateCalculatorEmptyHint();
    if (activeTabId === 'home') buildHomeHub();
    if (activeTabId === 'more') buildMoreHub();

    queuePersistSettings();
  }

  function toggleDataFreshnessDetails(forceOpen = null) {
    if (typeof forceOpen === 'boolean') dataFreshnessDetailsOpen = !!forceOpen;
    else dataFreshnessDetailsOpen = !dataFreshnessDetailsOpen;
    const details = document.getElementById('dataFreshnessDetails');
    const caret = document.getElementById('dataFreshnessToggleCaret');
    if (details) details.style.display = dataFreshnessDetailsOpen ? 'block' : 'none';
    if (caret) caret.textContent = dataFreshnessDetailsOpen ? '▾' : '▸';
  }

  function setTopFreshnessSummary(text, opts = {}) {
    const el = document.getElementById('dataFreshnessTop');
    if (!el) return;
    const stale = !!opts.stale;
    el.textContent = text || '';
    el.style.display = text ? '' : 'none';
    el.style.color = stale ? 'var(--amber)' : 'var(--subtext)';
  }

  function getScrapeFreshnessMeta(data) {
    const stamp = data?.scrapeTimestamp || data?.date;
    if (!stamp) return null;
    const scrapeDate = new Date(stamp);
    if (!isFinite(scrapeDate.getTime())) return null;
    const ageHours = Math.max(0, Math.round((Date.now() - scrapeDate.getTime()) / 3600000));
    const ageText = ageHours < 1 ? 'just now' : ageHours < 24 ? `${ageHours}h ago` : `${Math.round(ageHours / 24)}d ago`;
    return {
      ageHours,
      ageText,
      stale: ageHours > 48,
    };
  }

  // Keep top freshness summary + detailed source card wording in one place.
  function buildSourceFreshnessSummaryText(okCount, totalCount, scrapeAgeText = '', dlfCsvStale = false) {
    const parts = [`Sources ${okCount}/${totalCount}`];
    if (scrapeAgeText) parts.push(scrapeAgeText);
    if (dlfCsvStale) parts.push('DLF stale');
    return parts.join(' · ');
  }

  function loadJsonData(data, opts = {}) {
    if (!data || !data.players || !data.maxValues) return false;
    const phase = String(opts.phase || 'full').toLowerCase();
    const isStartupPhase = phase === 'startup';
    const skipTradeDraftRestore = !!opts.skipTradeDraftRestore;
    const deferWarmups = !!opts.deferWarmups;
    const deferAnchorFill = !!opts.deferAnchorFill;
    const skipSecondaryHubWarm = !!opts.skipSecondaryHubWarm;
    if (isStartupPhase) perfMark('startup_load_begin');
    else perfMark('full_load_begin');

    // Clean escaped unicode in player-name keys only when needed.
    let cleanPlayers = null;
    for (const [name, vals] of Object.entries(data.players)) {
      const clean = name.replace(/\\u0027/g, "'").replace(/\\u2019/g, "\u2019").replace(/\\u00e9/g, "é");
      if (clean === name) continue;
      if (!cleanPlayers) cleanPlayers = { ...data.players };
      delete cleanPlayers[name];
      cleanPlayers[clean] = vals;
    }
    if (cleanPlayers) data.players = cleanPlayers;

    loadedData = data;
    normalizeLookupCache.clear();
    pickTokenParseCache.clear();
    invalidateRankingsBaseRowsCache();
    playerNames = Object.keys(data.players).sort();
    playerSleeperIds = {};
    sleeperIdToPlayer = {};
    ktcIdToPlayer = {};

    // Build identity maps from exported Sleeper/KTC IDs.
    for (const [name, pdata] of Object.entries(data.players || {})) {
      const sid = pdata?._sleeperId;
      if (sid != null && sid !== '') {
        const sk = String(sid).trim();
        playerSleeperIds[name] = sk;
        sleeperIdToPlayer[sk] = name;
      }
    }
    if (data.sleeper?.playerIds && typeof data.sleeper.playerIds === 'object') {
      for (const [name, sid] of Object.entries(data.sleeper.playerIds)) {
        if (sid == null || sid === '') continue;
        const sk = String(sid).trim();
        playerSleeperIds[name] = sk;
        if (!sleeperIdToPlayer[sk]) sleeperIdToPlayer[sk] = name;
      }
    }
    if (data.sleeper?.idToPlayer && typeof data.sleeper.idToPlayer === 'object') {
      for (const [sid, name] of Object.entries(data.sleeper.idToPlayer)) {
        if (!sid || !name) continue;
        const sk = String(sid).trim();
        sleeperIdToPlayer[sk] = name;
        if (!playerSleeperIds[name]) playerSleeperIds[name] = sk;
      }
    }
    if (data.ktcIdMap && typeof data.ktcIdMap === 'object') {
      for (const [kid, name] of Object.entries(data.ktcIdMap)) {
        if (!kid || !name) continue;
        ktcIdToPlayer[String(kid).trim()] = name;
      }
    }

    // Show data freshness summary
    let scrapeAgeText = '';
    let scrapeAgeStale = false;
    const freshnessMeta = getScrapeFreshnessMeta(data);
    if (freshnessMeta) {
      scrapeAgeText = freshnessMeta.ageText;
      scrapeAgeStale = freshnessMeta.stale;
      setTopFreshnessSummary(`Updated ${freshnessMeta.ageText}${freshnessMeta.stale ? ' · stale' : ''}`, { stale: freshnessMeta.stale });
    }

    if (data.sleeper && data.sleeper.teams) {
      sleeperTeams = data.sleeper.teams;
      populateTeamDropdowns();
      // Hardcode league profile bootstrap: no login flow required.
      ensureHardcodedLeagueProfile();
    }
    if (data.sleeper && data.sleeper.positions) {
      playerPositions = data.sleeper.positions;
    }
    rebuildPlayerLookupCaches();

    if (data.maxValues && data.maxValues.idpTradeCalc) {
      // IDPTradeCalc anchor — use the scraper-computed value (max excl. Travis Hunter)
      const anchorEl = document.getElementById('idpAnchorInput');
      if (anchorEl) {
        const scraperAnchor = data.settings?.idpAnchor;
        if (scraperAnchor && scraperAnchor > 0) {
          anchorEl.value = scraperAnchor;
          // Also update max for IDP rank sites to match anchor
          const pffMaxEl = document.getElementById('max_pffIdp');
          const fpIdpMaxEl = document.getElementById('max_fantasyProsIdp');
          if (pffMaxEl) pffMaxEl.value = scraperAnchor;
          if (fpIdpMaxEl) fpIdpMaxEl.value = scraperAnchor;
        }
      }
    }

    const rankSites = new Set(
      sites
        .filter(s => ['rank', 'idpRank'].includes(s.mode || 'value'))
        .map(s => s.key)
    );
    sites.forEach(s => {
      if (rankSites.has(s.key)) return;
      const maxEl = document.getElementById('max_' + s.key);
      if (maxEl && data.maxValues[s.key] != null && data.maxValues[s.key] > 0) {
        maxEl.value = data.maxValues[s.key];
      }
    });
    // Keep source table aligned to what's actually in loaded data.
    syncSiteConfigToLoadedData(data);
    // DynastyNerds is part of the default market stack; stale session settings should not
    // hide its column when valid data exists in the current dataset.
    const dynastyNerdsHasData = (
      (Array.isArray(data.sites) && data.sites.some(s => s?.key === 'dynastyNerds' && Number(s.playerCount) > 0)) ||
      (Number(data.maxValues?.dynastyNerds) > 0) ||
      Object.values(data.players || {}).some(p => Number(p?.dynastyNerds) > 0)
    );
    const dynastyNerdsInclude = document.getElementById('include_dynastyNerds');
    if (dynastyNerdsInclude && dynastyNerdsHasData) {
      dynastyNerdsInclude.disabled = false;
      dynastyNerdsInclude.checked = true;
    }
    const dlfKeys = ['dlfSf', 'dlfIdp', 'dlfRsf', 'dlfRidp'];
    const dlfImport = (data.settings && data.settings.dlfImport && typeof data.settings.dlfImport === 'object')
      ? data.settings.dlfImport
      : {};
    const dlfImportRows = Object.values(dlfImport).filter(v => v && typeof v === 'object');
    const dlfLoadedRows = dlfImportRows.filter(v => !!v.loaded);
    const dlfHasFreshCsv = dlfLoadedRows.some(v => !(v.stale === true || Number(v.ageDays) > 7));
    const dlfCsvStale = dlfLoadedRows.length > 0 && !dlfHasFreshCsv;
    const dlfHasData = (
      (Array.isArray(data.sites) && data.sites.some(s => dlfKeys.includes(s?.key) && Number(s.playerCount) > 0)) ||
      dlfKeys.some(k => Number(data.maxValues?.[k]) > 0) ||
      Object.values(data.players || {}).some(p => dlfKeys.some(k => Number(p?.[k]) > 0))
    );

    const st = document.getElementById('dataStatus');
    const count = Object.keys(data.players).length;
    const siteCount = data.sites ? data.sites.filter(s => {
      const n = Number(s?.playerCount || 0);
      if (n > 0) return true;
      if (s?.key === 'dynastyNerds') return dynastyNerdsHasData;
      if (s?.key === 'DLF') return dlfHasData && !dlfCsvStale;
      return false;
    }).length : 0;
    const leagueInfo = data.sleeper ? ` · ${data.sleeper.leagueName}` : '';
    const dateInfo = data.date ? ` · updated ${data.date}` : '';
    st.textContent = `✓ ${count} players loaded (${siteCount} sources${dateInfo})${leagueInfo}`;
    st.style.color = 'var(--green)';

    // Data freshness: compact summary + expandable site pills
    const freshnessEl = document.getElementById('dataFreshness');
    if (freshnessEl && data.sites) {
      const siteLabels = {ktc:'KTC', fantasyCalc:'FC', dynastyDaddy:'DD', fantasyPros:'FP',
                          draftSharks:'DS', yahoo:'Yahoo', dynastyNerds:'DN',
                          DLF:'DLF',
                          dlfSf:'DLF SF', dlfIdp:'DLF IDP', dlfRsf:'DLF R SF', dlfRidp:'DLF R IDP',
                          idpTradeCalc:'IDP TC', pffIdp:'PFF', fantasyProsIdp:'FP IDP'};
      const siteCountMap = new Map((data.sites || []).map(s => [String(s?.key || ''), Number(s?.playerCount || 0)]));
      const dlfSubCount = dlfKeys.reduce((sum, k) => sum + Math.max(0, Number(siteCountMap.get(k) || 0)), 0);
      let html = '';
      let okCount = 0;
      let totalCount = 0;
      for (const s of data.sites) {
        totalCount++;
        const label = siteLabels[s.key] || s.key;
        let displayCount = Number(s?.playerCount || 0);
        let ok = displayCount > 0;
        if (!ok && s.key === 'dynastyNerds' && dynastyNerdsHasData) {
          ok = true;
          displayCount = Math.max(displayCount, 1);
        }
        if (!ok && s.key === 'DLF' && dlfHasData) {
          ok = !dlfCsvStale;
          displayCount = Math.max(displayCount, dlfSubCount, 1);
        }
        if (ok && dlfCsvStale && (s.key === 'DLF' || dlfKeys.includes(s.key))) ok = false;
        if (ok) okCount++;
        const color = ok ? 'var(--green)' : 'var(--red)';
        const bg = ok ? 'rgba(0,200,100,0.1)' : 'rgba(255,80,80,0.1)';
        let titleExtra = '';
        if ((s.key === 'DLF' || dlfKeys.includes(s.key)) && dlfCsvStale) titleExtra = ' (csv >7d old)';
        html += `<span style="display:inline-block;padding:2px 6px;margin:2px;border-radius:4px;font-size:0.62rem;font-family:var(--mono);color:${color};background:${bg};border:1px solid ${color}22;" title="${s.key}: ${displayCount} players${titleExtra}">${label} ${ok ? displayCount : '✗'}</span>`;
      }
      const sourceSummaryText = buildSourceFreshnessSummaryText(okCount, totalCount, scrapeAgeText, dlfCsvStale);
      freshnessEl.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-ghost btn-sm" type="button" onclick="toggleDataFreshnessDetails()">
            ${sourceSummaryText}
            <span id="dataFreshnessToggleCaret">${dataFreshnessDetailsOpen ? '▾' : '▸'}</span>
          </button>
          <span style="font-size:0.66rem;color:var(--subtext);font-family:var(--mono);">Tap to view source health</span>
        </div>
        <div id="dataFreshnessDetails" style="margin-top:6px;line-height:1.8;display:${dataFreshnessDetailsOpen ? 'block' : 'none'};">
          ${html}
        </div>
      `;
      freshnessEl.style.display = '';
      setTopFreshnessSummary(sourceSummaryText, {
        stale: scrapeAgeStale || dlfCsvStale,
      });
    }
    const qc = document.getElementById('quickUseCard');
    if (qc) qc.classList.add('data-loaded');

    // Compute per-site mean/stdev for z-score normalization.
    // Startup pass prefers server-provided stats to avoid blocking first paint with
    // a full client recompute across all players.
    const cfg = getSiteConfig();
    const usedPayloadSiteStats = isStartupPhase && hydrateSiteStatsFromPayload(data, cfg);
    if (!usedPayloadSiteStats) computeSiteStats();

    // Initialize League Adjustment Multipliers
    initLAM();
    initScarcity();

    // Non-critical warmups are intentionally deferred so first render becomes interactive sooner.
    if (!deferWarmups) {
      schedulePostLoadWarmups(data);
    }

    // Auto-fill pick anchor values from scraped pick data
    if (deferAnchorFill) {
      queueIdleWork(() => autoFillAnchors(), 1600);
    } else {
      autoFillAnchors();
    }

    // Populate roster dashboard team dropdown
    populateRosterTeamDropdown();

    // Restore roster team selection from session
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        const preferredFromSession = resolvePreferredTeamName({
          teams: sleeperTeams,
          explicitTeam: d.rosterTeam || '',
          savedTeam: localStorage.getItem('dynasty_my_team') || '',
          profileTeam: getProfile()?.teamName || '',
        });
        if (preferredFromSession) syncGlobalTeam(preferredFromSession);
      }
    } catch(_) {}
    if (!localStorage.getItem('dynasty_my_team')) {
      const preferred = resolvePreferredTeamName({
        teams: sleeperTeams,
        profileTeam: getProfile()?.teamName || '',
      });
      if (preferred) syncGlobalTeam(preferred);
    }

    const mp = getMobilePrefs();
    if (mp.sortBasis) {
      const sortEl = document.getElementById('rankingsSortBasis');
      if (sortEl) sortEl.value = normalizeValueBasis(mp.sortBasis);
    }
    rankingsSortAsc = !!mp.sortAsc;
    if (mp.filterPos) {
      currentRankingsFilter = normalizeRankingsFilterPos(mp.filterPos);
      document.querySelectorAll('.pos-filter-btn').forEach(b => b.classList.toggle('active', b.dataset.pos === currentRankingsFilter));
    }
    rankingsExtraFilters = {
      picksOnly: !!mp.picksOnly,
      trendingOnly: !!mp.trendingOnly,
      ageBucket: mp.ageBucket || 'ALL',
    };

    if (!skipTradeDraftRestore) {
      loadTradeDraftState();
    }
    renderMobileTradeWorkspace();
    updateMobileTradeTray();
    if (activeTabId === 'home') buildHomeHub();
    if (activeTabId === 'more') buildMoreHub();
    if (!skipSecondaryHubWarm) {
      // Warm secondary hubs off the critical path so first paint/interaction stays snappy.
      queueIdleWork(() => {
        if (activeTabId !== 'home') buildHomeHub();
        if (activeTabId !== 'more') buildMoreHub();
      }, 1200);
      postDataViewsHydrated = true;
    } else if (!postDataViewsHydrated) {
      postDataViewsHydrated = false;
    }
    updateRankingsActiveChips();
    updateCalculatorEmptyHint();
    if (isStartupPhase) {
      perfMark('startup_load_end');
      perfMeasure('startup_load_ms', 'startup_load_begin', 'startup_load_end');
    } else {
      perfMark('full_load_end');
      perfMeasure('full_load_ms', 'full_load_begin', 'full_load_end');
    }

    return true;
  }

  function queueIdleWork(fn, timeoutMs = 800) {
    if (typeof fn !== 'function') return;
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(() => fn(), { timeout: timeoutMs });
      return;
    }
    setTimeout(fn, 32);
  }

  function schedulePostLoadWarmups(data) {
    queueIdleWork(() => primeRankingsBaseRowsCache(), 1200);
    scheduleTrendComputation(data);
  }

  function scheduleTrendComputation(data) {
    trendComputeToken += 1;
    const token = trendComputeToken;
    if (pendingTrendCompute) {
      try { clearTimeout(pendingTrendCompute); } catch (_) {}
      pendingTrendCompute = null;
    }
    queueIdleWork(() => runTrendComputation(data, token), 1500);
  }

  function getTrendComparableValue(name, pdata) {
    const pre = Number(
      pdata?._finalAdjusted
      ?? pdata?._leagueAdjusted
      ?? pdata?._scarcityAdjusted
      ?? pdata?._scoringAdjusted
      ?? pdata?._composite
    );
    if (Number.isFinite(pre) && pre > 0) {
      return clampValue(Math.round(pre), 1, COMPOSITE_SCALE);
    }
    const result = computeMetaValueForPlayer(name);
    if (result && Number.isFinite(result.metaValue) && result.metaValue > 0) {
      return clampValue(Math.round(result.metaValue), 1, COMPOSITE_SCALE);
    }
    return 0;
  }

  function runTrendComputation(data, token) {
    if (!data || !data.players || token !== trendComputeToken) return;
    try {
      const prevRaw = localStorage.getItem('dynasty_prev_composites');
      const prevData = prevRaw ? JSON.parse(prevRaw) : {};
      const prevStamp = localStorage.getItem(PREV_TREND_STAMP_KEY) || '';
      const currentStamp = String(data.scrapeTimestamp || data.date || '');
      window.prevComposites = prevData;
      window.currentComposites = {};
      window.playerTrends = {};

      // Fast path: identical source snapshot already computed.
      if (prevStamp && currentStamp && prevStamp === currentStamp && Object.keys(prevData).length > 50) {
        window.currentComposites = prevData;
        return;
      }

      const entries = Object.entries(data.players || {});
      const currentComposites = {};
      const chunkSize = 64;
      let idx = 0;

      const processChunk = () => {
        if (token !== trendComputeToken || loadedData !== data) return;
        const end = Math.min(idx + chunkSize, entries.length);
        for (; idx < end; idx++) {
          const [name, pdata] = entries[idx];
          const trendVal = getTrendComparableValue(name, pdata);
          if (trendVal > 0) {
            currentComposites[name] = trendVal;
          }
        }
        if (idx < entries.length) {
          pendingTrendCompute = setTimeout(processChunk, 0);
          return;
        }

        pendingTrendCompute = null;
        window.currentComposites = currentComposites;
        const prevDate = localStorage.getItem('dynasty_prev_date') || '';
        const currentDate = data.date || '';
        if (prevDate && prevDate !== currentDate && Object.keys(prevData).length > 50) {
          for (const [name, curVal] of Object.entries(currentComposites)) {
            const prevVal = prevData[name];
            if (prevVal && prevVal > 100) {
              const pctChange = ((curVal - prevVal) / prevVal) * 100;
              if (Math.abs(pctChange) >= 2) {
                window.playerTrends[name] = pctChange;
              }
            }
          }
          if (DEBUG_MODE) {
            const up = Object.values(window.playerTrends).filter(v => v > 0).length;
            const down = Object.values(window.playerTrends).filter(v => v < 0).length;
            console.log(`[Trends] ${up} rising, ${down} falling (vs ${prevDate})`);
          }
        }
        localStorage.setItem('dynasty_prev_composites', JSON.stringify(currentComposites));
        if (currentStamp) localStorage.setItem(PREV_TREND_STAMP_KEY, currentStamp);
        localStorage.setItem('dynasty_prev_date', currentDate);
      };

      processChunk();
    } catch (e) {
      pendingTrendCompute = null;
      window.prevComposites = {};
      window.playerTrends = {};
    }
  }

  // ── AUTO-FILL PICK ANCHORS ──
  // Parses pick data from loaded JSON's pickAnchors, then interpolates/extrapolates
  // to fill in the 6 anchor inputs for each site.
  function autoFillAnchors(force) {
    if (!loadedData || !loadedData.pickAnchors) return;
    const anchorSlots = getAnchorPicksUI(); // e.g. ["1.01","1.06","1.12","2.06","3.06","4.12"]
    if (!anchorSlots.some(s => s)) return;

    const currentYear = parseInt(document.getElementById('pickCurrentYear')?.value) || 2026;
    const leagueSize = parseInt(document.getElementById('pickLeagueSize')?.value) || 12;

    // Convert anchor slot strings to numeric position for ordering (1.01 -> 1.01, 2.06 -> 2.06)
    function slotToNum(slotStr) {
      if (!slotStr) return NaN;
      const parts = slotStr.split('.');
      if (parts.length !== 2) return NaN;
      return parseInt(parts[0]) + parseInt(parts[1]) / 100;
    }

    const anchorNums = anchorSlots.map(slotToNum);

    function entryToNum(entry) {
      if (!entry) return NaN;
      if (entry.kind === 'slot') {
        return entry.round + entry.slot / 100;
      }
      if (entry.kind === 'tier') {
        const slot = pickTierRepresentativeSlot(entry.tier || 'mid', leagueSize);
        return entry.round + slot / 100;
      }
      return NaN;
    }

    function selectEntriesForYear(entries) {
      const exact = entries.filter(e => Number.isFinite(e.year) && e.year === currentYear);
      if (exact.length) return exact;

      const yearless = entries.filter(e => e.year == null);
      if (yearless.length) return yearless;

      const dated = entries.filter(e => Number.isFinite(e.year));
      if (!dated.length) return [];

      let minDiff = Infinity;
      dated.forEach(e => { minDiff = Math.min(minDiff, Math.abs(e.year - currentYear)); });
      return dated.filter(e => Math.abs(e.year - currentYear) === minDiff);
    }

    // For each site, build known points and interpolate
    for (const [siteKey, pickMap] of Object.entries(loadedData.pickAnchors)) {
      const parsedEntries = [];
      for (const [pickName, val] of Object.entries(pickMap)) {
        const n = Number(val);
        if (!isFinite(n) || n <= 0) continue;
        const parsed = parseAnchorPickName(pickName);
        if (!parsed) continue;
        parsedEntries.push({ ...parsed, value: n });
      }

      const selectedEntries = selectEntriesForYear(parsedEntries);
      const points = [];
      selectedEntries.forEach(e => {
        const num = entryToNum(e);
        if (isFinite(num)) points.push({ num, value: e.value });
      });

      if (points.length < 1) continue;
      points.sort((a, b) => a.num - b.num);

      // Deduplicate: if multiple picks map to same num, average them
      const deduped = [];
      let i = 0;
      while (i < points.length) {
        let j = i;
        let sum = 0, count = 0;
        while (j < points.length && Math.abs(points[j].num - points[i].num) < 0.001) {
          sum += points[j].value;
          count++;
          j++;
        }
        deduped.push({ num: points[i].num, value: sum / count });
        i = j;
      }

      // For each anchor slot, interpolate or extrapolate
      for (let ai = 0; ai < 6; ai++) {
        const target = anchorNums[ai];
        if (!isFinite(target)) continue;

        const inputId = `anchor_${siteKey}_${ai}`;
        const el = document.getElementById(inputId);
        if (!el) continue;
        // Don't overwrite user-entered values unless force=true
        if (!force && el.value && el.value.trim() !== '') continue;

        let estimated = null;

        // Exact match (within tolerance)
        const exact = deduped.find(p => Math.abs(p.num - target) < 0.005);
        if (exact) {
          estimated = exact.value;
        } else if (deduped.length === 1) {
          // Single point: extrapolate using typical pick value decay
          // Pick values roughly follow: value = A * position^(-1.5)
          const p = deduped[0];
          const ratio = p.num / target;
          estimated = p.value * Math.pow(ratio, 1.5);
        } else {
          // Find bracketing points for log-linear interpolation
          let lo = null, hi = null;
          for (const p of deduped) {
            if (p.num <= target) lo = p;
          }
          for (let k = deduped.length - 1; k >= 0; k--) {
            if (deduped[k].num >= target) hi = deduped[k];
          }

          if (lo && hi && lo !== hi) {
            // Log-linear interpolation between bracketing points
            const t = (target - lo.num) / (hi.num - lo.num);
            if (lo.value > 0 && hi.value > 0) {
              estimated = Math.exp(Math.log(lo.value) * (1 - t) + Math.log(hi.value) * t);
            } else {
              estimated = lo.value + t * (hi.value - lo.value);
            }
          } else if (lo) {
            // Extrapolating beyond highest slot — use the two highest-num points
            if (deduped.length >= 2) {
              const p1 = deduped[deduped.length - 2]; // second-highest num
              const p2 = deduped[deduped.length - 1]; // highest num (closest to target)
              if (p1.value > 0 && p2.value > 0 && p2.num !== p1.num) {
                const alpha = Math.log(p2.value / p1.value) / Math.log(p2.num / p1.num);
                estimated = p2.value * Math.pow(target / p2.num, alpha);
              }
            }
            if (!isFinite(estimated) || estimated <= 0) {
              estimated = lo.value * Math.pow(lo.num / target, 1.5);
            }
          } else if (hi) {
            // Extrapolating below lowest slot — use the two lowest-num points
            if (deduped.length >= 2) {
              const p1 = deduped[0]; // lowest num (closest to target)
              const p2 = deduped[1]; // second-lowest num
              if (p1.value > 0 && p2.value > 0 && p2.num !== p1.num) {
                const alpha = Math.log(p2.value / p1.value) / Math.log(p2.num / p1.num);
                estimated = p1.value * Math.pow(target / p1.num, alpha);
              }
            }
            if (!isFinite(estimated) || estimated <= 0) {
              estimated = hi.value * Math.pow(hi.num / target, 1.5);
            }
          }
        }

        if (isFinite(estimated) && estimated > 0) {
          el.value = Math.round(estimated);
        }
      }
    }
  }

  function resetPickAnchorsFromLoadedData() {
    if (!loadedData || !loadedData.pickAnchors) {
      alert('Load scraped data first to reset pick anchors.');
      return;
    }
    autoFillAnchors(true);
    persistSettings();
    const n = document.getElementById('saveNotice');
    if (n) {
      n.textContent = '✓ pick anchors reset from loaded data';
      setTimeout(() => { n.textContent = ''; }, 3000);
    }
  }


  // ── EDGE FINDER ──
  let edgeSortCol = 'edgeScore';
  let edgeSortDir = 'desc';
  let edgeCache = []; // cached edge data for re-sorting without recomputing
  let edgeProjectionCache = { key: '', data: null };
  let edgeProjectionDebug = null;

  function buildEdgeProjectionKey() {
    if (!loadedData || !loadedData.players) return '';
    const cfgKey = getSiteConfig()
      .map(s => `${s.key}:${s.include ? 1 : 0}:${s.max}:${s.weight}:${s.tep ? 1 : 0}`)
      .join('|');
    return [
      loadedData.scrapeTimestamp || loadedData.date || '',
      Object.keys(loadedData.players || {}).length,
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
  }

  function clampEdgeValue(n, lo, hi) {
    if (!isFinite(n)) return lo;
    return Math.max(lo, Math.min(hi, n));
  }

  function rankMapFromSorted(items, valueKey) {
    const map = new Map();
    let prev = null;
    let prevRank = 0;
    items.forEach((item, idx) => {
      const v = Number(item?.[valueKey]);
      const same = prev !== null && isFinite(v) && isFinite(prev) && v === prev;
      const rank = same ? prevRank : (idx + 1);
      map.set(item.name, rank);
      prev = v;
      prevRank = rank;
    });
    return map;
  }

  function rankToPercentile(rank, total) {
    if (!Number.isFinite(rank) || !Number.isFinite(total) || total <= 0) return 0;
    if (total <= 1) return 1;
    return 1 - ((rank - 1) / (total - 1));
  }

  function projectPercentileToCurve(sortedValuesDesc, percentile) {
    const vals = (Array.isArray(sortedValuesDesc) ? sortedValuesDesc : [])
      .map(v => Number(v))
      .filter(v => isFinite(v) && v > 0);
    if (!vals.length) return null;
    if (vals.length === 1) return vals[0];

    const pct = clampEdgeValue(Number(percentile), 0, 1);
    const idx = (1 - pct) * (vals.length - 1);
    const lo = Math.max(0, Math.min(vals.length - 1, Math.floor(idx)));
    const hi = Math.max(0, Math.min(vals.length - 1, Math.ceil(idx)));
    if (lo === hi) return vals[lo];
    const t = idx - lo;
    return vals[lo] + ((vals[hi] - vals[lo]) * t);
  }

  function edgeAssetClassFor(name, pos) {
    if (parsePickToken(name)) return 'pick';
    const p = String(pos || '').toUpperCase();
    if (IDP_POSITIONS.has(p)) return 'idp';
    return 'offense';
  }

  function edgeMarketSource(assetClass) {
    if (assetClass === 'idp') return { key: 'idpTradeCalc', label: 'IDP TC' };
    return { key: 'ktc', label: 'KTC' };
  }

  function confidenceLabelFromScore(score) {
    if (score >= 0.72) return 'HIGH';
    if (score >= 0.52) return 'MED';
    return 'LOW';
  }

  function computeEdgeConfidence(row, externalUniverseSize, comparable) {
    const assetClass = String(row?.assetClass || '').toLowerCase() || 'offense';
    const expectedSites = assetClass === 'idp' ? 3 : assetClass === 'pick' ? 2 : 8;
    const siteNorm = clampEdgeValue((Number(row.siteCount) || 0) / Math.max(1, expectedSites), 0, 1);
    const curveNorm = clampEdgeValue((Number(externalUniverseSize) - 20) / 180, 0, 1);
    const comparableBonus = comparable ? 0.2 : 0;
    const hasIdpTradeCalc = assetClass === 'idp'
      && String(row?.marketKey || '') === 'idpTradeCalc'
      && Number.isFinite(Number(row?.actualExternal))
      && Number(row.actualExternal) > 0;
    let score = (0.45 * siteNorm) + (0.35 * curveNorm) + comparableBonus;
    if (row.isFallbackOnly && !hasIdpTradeCalc) score -= 0.15;
    if (!comparable) score -= 0.10;
    score = clampEdgeValue(score, 0, 1);
    if (hasIdpTradeCalc) {
      score = Math.max(score, IDP_CONF_FLOOR_WITH_IDP_TC);
    }
    return {
      score,
      label: confidenceLabelFromScore(score),
      high: score >= 0.72 && (!row.isFallbackOnly || hasIdpTradeCalc) && (comparable || hasIdpTradeCalc),
    };
  }

  function buildEdgeProjectionLayer() {
    if (!loadedData || !loadedData.players) {
      return {
        rows: [],
        byName: new Map(),
        byNorm: new Map(),
        universes: { offense: [], idp: [], pick: [] },
        curves: { offense: [], idp: [], pick: [] },
      };
    }

    const rows = [];
    for (const [name, pData] of Object.entries(loadedData.players)) {
      const result = computeMetaValueForPlayer(name);
      const modelValue = Number(result?.metaValue);
      if (!isFinite(modelValue) || modelValue <= 0) continue;

      let pos = parsePickToken(name)
        ? 'PICK'
        : ((getPlayerPosition(name) || getRookiePosHint(name) || '').toUpperCase());
      if (!pos) pos = 'UNK';

      const assetClass = edgeAssetClassFor(name, pos);
      const market = edgeMarketSource(assetClass);
      const actualExternalRaw = Number((pData || {})[market.key]);
      const actualExternal = isFinite(actualExternalRaw) && actualExternalRaw > 0 ? actualExternalRaw : null;
      const idpSiteCount = ['idpTradeCalc', 'pffIdp', 'fantasyProsIdp']
        .reduce((n, k) => {
          const v = Number((pData || {})[k]);
          return n + ((isFinite(v) && v > 0) ? 1 : 0);
        }, 0);
      const rawSiteCount = Number(result?.siteCount || pData?._sites || 0) || 0;

      rows.push({
        name,
        pos,
        group: posGroup(pos),
        assetClass,
        marketKey: market.key,
        marketLabel: market.label,
        modelValue: Math.round(modelValue),
        actualExternal: actualExternal != null ? Math.round(actualExternal) : null,
        siteCount: assetClass === 'idp' ? idpSiteCount : rawSiteCount,
        isFallbackOnly: !!pData?._fallbackValue,
        trend: parsePickToken(name) ? 0 : ((window.playerTrends && window.playerTrends[name]) || 0),
      });
    }

    const universes = {
      offense: rows.filter(r => r.assetClass === 'offense'),
      idp: rows.filter(r => r.assetClass === 'idp'),
      pick: rows.filter(r => r.assetClass === 'pick'),
    };
    const curves = { offense: [], idp: [], pick: [] };
    const minimumCurveSizes = { offense: 40, idp: 30, pick: 24 };

    Object.entries(universes).forEach(([klass, universe]) => {
      const modelSorted = [...universe].sort((a, b) => {
        if (b.modelValue !== a.modelValue) return b.modelValue - a.modelValue;
        return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
      });
      const modelRankAll = rankMapFromSorted(modelSorted, 'modelValue');
      const modelTotal = modelSorted.length;

      const externalSorted = universe
        .filter(r => isFinite(r.actualExternal) && r.actualExternal > 0)
        .sort((a, b) => {
          if (b.actualExternal !== a.actualExternal) return b.actualExternal - a.actualExternal;
          return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
        });
      const modelComparableSorted = [...externalSorted].sort((a, b) => {
        if (b.modelValue !== a.modelValue) return b.modelValue - a.modelValue;
        return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
      });
      const modelRankComparable = rankMapFromSorted(modelComparableSorted, 'modelValue');
      const modelComparableTotal = modelComparableSorted.length;
      const externalRank = rankMapFromSorted(externalSorted, 'actualExternal');
      const externalCurveValues = externalSorted.map(r => Number(r.actualExternal));
      curves[klass] = externalCurveValues;

      const curveTooSmall = externalCurveValues.length < (minimumCurveSizes[klass] || 20);
      for (const row of universe) {
        const mRankAll = modelRankAll.get(row.name) || modelTotal;
        const mRankComparable = modelRankComparable.get(row.name) || null;
        // Use model percentile within the same external-covered universe to avoid one-way
        // bias when many internal rows are missing external market values.
        const mRank = mRankComparable || mRankAll;
        const mPct = rankToPercentile(
          mRank,
          mRankComparable ? modelComparableTotal : modelTotal
        );
        const projectedRaw = curveTooSmall ? null : projectPercentileToCurve(externalCurveValues, mPct);
        const projectedExternal = (isFinite(projectedRaw) && projectedRaw > 0) ? Math.round(projectedRaw) : null;
        const eRank = externalRank.get(row.name) || null;
        const comparable = (
          !curveTooSmall
          && isFinite(row.actualExternal)
          && row.actualExternal > 0
          && isFinite(projectedExternal)
          && projectedExternal > 0
        );
        const valueEdge = comparable ? (projectedExternal - row.actualExternal) : null;
        const edgePct = comparable ? ((valueEdge / row.actualExternal) * 100) : null;
        const rankEdge = comparable && eRank ? (eRank - mRank) : null;
        const conf = computeEdgeConfidence(row, externalCurveValues.length, comparable);

        const absPct = Math.abs(Number(edgePct) || 0);
        const absVal = Math.abs(Number(valueEdge) || 0);
        const valueThreshold = Math.max(120, (Number(row.actualExternal) || 0) * 0.04);
        let signal = 'HOLD';
        if (comparable && conf.score >= 0.45 && absPct >= MIN_EDGE_PCT && absVal >= valueThreshold) {
          signal = valueEdge > 0 ? 'BUY' : 'SELL';
        }

        row.modelRank = mRank;
        row.externalRank = eRank;
        row.modelPercentile = mPct;
        row.projectedExternal = projectedExternal;
        row.valueEdge = valueEdge;
        row.edgePct = edgePct;
        row.rankEdge = rankEdge;
        row.absValueEdge = Math.abs(Number(valueEdge) || 0);
        row.absRankEdge = Math.abs(Number(rankEdge) || 0);
        row.edgeScore = (
          (row.absValueEdge * 1_000_000) +
          (row.absRankEdge * 1_000) +
          Math.abs(Number(edgePct) || 0)
        );
        row.comparable = comparable;
        row.curveSize = externalCurveValues.length;
        row.curveTooSmall = curveTooSmall;
        row.confidenceScore = conf.score;
        row.confidenceLabel = conf.label;
        row.isHighConfidence = conf.high;
        row.signal = signal;
        // Legacy sign convention for existing call-sites.
        // positive = SELL, negative = BUY.
        row.pctDiff = comparable ? (-1 * edgePct) : null;
      }
    });

    const byName = new Map(rows.map(r => [r.name, r]));
    const byNorm = new Map(rows.map(r => [normalizeForLookup(r.name), r]));

    const mkCurve = (universe, key) => {
      const sorted = [...(universe || [])]
        .filter(r => isFinite(r[key]) && Number(r[key]) > 0)
        .sort((a, b) => Number(b[key]) - Number(a[key]));
      return sorted.map((r, idx) => ({
        name: r.name,
        value: Number(r[key]),
        rank: idx + 1,
        percentile: rankToPercentile(idx + 1, sorted.length),
      }));
    };
    edgeProjectionDebug = {
      offenseExternalCurve: mkCurve(universes.offense, 'actualExternal'),
      idpExternalCurve: mkCurve(universes.idp, 'actualExternal'),
      pickExternalCurve: mkCurve(universes.pick, 'actualExternal'),
      offenseModelUniverse: mkCurve(universes.offense, 'modelValue'),
      idpModelUniverse: mkCurve(universes.idp, 'modelValue'),
      pickModelUniverse: mkCurve(universes.pick, 'modelValue'),
      generatedAt: new Date().toISOString(),
    };
    window.edgeProjectionDebug = edgeProjectionDebug;

    return { rows, byName, byNorm, universes, curves };
  }

  function ensureEdgeProjectionLayer() {
    const key = buildEdgeProjectionKey();
    if (!key) {
      edgeProjectionCache = { key: '', data: null };
      return null;
    }
    if (edgeProjectionCache.key === key && edgeProjectionCache.data) {
      return edgeProjectionCache.data;
    }
    const data = buildEdgeProjectionLayer();
    edgeProjectionCache = { key, data };
    return data;
  }

  function rowMatchesEdgePosFilter(row, posFilter) {
    if (!isBuysSellsEligibleAsset(row)) return false;
    const p = String(row?.pos || '').toUpperCase();
    if (posFilter === 'ALL') return true;
    if (posFilter === 'OFF') return row.assetClass === 'offense';
    if (posFilter === 'IDP') return row.assetClass === 'idp';
    if (posFilter === 'DL') return ['DL', 'DE', 'DT', 'EDGE', 'NT'].includes(p);
    if (posFilter === 'DB') return ['DB', 'CB', 'S', 'FS', 'SS'].includes(p);
    return p === posFilter;
  }

  function isBuysSellsEligibleAsset(row) {
    if (!row || typeof row !== 'object') return false;
    if (String(row.assetClass || '').toLowerCase() === 'pick') return false;
    if (String(row.pos || '').toUpperCase() === 'PICK') return false;
    const name = String(row.name || '').trim();
    if (name && parsePickToken(name)) return false;
    return true;
  }

  function normalizeEdgePosFilter(rawPosFilter) {
    const next = String(rawPosFilter || 'ALL').toUpperCase();
    const allowed = new Set(['ALL', 'OFF', 'IDP', 'QB', 'RB', 'WR', 'TE', 'LB', 'DL', 'DB']);
    return allowed.has(next) ? next : 'ALL';
  }

  function buildEdgeTable() {
    if (!loadedData || !loadedData.players) {
      document.getElementById('edgeSummary').textContent = 'Tap Refresh Values to load player data first.';
      document.getElementById('edgeBody').innerHTML = '';
      renderEdgeCardsInto('edgeMobileList', [], { emptyText: 'Tap Refresh Values to load edge signals.' });
      return;
    }

    computeSiteStats(); // ensure z-score stats are fresh
    const projection = ensureEdgeProjectionLayer();
    if (!projection) {
      document.getElementById('edgeSummary').textContent = 'Unable to compute edge projection data.';
      document.getElementById('edgeBody').innerHTML = '';
      renderEdgeCardsInto('edgeMobileList', [], { emptyText: 'Unable to compute edge projection data.' });
      return;
    }

    // Filters
    const posFilterEl = document.getElementById('edgePosFilter');
    const posFilter = normalizeEdgePosFilter(posFilterEl?.value || 'ALL');
    if (posFilterEl && posFilterEl.value !== posFilter) posFilterEl.value = posFilter;
    const requestedRosterFilter = document.getElementById('edgeRosterFilter')?.value || 'ALL';
    const dirFilter = document.getElementById('edgeDirFilter')?.value || 'ALL';
    const minMarket = parseFloat(document.getElementById('edgeMinMeta')?.value) || 0;
    const highConfidenceOnly = !!document.getElementById('edgeHighConfidence')?.checked;

    // Get my roster + league roster sets (players + picks)
    const myTeamName = document.getElementById('rosterMyTeam')?.value || '';
    const myTeam = sleeperTeams.find(t => t.name === myTeamName);
    let rosterFilter = requestedRosterFilter;
    if ((requestedRosterFilter === 'MINE' || requestedRosterFilter === 'LEAGUE') && !myTeam) {
      rosterFilter = 'ALL';
      const rosterFilterEl = document.getElementById('edgeRosterFilter');
      if (rosterFilterEl) rosterFilterEl.value = 'ALL';
    }
    const addTeamAssets = (set, team) => {
      (team?.players || []).forEach(p => set.add(String(p).toLowerCase()));
      (team?.picks || []).forEach(p => set.add(String(p).toLowerCase()));
    };
    const myAssetSet = new Set();
    if (myTeam) addTeamAssets(myAssetSet, myTeam);
    const allRosteredSet = new Set();
    sleeperTeams.forEach(t => addTeamAssets(allRosteredSet, t));

    let edgeData = projection.rows.filter(r => r.comparable && isBuysSellsEligibleAsset(r));
    edgeData = edgeData.filter(r => rowMatchesEdgePosFilter(r, posFilter));
    edgeData = edgeData.filter(r => Number(r.actualExternal || 0) >= minMarket);
    if (highConfidenceOnly) edgeData = edgeData.filter(r => r.isHighConfidence);

    edgeData = edgeData.map(r => ({
      ...r,
      isOnMyRoster: myAssetSet.has(r.name.toLowerCase()),
      isRostered: allRosteredSet.has(r.name.toLowerCase()),
    }));

    if (rosterFilter === 'MINE') edgeData = edgeData.filter(r => r.isOnMyRoster);
    if (rosterFilter === 'LEAGUE') edgeData = edgeData.filter(r => (r.isRostered && !r.isOnMyRoster));
    if (rosterFilter === 'AVAILABLE') edgeData = edgeData.filter(r => !r.isRostered);

    if (dirFilter === 'BUY') edgeData = edgeData.filter(r => r.signal === 'BUY');
    else if (dirFilter === 'SELL') edgeData = edgeData.filter(r => r.signal === 'SELL');
    else edgeData = edgeData.filter(r => r.signal === 'BUY' || r.signal === 'SELL');

    edgeCache = edgeData;
    sortEdgeData();
    renderEdgeTable();

    const buys = edgeData.filter(p => p.signal === 'BUY').length;
    const sells = edgeData.filter(p => p.signal === 'SELL').length;
    const myBuys = edgeData.filter(p => p.signal === 'BUY' && p.isOnMyRoster).length;
    const mySells = edgeData.filter(p => p.signal === 'SELL' && p.isOnMyRoster).length;
    let summary = `${edgeData.length} players scanned — ${buys} undervalued (BUY), ${sells} overvalued (SELL)`;
    if (highConfidenceOnly) summary += ' · showing high-confidence edges only';
    if (requestedRosterFilter !== rosterFilter) summary += ' · select your team to filter to your roster';
    if (myTeamName) summary += ` · On your roster: ${myBuys} buys, ${mySells} sells`;
    document.getElementById('edgeSummary').textContent = summary;

    // Summary cards: top buys and sells on your roster
    const cardsEl = document.getElementById('edgeSummaryCards');
    const buysEl = document.getElementById('edgeTopBuys');
    const sellsEl = document.getElementById('edgeTopSells');
    if (cardsEl && buysEl && sellsEl && myTeamName) {
      const myBuyList = edgeData
        .filter(p => p.isOnMyRoster && p.signal === 'BUY')
        .sort((a, b) => b.valueEdge - a.valueEdge)
        .slice(0, 5);
      const mySellList = edgeData
        .filter(p => p.isOnMyRoster && p.signal === 'SELL')
        .sort((a, b) => a.valueEdge - b.valueEdge)
        .slice(0, 5);

      const POS_C = {
        QB:'#e74c3c',RB:'#27ae60',WR:'#3498db',TE:'#e67e22',
        LB:'#9b59b6',DL:'#9b59b6',DE:'#9b59b6',DT:'#9b59b6',EDGE:'#9b59b6',
        CB:'#16a085',S:'#16a085',DB:'#16a085',PICK:'#f39c12',
      };
      const renderList = (list, isBuy) => {
        if (!list.length) return '<span style="color:var(--subtext);font-size:0.68rem;">None on your roster</span>';
        return list.map(p => {
          const posC = POS_C[(p.pos||'').toUpperCase()] || 'var(--subtext)';
          const sign = isBuy ? '+' : '';
          const edgeVal = Math.round(Number(p.valueEdge || 0));
          const edgePct = Number(p.edgePct || 0);
          const pctStr = `${edgePct > 0 ? '+' : ''}${edgePct.toFixed(0)}%`;
          return `<div class="edge-summary-item ${isBuy ? 'edge-summary-buy' : 'edge-summary-sell'}">
            <span style="display:flex;align-items:center;gap:5px;">
              <span style="color:${posC};font-family:var(--mono);font-size:0.58rem;font-weight:700;width:26px;">${p.pos}</span>
              <span class="edge-summary-item-name">${p.name}</span>
            </span>
            <span class="edge-summary-item-val">${sign}${edgeVal.toLocaleString()} <span style="font-size:0.60rem;opacity:0.7;">(${pctStr})</span></span>
          </div>`;
        }).join('');
      };
      buysEl.innerHTML = renderList(myBuyList, true);
      sellsEl.innerHTML = renderList(mySellList, false);
      cardsEl.style.display = (myBuyList.length || mySellList.length) ? 'block' : 'none';
    } else if (cardsEl) {
      cardsEl.style.display = 'none';
    }

    // Build league-wide edge map
    buildLeagueEdge();
  }

  function sortEdgeData() {
    const col = edgeSortCol;
    const dir = edgeSortDir === 'asc' ? 1 : -1;
    edgeCache.sort((a, b) => {
      const va = a?.[col];
      const vb = b?.[col];
      const sa = String(va ?? '').trim();
      const sb = String(vb ?? '').trim();
      const aEmpty = !sa || sa === '—' || sa === '-' || /^n\/a$/i.test(sa);
      const bEmpty = !sb || sb === '—' || sb === '-' || /^n\/a$/i.test(sb);
      if (aEmpty && bEmpty) {
        return String(a?.name || '').localeCompare(String(b?.name || ''), undefined, { numeric: true, sensitivity: 'base' });
      }
      if (aEmpty) return 1;
      if (bEmpty) return -1;

      if (typeof va === 'string' || typeof vb === 'string') {
        return dir * String(va || '').localeCompare(String(vb || ''), undefined, { numeric: true, sensitivity: 'base' });
      }
      const na = Number(va);
      const nb = Number(vb);
      if (!isFinite(na) && !isFinite(nb)) {
        return String(a?.name || '').localeCompare(String(b?.name || ''), undefined, { numeric: true, sensitivity: 'base' });
      }
      if (!isFinite(na)) return 1;
      if (!isFinite(nb)) return -1;
      if (na === nb) {
        return String(a?.name || '').localeCompare(String(b?.name || ''), undefined, { numeric: true, sensitivity: 'base' });
      }
      return dir * (na - nb);
    });
  }

  function handleEdgeSort(col) {
    if (edgeSortCol === col) {
      edgeSortDir = edgeSortDir === 'desc' ? 'asc' : 'desc';
    } else {
      edgeSortCol = col;
      edgeSortDir = 'desc';
    }
    sortEdgeData();
    renderEdgeTable();
  }

  function renderEdgeTable() {
    const data = edgeCache;
    const hdr = document.getElementById('edgeHeader');
    const tbody = document.getElementById('edgeBody');
    if (!hdr || !tbody) return;

    const cols = [
      { key: 'name', label: 'Player', tip: 'Player or pick name' },
      { key: 'pos', label: 'Pos', tip: 'Position' },
      { key: 'marketLabel', label: 'Source', tip: 'Which market source is used for comparison' },
      { key: 'actualExternal', label: 'Market Val', tip: 'Current value on the selected market source' },
      { key: 'projectedExternal', label: 'Projected', tip: 'Projected market value based on trend curve' },
      { key: 'modelValue', label: 'Our Value', tip: 'Our composite model value (league-adjusted)' },
      { key: 'externalRank', label: 'Market Rank', tip: 'Rank on the selected market source' },
      { key: 'modelRank', label: 'Our Rank', tip: 'Rank on our composite model' },
      { key: 'valueEdge', label: 'Value Edge', tip: 'Difference between our value and the market (positive = we value higher)' },
      { key: 'edgePct', label: 'Edge %', tip: 'Value edge as a percentage of market value' },
      { key: 'rankEdge', label: 'Rank Edge', tip: 'Rank difference (positive = we rank higher than market)' },
      { key: 'confidenceScore', label: 'Confidence', tip: 'How reliable the edge signal is (based on source count and data coverage)' },
      { key: 'signal', label: 'Signal', tip: 'BUY = undervalued by market, SELL = overvalued by market, HOLD = fair value' },
    ];
    hdr.innerHTML = cols.map(c => {
      const cls = edgeSortCol === c.key ? (edgeSortDir === 'asc' ? 'sorted-asc' : 'sorted-desc') : '';
      return `<th class="${cls}" title="${c.tip}" onclick="handleEdgeSort('${c.key}')">${c.label}</th>`;
    }).join('');

    if (!data.length) {
      tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--subtext);padding:16px;">No assets match current filters.</td></tr>';
      renderEdgeCardsInto('edgeMobileList', [], { emptyText: 'No assets match current edge filters.' });
      return;
    }

    const POS_COLORS = {
      QB: '#e74c3c', RB: '#27ae60', WR: '#3498db', TE: '#e67e22',
      LB: '#9b59b6', DL: '#9b59b6', DE: '#9b59b6', DT: '#9b59b6', EDGE: '#9b59b6',
      CB: '#16a085', S: '#16a085', DB: '#16a085', PICK: '#f39c12',
    };

    let html = '';
    for (const p of data.slice(0, 250)) {
      const posColor = POS_COLORS[(p.pos||'').toUpperCase()] || 'var(--subtext)';
      const valueEdge = Number(p.valueEdge || 0);
      const edgePct = Number(p.edgePct || 0);
      const rankEdge = Number(p.rankEdge || 0);
      const valueColor = valueEdge > 0 ? 'var(--green)' : (valueEdge < 0 ? 'var(--red)' : 'var(--subtext)');
      const pctClass = edgePct >= 0 ? 'edge-pct-buy' : 'edge-pct-sell';
      const pctSign = edgePct > 0 ? '+' : '';
      const rankColor = rankEdge > 0 ? 'var(--green)' : (rankEdge < 0 ? 'var(--red)' : 'var(--subtext)');
      const rowClass = 'edge-row' + (p.isOnMyRoster ? ' edge-mine' : '');
      let signalBadge = `<span class="edge-badge edge-badge-buy">BUY</span>`;
      if (p.signal === 'SELL') signalBadge = `<span class="edge-badge edge-badge-sell">SELL</span>`;
      if (p.signal === 'HOLD') signalBadge = `<span class="edge-badge" style="background:rgba(140,140,140,0.18);color:var(--subtext);">HOLD</span>`;
      const confColor = p.confidenceLabel === 'HIGH' ? 'var(--green)' : (p.confidenceLabel === 'MED' ? 'var(--amber)' : 'var(--subtext)');

      html += `<tr class="${rowClass}">`;
      html += `<td class="edge-name">${p.name}${p.isOnMyRoster ? ' <span style="color:var(--cyan);font-size:0.6rem;">★</span>' : ''}</td>`;
      html += `<td class="edge-pos" style="color:${posColor}">${p.pos}</td>`;
      html += `<td class="edge-val">${p.marketLabel}</td>`;
      html += `<td class="edge-val">${Number(p.actualExternal || 0).toLocaleString()}</td>`;
      html += `<td class="edge-val">${Number(p.projectedExternal || 0).toLocaleString()}</td>`;
      html += `<td class="edge-val">${Number(p.modelValue || 0).toLocaleString()}</td>`;
      html += `<td class="edge-val">${p.externalRank || '—'}</td>`;
      html += `<td class="edge-val">${p.modelRank || '—'}</td>`;
      html += `<td class="edge-val" style="color:${valueColor};font-weight:600;">${valueEdge > 0 ? '+' : ''}${Math.round(valueEdge).toLocaleString()}</td>`;
      html += `<td class="edge-pct ${pctClass}">${pctSign}${edgePct.toFixed(1)}%</td>`;
      html += `<td class="edge-val" style="color:${rankColor};font-weight:600;">${rankEdge > 0 ? '+' : ''}${Math.round(rankEdge)}</td>`;
      const confTip = p.confidenceLabel === 'HIGH'
        ? `High confidence: ${p.siteCount} sources, strong data coverage`
        : p.confidenceLabel === 'MED'
          ? `Moderate confidence: ${p.siteCount} sources, some data gaps`
          : `Low confidence: ${p.siteCount || 'few'} sources, limited data — treat with caution`;
      html += `<td class="edge-val" style="color:${confColor};font-weight:600;" title="${confTip}">${p.confidenceLabel}</td>`;
      html += `<td>${signalBadge}</td>`;
      html += `</tr>`;
    }
    tbody.innerHTML = html;
    renderEdgeCardsInto('edgeMobileList', data, { limit: 60, emptyText: 'No assets match current edge filters.' });
  }

  // Helper: compute edge for a single player (used in calculator rows)
  function getPlayerEdge(playerName) {
    const projection = ensureEdgeProjectionLayer();
    if (!projection) return null;
    const byName = projection.byName?.get(playerName);
    const row = byName || projection.byNorm?.get(normalizeForLookup(playerName));
    if (!isBuysSellsEligibleAsset(row)) return null;
    if (!row || !row.comparable) return null;
    return {
      market: row.actualExternal,
      projectedMarket: row.projectedExternal,
      model: row.modelValue,
      externalRank: row.externalRank,
      modelRank: row.modelRank,
      rankEdge: row.rankEdge,
      valueEdge: row.valueEdge,
      edgePct: row.edgePct,     // positive = BUY
      pctDiff: row.pctDiff,     // legacy sign: positive = SELL
      signal: row.signal,
      confidenceLabel: row.confidenceLabel,
      confidenceScore: row.confidenceScore,
      externalSource: row.marketLabel,
      // Legacy compatibility fields:
      ktc: row.actualExternal,
      meta: row.modelValue,
    };
  }


  function normalizeTradeTimestampMs(ts) {
    const n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return null;
    return n < 1_000_000_000_000 ? n * 1000 : n;
  }

  function getTradeHistoryWindowDays() {
    const cfg = Number(loadedData?.sleeper?.tradeWindowDays);
    if (Number.isFinite(cfg) && cfg >= 30) return Math.round(cfg);
    return 365;
  }

  function filterTradesToRollingWindow(trades) {
    if (!Array.isArray(trades) || !trades.length) return [];
    const days = getTradeHistoryWindowDays();
    const cutoffMs = Date.now() - (days * 24 * 60 * 60 * 1000);
    return trades.filter(t => {
      const ts = normalizeTradeTimestampMs(t?.timestamp);
      return Number.isFinite(ts) && ts >= cutoffMs;
    });
  }

  let tradeHistoryRenderCache = [];

  function gradeTradeHistorySide(pct, isWinner) {
    if (pct < 3) return { grade: 'A', color: 'var(--green)', label: 'Fair trade' };
    if (isWinner) {
      if (pct < 8) return { grade: 'A', color: 'var(--green)', label: 'Slight win' };
      if (pct < 15) return { grade: 'A-', color: 'var(--green)', label: 'Good win' };
      if (pct < 25) return { grade: 'B+', color: '#2ecc71', label: 'Clear win' };
      return { grade: 'A+', color: '#00ff88', label: 'Big win' };
    }
    if (pct < 8) return { grade: 'B+', color: '#2ecc71', label: 'Slight overpay' };
    if (pct < 15) return { grade: 'B', color: 'var(--amber)', label: 'Overpay' };
    if (pct < 25) return { grade: 'C', color: '#e67e22', label: 'Bad deal' };
    if (pct < 40) return { grade: 'D', color: 'var(--red)', label: 'Robbery' };
    return { grade: 'F', color: '#ff4444', label: 'Fleeced' };
  }

  function analyzeSleeperTradeHistory() {
    const windowDays = getTradeHistoryWindowDays();
    if (!loadedData || !loadedData.sleeper?.trades?.length) {
      return { windowDays, analyzed: [], teamScores: {} };
    }
    const trades = filterTradesToRollingWindow(loadedData.sleeper.trades);
    if (!trades.length) return { windowDays, analyzed: [], teamScores: {} };

    const alpha = parseFloat(document.getElementById('alphaSlider')?.value) || 1.075;
    const teamScores = {}; // teamName → { won: count, lost: count, totalGain: number }
    const analyzed = [];

    for (const trade of trades) {
      const ts = normalizeTradeTimestampMs(trade.timestamp);
      const date = ts ? new Date(ts).toLocaleDateString() : '?';
      const sides = [];

      for (const side of trade.sides) {
        let linearTotal = 0, weightedTotal = 0, items = [];
        for (const rawItem of getTradeSideItemLabels(side?.got)) {
          const tiv = getTradeItemValue(rawItem);
          const val = tiv.metaValue;
          const safeVal = Number.isFinite(val) ? Math.max(0, Number(val)) : 0;
          const itemName = tiv.displayName || rawItem;
          const pos = tiv.isPick ? '' : (getPlayerPosition(tiv.resolvedName || itemName) || '');
          linearTotal += safeVal;
          weightedTotal += Math.pow(Math.max(safeVal, 1), alpha);
          items.push({ name: itemName, val: Math.round(safeVal), pos, isPick: tiv.isPick });
        }
        sides.push({ team: side.team, linear: linearTotal, weighted: weightedTotal, items });
      }

      // Determine winner using stud-adjusted values
      sides.sort((a, b) => b.weighted - a.weighted);
      const winner = sides[0];
      const loser = sides.length > 1 ? sides[sides.length - 1] : null;
      const pctGap = loser && winner.weighted > 0 ? ((winner.weighted - loser.weighted) / winner.weighted) * 100 : 0;

      const winnerGrade = gradeTradeHistorySide(pctGap, true);
      const loserGrade = loser ? gradeTradeHistorySide(pctGap, false) : null;

      // Track team scores
      for (const s of sides) {
        if (!teamScores[s.team]) teamScores[s.team] = { won: 0, lost: 0, totalGain: 0, trades: 0 };
        teamScores[s.team].trades++;
        if (s === winner && pctGap >= 3) {
          teamScores[s.team].won++;
          teamScores[s.team].totalGain += (winner.weighted - (loser ? loser.weighted : 0));
        } else if (s === loser && pctGap >= 3) {
          teamScores[s.team].lost++;
          teamScores[s.team].totalGain -= (winner.weighted - loser.weighted);
        }
      }

      analyzed.push({ trade, date, sides, winner, loser, pctGap, winnerGrade, loserGrade });
    }

    return { windowDays, analyzed, teamScores };
  }

  function setTradeTeamFilterByName(selectId, teamName) {
    const el = document.getElementById(selectId);
    if (!el || !teamName) return;
    const match = Array.from(el.options || []).find(opt => String(opt.value || '') === String(teamName || ''));
    if (match) el.value = String(teamName);
  }

  function resolveHistoricalTradeAssetForBuilder(rawAsset) {
    const label = normalizeTradeAssetLabel(rawAsset);
    if (!label) return { label: '', resolved: false, isPick: false };

    const pickInfo = parsePickToken(label);
    if (pickInfo) {
      const value = getTradeItemValue(label);
      const resolved = Number(value?.metaValue || 0) > 0;
      return { label, resolved, isPick: true };
    }

    const canonicalPlayer = getCanonicalPlayerName(label) || label;
    const value = getTradeItemValue(canonicalPlayer);
    const resolved = Number(value?.metaValue || 0) > 0;
    return { label: canonicalPlayer, resolved, isPick: false };
  }

  function hydrateHistoricalTradeIntoBuilder(entry) {
    const trade = entry?.trade || entry;
    const sidesRaw = Array.isArray(trade?.sides) ? trade.sides.slice() : [];
    if (!sidesRaw.length) return { ok: false, error: 'No sides found in selected historical trade.' };

    const selectedTeam = String(document.getElementById('tradeTeamFilter')?.value || '');
    if (selectedTeam) {
      const idx = sidesRaw.findIndex(s => String(s?.team || '') === selectedTeam);
      if (idx > 0) {
        const [mySide] = sidesRaw.splice(idx, 1);
        sidesRaw.unshift(mySide);
      }
    }

    const mappedSides = sidesRaw.slice(0, 3).map(side => {
      const assetsRaw = getTradeSideItemLabels(side?.got);
      const assets = [];
      const unresolved = [];
      for (const rawAsset of assetsRaw) {
        const resolved = resolveHistoricalTradeAssetForBuilder(rawAsset);
        if (!resolved.label) continue;
        assets.push(resolved.label);
        if (!resolved.resolved) unresolved.push(resolved.label);
      }
      return {
        team: String(side?.team || ''),
        assets,
        unresolved,
      };
    });

    const sideA = mappedSides[0]?.assets || [];
    const sideB = mappedSides[1]?.assets || [];
    const sideC = mappedSides[2]?.assets || [];
    const hasSideC = sideC.length > 0;

    if (!sideA.length && !sideB.length && !hasSideC) {
      return { ok: false, error: 'Could not map any assets from that trade into the builder.' };
    }

    const multiToggle = document.getElementById('multiTeamToggle');
    if (multiToggle) {
      if (hasSideC && !multiToggle.checked) {
        multiToggle.checked = true;
        toggleMultiTeam(true);
      } else if (!hasSideC && multiToggle.checked) {
        multiToggle.checked = false;
        toggleMultiTeam(false);
      }
    }

    populateTradeSide('sideABody', 'A', sideA);
    populateTradeSide('sideBBody', 'B', sideB);
    populateTradeSide('sideCBody', 'C', hasSideC ? sideC : []);

    setTradeTeamFilterByName('teamFilterA', mappedSides[0]?.team || '');
    setTradeTeamFilterByName('teamFilterB', mappedSides[1]?.team || '');
    setTradeTeamFilterByName('teamFilterC', mappedSides[2]?.team || '');
    updateTeamFilter();
    recalculate();
    renderMobileTradeWorkspace();
    syncMobileTradeControlState();

    const unresolved = mappedSides.flatMap((s, idx) => {
      const sideLabel = String.fromCharCode(65 + idx);
      return (s.unresolved || []).map(name => `${sideLabel}: ${name}`);
    });

    return {
      ok: true,
      unresolved,
      unresolvedCount: unresolved.length,
      importedA: sideA.length,
      importedB: sideB.length,
      importedC: sideC.length,
    };
  }

  function openHistoricalTradeInBuilder(index) {
    const idx = Number(index);
    if (!Number.isInteger(idx) || idx < 0 || idx >= tradeHistoryRenderCache.length) {
      alert('That historical trade is no longer in the current view. Refresh and try again.');
      return;
    }

    switchTab('calculator', { ensureTopOnMobile: true });
    const result = hydrateHistoricalTradeIntoBuilder(tradeHistoryRenderCache[idx]);
    if (!result?.ok) {
      alert(result?.error || 'Unable to load that historical trade into the builder.');
      return;
    }

    if (typeof setMobileKtcImportFeedback === 'function') {
      if (result.unresolvedCount > 0) {
        setMobileKtcImportFeedback(
          `Loaded trade with ${result.unresolvedCount} unresolved asset(s).`,
          'error'
        );
      } else {
        setMobileKtcImportFeedback('Loaded historical trade into builder.', 'success');
      }
    }

    if (result.unresolvedCount > 0) {
      console.warn('[Trade History] Unresolved assets while loading historical trade:', result.unresolved);
    }
  }
