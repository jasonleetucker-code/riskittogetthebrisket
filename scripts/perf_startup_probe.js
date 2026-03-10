const { spawn } = require('child_process');
const { chromium, devices } = require('playwright');

const BASE_URL = process.env.PERF_BASE_URL || 'http://127.0.0.1:8000';
const PYTHON_CMD = process.env.PYTHON_CMD || 'python';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForHealth(url, timeoutMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (res.ok) return true;
    } catch (_) {}
    await sleep(800);
  }
  return false;
}

async function getJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`GET ${url} failed: ${res.status}`);
  return res.json();
}

function formatDebugBlock(debug) {
  return [
    `[probe-debug] stage=${debug.stage || 'unknown'}`,
    `[probe-debug] dataStatusExists=${debug.dataStatusExists}`,
    `[probe-debug] dataStatusText=${JSON.stringify(debug.dataStatusText || '')}`,
    `[probe-debug] dataStatusOuterHtml=${JSON.stringify(debug.dataStatusOuterHtml || '')}`,
    `[probe-debug] switchTabExists=${debug.switchTabExists}`,
    `[probe-debug] openGlobalSearchForTradeExists=${debug.openGlobalSearchForTradeExists}`,
    `[probe-debug] playerCount=${debug.playerCount}`,
    `[probe-debug] payloadView=${JSON.stringify(debug.payloadView || '')}`,
  ].join('\n');
}

async function collectRuntimeDebug(page, stage = '') {
  return page.evaluate((currentStage) => {
    const runtimeData = window.loadedData || (typeof loadedData !== 'undefined' ? loadedData : null);
    const statusEl = document.getElementById('dataStatus');
    return {
      stage: currentStage,
      dataStatusExists: !!statusEl,
      dataStatusText: statusEl ? String(statusEl.textContent || '').trim() : '',
      dataStatusOuterHtml: statusEl ? String(statusEl.outerHTML || '') : '',
      switchTabExists: typeof window.switchTab === 'function',
      openGlobalSearchForTradeExists: typeof window.openGlobalSearchForTrade === 'function',
      playerCount: Object.keys(runtimeData?.players || {}).length,
      payloadView: runtimeData?.payloadView || '',
    };
  }, stage);
}

async function measureViewport({ name, contextOptions = {} }) {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext(contextOptions);
  const page = await context.newPage();
  let stage = 'init';

  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => {
    consoleErrors.push(String(err));
  });

  try {
    const start = Date.now();
    stage = 'goto';
    await page.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded' });

    // Authoritative runtime-data readiness gate.
    stage = 'runtime-data-ready';
    await page.waitForFunction(() => {
      const d = window.loadedData || (typeof loadedData !== 'undefined' ? loadedData : null);
      return !!(d && d.players && Object.keys(d.players).length > 50);
    }, { timeout: 120000 });
    const timeToRuntimeDataMs = Date.now() - start;

    // App-ready gate: runtime functions required for interaction are available.
    stage = 'app-ready';
    await page.waitForFunction(() => (
      typeof window.switchTab === 'function'
      && typeof window.openGlobalSearchForTrade === 'function'
    ), { timeout: 60000 });
    const timeToAppReadyMs = Date.now() - start;

    // Optional status diagnostics only (not a failure gate).
    const statusDebug = await page.evaluate(() => {
      const el = document.getElementById('dataStatus');
      const text = String(el?.textContent || '').trim();
      const broadReadyRegex = /players|loaded|live|ready|cached/i;
      return {
        exists: !!el,
        text,
        matchesBroadReadyText: broadReadyRegex.test(text),
      };
    });

    // Time to add one trade asset via real trade search flow.
    stage = 'trade-asset-add';
    await page.evaluate(() => {
      if (typeof window.switchTab === 'function') {
        window.switchTab('calculator', { persist: false, ensureTopOnMobile: true });
      }
      if (typeof window.clearPlayers === 'function') window.clearPlayers();
    });
    await page.waitForFunction(() => {
      const a = (window.getTradeSideAssets?.('A') || []).length;
      const b = (window.getTradeSideAssets?.('B') || []).length;
      const c = (window.getTradeSideAssets?.('C') || []).length;
      return a === 0 && b === 0 && c === 0;
    }, { timeout: 30000 });

    const samplePlayer = await page.evaluate(() => {
      const d = window.loadedData || (typeof loadedData !== 'undefined' ? loadedData : null);
      const names = Object.keys(d?.players || {});
      return names.find((n) => {
        if (typeof window.parsePickToken === 'function' && window.parsePickToken(n)) return false;
        return !/\b20\d{2}\b\s+(pick|round|[1-6]\.)/i.test(String(n));
      }) || names[0] || '';
    });
    if (!samplePlayer) throw new Error('No sample player available for trade add timing');
    const searchQuery = String(samplePlayer).slice(0, 6);

    await page.evaluate(() => {
      if (typeof window.openGlobalSearchForTrade === 'function') {
        window.openGlobalSearchForTrade('A');
      }
    });
    await page.waitForFunction(() => {
      const overlay = document.getElementById('globalSearchOverlay');
      const input = document.getElementById('globalSearchInput');
      return !!overlay && overlay.classList.contains('active') && !!input;
    }, { timeout: 30000 });

    await page.fill('#globalSearchInput', searchQuery);
    await page.waitForFunction(() => {
      const btn = document.querySelector('#globalSearchBody .gs-actions .mobile-chip-btn.primary');
      return !!btn;
    }, { timeout: 30000 });
    await page.click('#globalSearchBody .gs-actions .mobile-chip-btn.primary');
    await page.waitForFunction(() => {
      const rows = window.getTradeSideAssets?.('A') || [];
      return rows.length > 0;
    }, { timeout: 30000 });
    const timeToAddTradeAssetMs = Date.now() - start;

    // Time to first rankings rows.
    stage = 'rankings-rows';
    await page.evaluate(() => {
      if (typeof window.closeGlobalSearch === 'function') window.closeGlobalSearch();
      if (typeof window.switchTab === 'function') {
        window.switchTab('rookies', { persist: false, ensureTopOnMobile: true });
      }
    });
    await page.waitForFunction(() => {
      const desktopRows = document.querySelectorAll('#rookieBody tr').length;
      const mobileRows = document.querySelectorAll('#rankingsMobileList .mobile-row-card').length;
      return desktopRows > 0 || mobileRows > 0;
    }, { timeout: 60000 });
    const timeToFirstRankingsRowsMs = Date.now() - start;

    return {
      viewport: name,
      timeToRuntimeDataMs,
      timeToAppReadyMs,
      timeToAddTradeAssetMs,
      timeToFirstRankingsRowsMs,
      statusDebug,
      consoleErrorCount: consoleErrors.length,
      consoleErrors: consoleErrors.slice(0, 5),
    };
  } catch (err) {
    const debug = await collectRuntimeDebug(page, stage).catch((e) => ({
      stage,
      dataStatusExists: false,
      dataStatusText: '',
      dataStatusOuterHtml: '',
      switchTabExists: false,
      openGlobalSearchForTradeExists: false,
      playerCount: -1,
      payloadView: '',
      collectDebugError: String(e),
    }));
    const baseMsg = (err && err.message) ? err.message : String(err);
    const extra = formatDebugBlock(debug);
    throw new Error(`${baseMsg}\n${extra}`);
  } finally {
    await context.close();
    await browser.close();
  }
}

async function main() {
  const env = {
    ...process.env,
    FRONTEND_RUNTIME: process.env.FRONTEND_RUNTIME || 'static',
    UPTIME_CHECK_ENABLED: 'false',
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
  };

  const server = spawn(PYTHON_CMD, ['server.py'], {
    cwd: process.cwd(),
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let serverOut = '';
  let serverErr = '';
  server.stdout.on('data', (d) => { serverOut += d.toString(); });
  server.stderr.on('data', (d) => { serverErr += d.toString(); });

  try {
    const healthy = await waitForHealth(`${BASE_URL}/api/health`, 180000);
    if (!healthy) {
      throw new Error(`Server did not become healthy in time. stdout=${serverOut.slice(-1500)} stderr=${serverErr.slice(-1500)}`);
    }

    const status = await getJson(`${BASE_URL}/api/status`);

    const runs = [];
    runs.push(await measureViewport({
      name: 'desktop-1366',
      contextOptions: { viewport: { width: 1366, height: 768 } },
    }));

    runs.push(await measureViewport({
      name: 'mobile-390',
      contextOptions: {
        ...devices['iPhone 13'],
        viewport: { width: 390, height: 844 },
      },
    }));

    runs.push(await measureViewport({
      name: 'mobile-430',
      contextOptions: {
        ...devices['iPhone 14 Pro Max'],
        viewport: { width: 430, height: 932 },
      },
    }));

    const result = {
      capturedAt: new Date().toISOString(),
      payload: {
        fullBytes: status?.data_runtime?.payload_bytes_full || 0,
        runtimeBytes: status?.data_runtime?.payload_bytes_runtime || 0,
        fullGzipBytes: status?.data_runtime?.payload_gzip_bytes_full || 0,
        runtimeGzipBytes: status?.data_runtime?.payload_gzip_bytes_runtime || 0,
        startupBytes: status?.data_runtime?.payload_bytes_startup || 0,
        startupGzipBytes: status?.data_runtime?.payload_gzip_bytes_startup || 0,
      },
      runs,
    };

    console.log(JSON.stringify(result, null, 2));
  } finally {
    if (!server.killed) {
      server.kill('SIGTERM');
      await sleep(500);
      if (!server.killed) server.kill('SIGKILL');
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
