(() => {
  const NAV_ITEMS = [
    { slug: "home", label: "Home", path: "/league" },
    { slug: "standings", label: "Standings", path: "/league/standings" },
    { slug: "franchises", label: "Franchises", path: "/league/franchises" },
    { slug: "awards", label: "Awards", path: "/league/awards" },
    { slug: "draft", label: "Draft", path: "/league/draft" },
    { slug: "trades", label: "Trades", path: "/league/trades" },
    { slug: "records", label: "Records", path: "/league/records" },
    { slug: "money", label: "Money", path: "/league/money" },
    { slug: "constitution", label: "Constitution", path: "/league/constitution" },
    { slug: "history", label: "History", path: "/league/history" },
    { slug: "league-media", label: "League Media", path: "/league/league-media" },
  ];

  const ROUTE_ALIASES = {
    home: "home",
    standings: "standings",
    franchises: "franchises",
    awards: "awards",
    draft: "draft",
    drafts: "draft",
    trades: "trades",
    records: "records",
    money: "money",
    constitution: "constitution",
    rules: "constitution",
    history: "history",
    "league-media": "league-media",
    media: "league-media",
  };

  const STATUS_META = {
    live: { label: "Live now", className: "pill-live" },
    stub: { label: "Scaffold", className: "pill-stub" },
    blocked: { label: "Blocked", className: "pill-blocked" },
  };

  const PAGE_SPECS = {
    home: {
      title: "League Home",
      purpose: "Public league HQ for identity, navigation, and context.",
      phase: "Phase 1",
      modules: [
        {
          title: "Public route + shell",
          status: "live",
          description: "Public entry and page framework are now wired.",
        },
        {
          title: "League snapshot",
          status: "live",
          description: "Reads public-safe summary data from /api/league/public.",
        },
        {
          title: "Cross-tab hub",
          status: "stub",
          description: "Each top-level section now has a real route shell.",
        },
      ],
      dependencies: [
        "Public-safe backend subset endpoint (/api/league/public).",
        "League metadata from Sleeper block (league name, teams, trade window).",
      ],
    },
    standings: {
      title: "Standings",
      purpose: "Season standings and year-over-year performance context.",
      phase: "Phase 2+",
      modules: [
        {
          title: "Current standings table",
          status: "stub",
          description: "Table shell is ready; standings dataset is not wired yet.",
        },
        {
          title: "Historical standings by season",
          status: "blocked",
          description: "Requires standings-by-year backfill and validation.",
        },
        {
          title: "Playoff finish markers",
          status: "blocked",
          description: "Needs reliable playoff outcome history per season.",
        },
      ],
      dependencies: [
        "seasons",
        "standings_by_year",
        "playoff_results_by_year",
      ],
    },
    franchises: {
      title: "Franchises",
      purpose: "Franchise directory, identity, and eventual all-time profiles.",
      phase: "Phase 1 foundation / deeper Phase 2+",
      modules: [
        {
          title: "Franchise directory",
          status: "live",
          description: "Current franchise/team summary list is wired from public API.",
        },
        {
          title: "Franchise profile pages",
          status: "stub",
          description: "Detail route shape is supported; historical module data is pending.",
        },
        {
          title: "All-time player leaders",
          status: "blocked",
          description: "Requires roster ownership by week + weekly player scoring history.",
        },
      ],
      dependencies: [
        "franchises",
        "franchise_name_history",
        "roster_history by week",
        "weekly_player_scores",
      ],
    },
    awards: {
      title: "Awards",
      purpose: "League award history with transparent methodology and data gates.",
      phase: "Phase 2/3",
      modules: [
        {
          title: "Awards index shell",
          status: "stub",
          description: "Route and framework are in place.",
        },
        {
          title: "Methodology-first presentation",
          status: "live",
          description: "Page is scoped to public methodology + data readiness notes.",
        },
        {
          title: "Official computed winners",
          status: "blocked",
          description: "Blocked until historical ownership + scoring coverage meets quality bars.",
        },
      ],
      dependencies: [
        "weekly_player_scores",
        "roster_history by week",
        "awards output table",
      ],
    },
    draft: {
      title: "Draft",
      purpose: "Rookie draft tracking, traded picks, and long-term draft archive.",
      phase: "Phase 1+",
      modules: [
        {
          title: "Future pick ownership baseline",
          status: "live",
          description: "Source data exists for team-level future pick counts.",
        },
        {
          title: "Current year order + tracker",
          status: "stub",
          description: "UI shell is ready; normalized draft view is pending.",
        },
        {
          title: "Historical rookie results and hit rates",
          status: "blocked",
          description: "Needs historical draft results + longitudinal outcomes.",
        },
      ],
      dependencies: [
        "draft_picks",
        "draft_results",
        "pick_ownership_history",
      ],
    },
    trades: {
      title: "Trades",
      purpose: "Public trade timeline and league activity context without private edge leakage.",
      phase: "Phase 1 foundation / deeper Phase 2+",
      modules: [
        {
          title: "Rolling trade activity summary",
          status: "live",
          description: "Recent trade window metadata is wired from Sleeper-derived payload.",
        },
        {
          title: "Trade list/table shell",
          status: "stub",
          description: "Public-safe history shell is ready for enriched trade rows.",
        },
        {
          title: "Best/worst trade analytics",
          status: "blocked",
          description: "Requires normalized trade assets + at-time and hindsight valuation layers.",
        },
      ],
      dependencies: [
        "trades",
        "trade_assets normalized",
        "time-sliced valuation context",
      ],
    },
    records: {
      title: "Records",
      purpose: "League record book for weekly, seasonal, and all-time milestones.",
      phase: "Phase 2+",
      modules: [
        {
          title: "Records categories shell",
          status: "stub",
          description: "Category framework is established.",
        },
        {
          title: "Official record outputs",
          status: "blocked",
          description: "Blocked until historical scoring and matchup integrity is complete.",
        },
        {
          title: "Verification metadata",
          status: "stub",
          description: "Record lineage/audit details are planned in this section.",
        },
      ],
      dependencies: [
        "weekly_team_scores",
        "matchups",
        "season history coverage",
      ],
    },
    money: {
      title: "Money",
      purpose: "Public finance board for dues, payouts, and profitability context.",
      phase: "Phase 1 manual-first",
      modules: [
        {
          title: "Money module shell",
          status: "stub",
          description: "Route and layout are implemented.",
        },
        {
          title: "Manual ledger ingestion",
          status: "blocked",
          description: "Requires commissioner-maintained payouts/dues dataset.",
        },
        {
          title: "Leaderboard metrics",
          status: "blocked",
          description: "Dependent on validated ledger rows across seasons.",
        },
      ],
      dependencies: [
        "payouts ledger",
        "dues history",
        "manual commissioner entries",
      ],
    },
    constitution: {
      title: "Constitution",
      purpose: "Public rules archive with version history and change log.",
      phase: "Phase 1 manual-first",
      modules: [
        {
          title: "Constitution route shell",
          status: "stub",
          description: "Public route and page framework are in place.",
        },
        {
          title: "Versioned rules document store",
          status: "blocked",
          description: "Requires manual rules_versions content source.",
        },
        {
          title: "Amendment/change timeline",
          status: "blocked",
          description: "Needs amendment log and publishing workflow.",
        },
      ],
      dependencies: [
        "rules_versions",
        "amendments log",
        "commissioner edit workflow",
      ],
    },
    history: {
      title: "History",
      purpose: "League museum timeline, eras, and notable milestones.",
      phase: "Phase 2+",
      modules: [
        {
          title: "History route shell",
          status: "stub",
          description: "Public page structure is ready.",
        },
        {
          title: "Season timeline",
          status: "blocked",
          description: "Needs validated historical season outcomes and metadata.",
        },
        {
          title: "Era/rivalry storytelling",
          status: "stub",
          description: "Narrative container exists pending curated content.",
        },
      ],
      dependencies: [
        "seasons complete history",
        "matchups and outcomes",
        "manual milestone entries",
      ],
    },
    "league-media": {
      title: "League Media",
      purpose: "Public weekly content hub for previews, recaps, and stories.",
      phase: "Phase 1 manual-first / automation later",
      modules: [
        {
          title: "League Media route shell",
          status: "stub",
          description: "Navigation and section framework is implemented.",
        },
        {
          title: "Manual publish/archive workflow",
          status: "blocked",
          description: "Needs commissioner-managed content storage and moderation flow.",
        },
        {
          title: "Automated narratives",
          status: "blocked",
          description: "Deferred until public-safe generation and quality controls are defined.",
        },
      ],
      dependencies: [
        "media_posts",
        "editorial workflow",
        "public-safe generation guardrails",
      ],
    },
  };

  const state = {
    loading: true,
    error: "",
    data: null,
  };

  const navEl = document.getElementById("leagueNav");
  const mainEl = document.getElementById("leagueMain");
  const summaryEl = document.getElementById("leagueDataSummary");
  const timestampEl = document.getElementById("leagueDataTimestamp");
  const statusBadgeEl = document.getElementById("leagueStatusBadge");

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatTime(iso) {
    if (!iso) return "No timestamp";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "Invalid timestamp";
    return d.toLocaleString();
  }

  function resolveRoute(pathname) {
    const path = String(pathname || "/").replace(/\/+/g, "/");
    const segments = path.split("/").filter(Boolean);
    if (!segments.length) return { slug: "home", known: true, subpath: [] };
    if (segments[0] !== "league") return { slug: "home", known: false, subpath: segments };
    if (segments.length === 1) return { slug: "home", known: true, subpath: [] };
    const requested = String(segments[1] || "").toLowerCase();
    const slug = ROUTE_ALIASES[requested];
    if (!slug) return { slug: "home", known: false, subpath: segments.slice(1), requested };
    return { slug, known: true, subpath: segments.slice(2), requested };
  }

  function pathForSlug(slug) {
    const row = NAV_ITEMS.find((item) => item.slug === slug);
    return row ? row.path : "/league";
  }

  function renderNav(activeSlug) {
    navEl.innerHTML = NAV_ITEMS.map((item) => {
      const activeClass = item.slug === activeSlug ? " active" : "";
      return `<a class="league-nav-link${activeClass}" href="${item.path}" data-nav-slug="${item.slug}">${escapeHtml(item.label)}</a>`;
    }).join("");

    navEl.querySelectorAll("a[data-nav-slug]").forEach((link) => {
      link.addEventListener("click", (event) => {
        const href = link.getAttribute("href");
        if (!href) return;
        event.preventDefault();
        const url = new URL(href, window.location.origin);
        if (window.location.pathname !== url.pathname) {
          window.history.pushState({}, "", url.pathname);
        }
        render();
      });
    });
  }

  function statusPill(status) {
    const meta = STATUS_META[status] || STATUS_META.stub;
    return `<span class="pill ${meta.className}">${escapeHtml(meta.label)}</span>`;
  }

  function renderModuleCard(module) {
    return `
      <article class="card">
        <div class="module-head">
          <div class="card-title">${escapeHtml(module.title)}</div>
          ${statusPill(module.status)}
        </div>
        <div class="card-body">${escapeHtml(module.description)}</div>
      </article>
    `;
  }

  function renderDependencies(dependencies) {
    if (!Array.isArray(dependencies) || !dependencies.length) {
      return "<p>No dependency notes.</p>";
    }
    const items = dependencies.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    return `<ul class="module-list">${items}</ul>`;
  }

  function renderPageShell(spec, extraHtml) {
    const modulesHtml = (spec.modules || []).map(renderModuleCard).join("");
    return `
      <section class="panel">
        <h1>${escapeHtml(spec.title)}</h1>
        <p>${escapeHtml(spec.purpose)}</p>
        <div class="grid two" style="margin-top:10px;">
          <div class="card">
            <div class="card-title">Delivery Phase</div>
            <div class="card-body mono">${escapeHtml(spec.phase || "TBD")}</div>
          </div>
          <div class="card">
            <div class="card-title">Scope Guardrail</div>
            <div class="card-body">Public-safe only. No private ranking/calculator internals.</div>
          </div>
        </div>
      </section>
      <section class="panel">
        <h2>Module Readiness</h2>
        <div class="grid two" style="margin-top:10px;">${modulesHtml}</div>
      </section>
      ${extraHtml || ""}
      <section class="panel">
        <h2>Data Dependencies</h2>
        ${renderDependencies(spec.dependencies || [])}
      </section>
    `;
  }

  function getLeagueData() {
    return state.data && state.data.ok ? state.data : null;
  }

  function renderHome() {
    const payload = getLeagueData();
    const league = payload ? payload.league || {} : {};
    const teams = payload ? (Array.isArray(payload.teams) ? payload.teams : []) : [];

    const quickLinks = NAV_ITEMS.filter((item) => item.slug !== "home")
      .map((item) => {
        return `
          <a class="card" href="${item.path}" data-quick-link="${item.slug}" style="text-decoration:none;color:inherit;">
            <div class="card-title">${escapeHtml(item.label)}</div>
            <div class="card-body">Open ${escapeHtml(item.label)} section</div>
          </a>
        `;
      })
      .join("");

    const teamsTableRows = teams.slice(0, 12).map((team) => {
      return `
        <tr>
          <td>${escapeHtml(team.name || "Team")}</td>
          <td class="mono">${escapeHtml(team.rosterId ?? "n/a")}</td>
          <td class="mono">${escapeHtml(team.playerCount ?? 0)}</td>
          <td class="mono">${escapeHtml(team.pickCount ?? 0)}</td>
        </tr>
      `;
    }).join("");

    const homeExtra = `
      <section class="panel">
        <div class="module-head">
          <h2>League Snapshot</h2>
          <button id="refreshPublicDataBtn" class="pill pill-public" type="button">Refresh Public Data</button>
        </div>
        <div class="grid three" style="margin-top:10px;">
          <article class="card">
            <div class="card-title">League</div>
            <div class="card-body">${escapeHtml(league.leagueName || "Not available yet")}</div>
          </article>
          <article class="card">
            <div class="card-title">Franchises</div>
            <div class="card-body mono">${escapeHtml(league.teamCount ?? 0)} teams</div>
          </article>
          <article class="card">
            <div class="card-title">Trade Window</div>
            <div class="card-body mono">${escapeHtml(league.tradeCount ?? 0)} trades in ${escapeHtml(league.tradeWindowDays ?? "n/a")} days</div>
          </article>
        </div>
      </section>
      <section class="panel">
        <h2>Jump To Section</h2>
        <div class="grid three" style="margin-top:10px;">${quickLinks}</div>
      </section>
      <section class="panel">
        <h2>Current Franchise Directory (Public Summary)</h2>
        ${teams.length
          ? `
            <table class="table">
              <thead>
                <tr>
                  <th>Franchise</th>
                  <th>Roster ID</th>
                  <th>Players</th>
                  <th>Picks</th>
                </tr>
              </thead>
              <tbody>${teamsTableRows}</tbody>
            </table>
          `
          : "<p>Public league team summaries are not available yet.</p>"
        }
      </section>
    `;

    return renderPageShell(PAGE_SPECS.home, homeExtra);
  }

  function renderStandings() {
    const extra = `
      <section class="panel">
        <h2>Standings Framework (Phase 1 Shell)</h2>
        <p>This section is intentionally scaffolded while historical standings and playoff outcomes are validated.</p>
      </section>
    `;
    return renderPageShell(PAGE_SPECS.standings, extra);
  }

  function renderFranchises(route) {
    const payload = getLeagueData();
    const teams = payload ? (Array.isArray(payload.teams) ? payload.teams : []) : [];
    const teamRows = teams.map((team) => {
      const detailHref = `/league/franchises/${encodeURIComponent(String(team.rosterId ?? team.name ?? "team"))}`;
      return `
        <tr>
          <td>${escapeHtml(team.name || "Team")}</td>
          <td class="mono">${escapeHtml(team.rosterId ?? "n/a")}</td>
          <td class="mono">${escapeHtml(team.playerCount ?? 0)}</td>
          <td class="mono">${escapeHtml(team.pickCount ?? 0)}</td>
          <td><a href="${detailHref}" data-franchise-link="1">Open Shell</a></td>
        </tr>
      `;
    }).join("");

    const detailNotice = route.subpath.length
      ? `
        <section class="panel">
          <h2>Franchise Detail Route Detected</h2>
          <p>Requested franchise path: <span class="mono">${escapeHtml(route.subpath.join("/"))}</span></p>
          <p>This confirms detail route addressing is live; full franchise profile data modules are pending historical wiring.</p>
        </section>
      `
      : "";

    const extra = `
      ${detailNotice}
      <section class="panel">
        <h2>Franchise Directory</h2>
        ${teams.length
          ? `
            <table class="table">
              <thead>
                <tr>
                  <th>Franchise</th>
                  <th>Roster ID</th>
                  <th>Players</th>
                  <th>Picks</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>${teamRows}</tbody>
            </table>
          `
          : "<p>Franchise directory will appear here once public API data is available.</p>"
        }
      </section>
    `;
    return renderPageShell(PAGE_SPECS.franchises, extra);
  }

  function renderAwards() {
    const extra = `
      <section class="panel">
        <h2>Awards Scope Guardrail</h2>
        <p>Player awards will remain methodology-first until replacement-level and VORP calculations can be trusted from complete historical data.</p>
      </section>
    `;
    return renderPageShell(PAGE_SPECS.awards, extra);
  }

  function renderDraft() {
    const extra = `
      <section class="panel">
        <h2>Draft Framework</h2>
        <p>Current focus is public-safe draft structure and pick ownership routing. Historical draft analytics will be wired only after validated backfill.</p>
      </section>
    `;
    return renderPageShell(PAGE_SPECS.draft, extra);
  }

  function renderTrades() {
    const payload = getLeagueData();
    const recentTrades = payload ? (Array.isArray(payload.recentTrades) ? payload.recentTrades : []) : [];
    const tradeRows = recentTrades.map((trade) => {
      const sideText = (Array.isArray(trade.sideSummaries) ? trade.sideSummaries : [])
        .map((side) => `${side.team} (+${side.gotCount}/-${side.gaveCount})`)
        .join(" | ");
      return `
        <tr>
          <td class="mono">${escapeHtml(formatTime(trade.timestampIso))}</td>
          <td class="mono">${escapeHtml(trade.week ?? "n/a")}</td>
          <td>${escapeHtml(sideText || "n/a")}</td>
        </tr>
      `;
    }).join("");

    const extra = `
      <section class="panel">
        <h2>Recent Trade Window (Public Summary)</h2>
        ${recentTrades.length
          ? `
            <table class="table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Week</th>
                  <th>Side Summary</th>
                </tr>
              </thead>
              <tbody>${tradeRows}</tbody>
            </table>
          `
          : "<p>No recent trade summary rows are available yet.</p>"
        }
      </section>
    `;
    return renderPageShell(PAGE_SPECS.trades, extra);
  }

  function renderRecords() {
    const extra = `
      <section class="panel">
        <h2>Records Framework</h2>
        <p>Records categories will remain scaffolded until historical matchup and score completeness is verified season-by-season.</p>
      </section>
    `;
    return renderPageShell(PAGE_SPECS.records, extra);
  }

  function renderMoney() {
    const extra = `
      <section class="panel">
        <h2>Money Module Note</h2>
        <p>Money leaderboard metrics are intentionally not fabricated. This section will use commissioner-entered payouts/dues data when that ledger is wired.</p>
      </section>
    `;
    return renderPageShell(PAGE_SPECS.money, extra);
  }

  function renderConstitution() {
    const extra = `
      <section class="panel">
        <h2>Constitution Module Note</h2>
        <p>Constitution content is planned as a commissioner-managed versioned store. Route and layout are ready for that content source.</p>
      </section>
    `;
    return renderPageShell(PAGE_SPECS.constitution, extra);
  }

  function renderHistory() {
    const extra = `
      <section class="panel">
        <h2>History Framework</h2>
        <p>History will become the league timeline/museum once season-level outcomes are fully backfilled and validated.</p>
      </section>
    `;
    return renderPageShell(PAGE_SPECS.history, extra);
  }

  function renderLeagueMedia() {
    const extra = `
      <section class="panel">
        <h2>League Media Framework</h2>
        <p>This section is set up for weekly preview/review publishing and archive workflows. Public-safe automation is deferred until quality controls are finalized.</p>
      </section>
    `;
    return renderPageShell(PAGE_SPECS["league-media"], extra);
  }

  function renderNotFound(route) {
    const badPath = window.location.pathname;
    return `
      <section class="panel">
        <h1>League Route Not Found</h1>
        <p>The requested route does not match a public League section.</p>
        <p class="mono" style="margin-top:10px;">${escapeHtml(badPath)}</p>
        <p style="margin-top:12px;"><a href="/league">Return to League Home</a></p>
        ${route && route.requested ? `<p style="margin-top:8px;">Unknown section key: <span class="mono">${escapeHtml(route.requested)}</span></p>` : ""}
      </section>
    `;
  }

  function updateSnapshotBar() {
    if (state.loading) {
      summaryEl.textContent = "Loading public league context…";
      statusBadgeEl.textContent = "Loading";
      statusBadgeEl.className = "pill pill-loading";
      timestampEl.textContent = "Waiting for /api/league/public";
      return;
    }

    if (state.error) {
      summaryEl.textContent = "Public league data is currently unavailable.";
      statusBadgeEl.textContent = "Unavailable";
      statusBadgeEl.className = "pill pill-blocked";
      timestampEl.textContent = state.error;
      return;
    }

    const payload = getLeagueData();
    const league = payload ? payload.league || {} : {};
    summaryEl.textContent = `${league.leagueName || "League"} • ${league.teamCount ?? 0} teams • ${league.tradeCount ?? 0} trades in current window`;
    statusBadgeEl.textContent = "Public Feed";
    statusBadgeEl.className = "pill pill-live";
    timestampEl.textContent = `Source refreshed: ${formatTime(payload.sourceLoadedAt)}`;
  }

  function renderPageBySlug(slug, route) {
    switch (slug) {
      case "home":
        return renderHome(route);
      case "standings":
        return renderStandings(route);
      case "franchises":
        return renderFranchises(route);
      case "awards":
        return renderAwards(route);
      case "draft":
        return renderDraft(route);
      case "trades":
        return renderTrades(route);
      case "records":
        return renderRecords(route);
      case "money":
        return renderMoney(route);
      case "constitution":
        return renderConstitution(route);
      case "history":
        return renderHistory(route);
      case "league-media":
        return renderLeagueMedia(route);
      default:
        return renderNotFound(route);
    }
  }

  function wirePageActions() {
    const refreshBtn = document.getElementById("refreshPublicDataBtn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", async () => {
        await fetchPublicData();
        render();
      });
    }

    mainEl.querySelectorAll("a[data-quick-link], a[data-franchise-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        const href = link.getAttribute("href");
        if (!href) return;
        event.preventDefault();
        const url = new URL(href, window.location.origin);
        if (window.location.pathname !== url.pathname) {
          window.history.pushState({}, "", url.pathname);
        }
        render();
      });
    });
  }

  function render() {
    const route = resolveRoute(window.location.pathname);
    const activeSlug = route.known ? route.slug : "";
    renderNav(activeSlug);
    updateSnapshotBar();

    if (!route.known) {
      mainEl.innerHTML = renderNotFound(route);
      return;
    }

    const pageHtml = renderPageBySlug(route.slug, route);
    mainEl.innerHTML = pageHtml;
    wirePageActions();
  }

  async function fetchPublicData() {
    state.loading = true;
    state.error = "";
    updateSnapshotBar();

    try {
      const resp = await fetch("/api/league/public", {
        method: "GET",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      const payload = await resp.json().catch(() => ({}));
      if (!resp.ok || !payload.ok) {
        throw new Error(payload.error || `Request failed (${resp.status})`);
      }
      state.data = payload;
    } catch (err) {
      state.data = null;
      state.error = err instanceof Error ? err.message : "Unknown public data error.";
    } finally {
      state.loading = false;
      updateSnapshotBar();
    }
  }

  async function init() {
    render();
    await fetchPublicData();
    render();
    window.addEventListener("popstate", render);
  }

  init();
})();
