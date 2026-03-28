/*
 * Runtime Module: 50-bootstrap.js
 * Boot sequence and startup wiring.
 * Extracted from legacy monolithic inline runtime to keep live behavior intact.
 */

  // ── BOOT ──
  document.addEventListener('DOMContentLoaded', async () => {
    perfMark('dom_content_loaded');
    initGlobalTableSorting();
    initSiteConfig();
    initAnchors();
    loadSettings();
    try {
      const savedQuickSide = localStorage.getItem(MOBILE_RANKINGS_QUICK_SIDE_KEY);
      if (savedQuickSide) rankingsQuickTradeSide = (String(savedQuickSide).toUpperCase() === 'A') ? 'A' : 'B';
    } catch (_) {}
    updateRankingsQuickTradeSideButtons();
    hydrateMobilePowerModeFromStorage();
    buildPlayersTable();
    populateSavedTrades();
    updateProfileBar();

    // Try server API first, then lazily load embedded data only if needed.
    const fromServer = await fetchFromServer();
    if (!fromServer) {
      const embeddedReady = await ensureEmbeddedDataLoaded();
      if (embeddedReady && loadJsonData(window.DYNASTY_DATA)) {
        const btn = document.getElementById('loadDataBtn');
        if (btn) btn.textContent = '✓ Auto-loaded';
      }
    }
    if (loadedData?.players) {
      perfMark('first_data_loaded');
      perfMeasure('dom_to_first_data_ms', 'dom_content_loaded', 'first_data_loaded');
    }
    // Ensure hardcoded league profile exists after first successful data load.
    if (loadedData?.sleeper) {
      ensureHardcodedLeagueProfile();
    }

    // "Refresh Values" always triggers the live pipeline via triggerScrape().
    // Manual file import is a separate action and is never wired to this button.
    if (serverMode) {
      // Already connected — start status polling
      setInterval(updateServerStatus, 60000);
    } else {
      // Not yet connected — button still says "Refresh Values" and will attempt
      // the server call when clicked, showing a clear error if unreachable.
      const btn = document.getElementById('loadDataBtn');
      if (btn) btn.textContent = '🔄 Refresh Values';
    }

    const gsInput = document.getElementById('globalSearchInput');
    if (gsInput) {
      gsInput.addEventListener('input', (e) => renderGlobalSearchResults(e.target.value));
      gsInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          closeGlobalSearch();
        }
        if (e.key === 'Enter') {
          const firstBtn = document.querySelector('#globalSearchBody .gs-actions .mobile-chip-btn.primary');
          if (firstBtn) {
            e.preventDefault();
            firstBtn.click();
          }
        }
      });
    }

    document.addEventListener('keydown', (e) => {
      const active = document.activeElement;
      const tag = String(active?.tagName || '').toUpperCase();
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || active?.isContentEditable;
      if (typing) return;
      if (e.key === '/') {
        e.preventDefault();
        openGlobalSearch();
      }
    });

    try {
      mobileMoreSection = normalizeMobileMoreSection(localStorage.getItem(MOBILE_MORE_SECTION_KEY) || mobileMoreSection);
      mobileMoreRosterView = normalizeMobileMoreRosterSubview(localStorage.getItem(MOBILE_MORE_ROSTER_VIEW_KEY) || mobileMoreRosterView);
      mobileMoreTradesView = normalizeMobileMoreTradesSubview(localStorage.getItem(MOBILE_MORE_TRADES_VIEW_KEY) || mobileMoreTradesView);
    } catch (_) {}

    window.addEventListener('resize', () => {
      if (isMobileViewport() && !['home', 'rookies', 'calculator', 'more'].includes(activeTabId)) {
        // Keep full legacy tab open on mobile for parity workflows.
        switchTab(activeTabId, { persist: false, allowLegacyMobile: true });
        return;
      }
      updateMobileChrome(activeTabId);
    });

    recalculate();
    perfMark('initial_recalculate_done');

    const isMobileInit = isMobileViewport();
    const preferredTab = String(localStorage.getItem(ACTIVE_TAB_KEY) || '').trim().toLowerCase();
    const urlTab = getInitialTabFromUrl();
    let initialTab;
    if (isMobileInit) {
      // Mobile product default: always land directly in Trade Calculator unless the URL explicitly asks otherwise.
      initialTab = urlTab || MOBILE_DEFAULT_LANDING_TAB;
    } else {
      initialTab = urlTab || preferredTab || 'calculator';
      if (['home', 'watch', 'more'].includes(initialTab)) initialTab = 'calculator';
    }
    const allowLegacyOnInit = isMobileInit
      && getMobilePowerModeEnabled()
      && !['home', 'rookies', 'calculator', 'more'].includes(initialTab);
    switchTab(initialTab, {
      persist: false,
      allowLegacyMobile: allowLegacyOnInit,
      ensureTopOnMobile: isMobileInit,
    });
    if (!postDataViewsHydrated) {
      renderMobileTradeWorkspace();
      updateMobileTradeTray();
      buildHomeHub();
      buildMoreHub();
    }
    perfMark('initial_tab_ready');
    perfMeasure('dom_to_initial_tab_ms', 'dom_content_loaded', 'initial_tab_ready');
    startupPerf.meta.mobileInit = !!isMobileInit;
    startupPerf.meta.initialTab = String(initialTab || '');
    startupPerf.meta.playerCount = Object.keys(loadedData?.players || {}).length;
  });
