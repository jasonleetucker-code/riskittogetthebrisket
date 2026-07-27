-- ============================================================================
-- Brisket Dynasty Valuation Model — PostgreSQL schema v1.0
-- Design rule: every fact that can change over time carries as_of.
--              every derived value carries (model_version, param_set_id, config_id, as_of).
--              nothing is ever UPDATEd in place — value history is the product.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS bdvm;
SET search_path = bdvm, public;

-- ---------------------------------------------------------------- identity --

CREATE TABLE players (
    player_id        TEXT PRIMARY KEY,               -- GSIS id preferred
    full_name        TEXT NOT NULL,
    birth_date       DATE,
    pos_true         TEXT NOT NULL CHECK (pos_true IN
                       ('QB','RB','WR','TE','DT','EDGE','LB','CB','S')),
    archetype        TEXT,                           -- pocket/dual, box/deep, slot/boundary
    archetype_weight NUMERIC,                        -- continuous blend, 0-1
    entry_year       INT,
    draft_round      INT,
    draft_pick       INT,                            -- overall
    college          TEXT,
    height_in        INT,
    weight_lb        INT,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE player_ids (
    player_id   TEXT REFERENCES players(player_id),
    source      TEXT NOT NULL,                       -- sleeper, ktc, fantasycalc, pfr, ...
    source_id   TEXT NOT NULL,
    PRIMARY KEY (player_id, source)
);

-- Platform position can differ from true position and can change between seasons.
CREATE TABLE player_designations (
    player_id      TEXT REFERENCES players(player_id),
    season         INT NOT NULL,
    platform       TEXT NOT NULL,                    -- sleeper, mfl, ffpc...
    pos_platform   TEXT NOT NULL,
    as_of          DATE NOT NULL,
    PRIMARY KEY (player_id, season, platform, as_of)
);

-- ------------------------------------------------------------ nfl history --

CREATE TABLE player_seasons (
    player_id       TEXT REFERENCES players(player_id),
    season          INT NOT NULL,
    team            TEXT,
    games           INT,
    games_started   INT,
    snap_pct        NUMERIC,
    route_pct       NUMERIC,
    tgt_share       NUMERIC,
    carry_share     NUMERIC,
    goalline_share  NUMERIC,
    career_load     NUMERIC,                         -- touches/targets/dropbacks/snaps to date
    -- offense raw
    pass_att INT, pass_yd INT, pass_td INT, interceptions INT,
    rush_att INT, rush_yd INT, rush_td INT,
    targets INT, receptions INT, rec_yd INT, rec_td INT, first_downs INT,
    -- idp raw
    tkl_solo INT, tkl_ast INT, sacks NUMERIC, tfl INT, qb_hits INT,
    pass_def INT, int_def INT, forced_fum INT, fum_rec INT, def_td INT,
    pass_rush_snaps INT, box_snaps INT, slot_snaps INT, deep_snaps INT,
    coverage_snaps INT, targets_faced INT,
    -- derived / charted
    yprr NUMERIC, tprr NUMERIC, pressure_rate NUMERIC,
    expected_sacks NUMERIC, tackle_rate NUMERIC, tackles_vs_expected NUMERIC,
    exp_fpts NUMERIC,                                -- opportunity-based expected points
    as_of           DATE NOT NULL,
    PRIMARY KEY (player_id, season, as_of)
);

CREATE TABLE player_injuries (
    player_id    TEXT REFERENCES players(player_id),
    season       INT, week INT,
    body_part    TEXT, injury_type TEXT,             -- soft_tissue / joint / bone / concussion
    games_missed INT,
    as_of        DATE NOT NULL,
    PRIMARY KEY (player_id, season, week, as_of)
);

CREATE TABLE player_contracts (
    player_id            TEXT REFERENCES players(player_id),
    season               INT,
    years_left           INT,
    guaranteed_remaining NUMERIC,
    dead_cap_if_cut      NUMERIC,
    fifth_year_option    BOOLEAN,
    franchise_tag        BOOLEAN,
    status               TEXT,                       -- active/ir/ps/fa/rfa
    as_of                DATE NOT NULL,
    PRIMARY KEY (player_id, season, as_of)
);

CREATE TABLE college_production (
    player_id         TEXT PRIMARY KEY REFERENCES players(player_id),
    breakout_age      NUMERIC,
    peak_dominator    NUMERIC,
    career_dominator  NUMERIC,
    yds_per_team_att  NUMERIC,
    early_declare     BOOLEAN,
    conference        TEXT,
    ras               NUMERIC,                       -- athletic score
    col_pressure_rate NUMERIC, col_tackle_rate NUMERIC, col_coverage_grade NUMERIC
);

-- ------------------------------------------------------------ projections --

CREATE TABLE projection_sources (
    source         TEXT PRIMARY KEY,
    display_name   TEXT,
    is_consensus   BOOLEAN DEFAULT false,
    active         BOOLEAN DEFAULT true
);

CREATE TABLE source_weights (                        -- trained ONLY on prior seasons
    source   TEXT REFERENCES projection_sources(source),
    pos      TEXT NOT NULL,
    season   INT  NOT NULL,                          -- season the weight applies TO
    mase     NUMERIC,
    weight   NUMERIC NOT NULL,
    trained_through_season INT NOT NULL,             -- leakage guard
    PRIMARY KEY (source, pos, season)
);

CREATE TABLE projections_raw (
    id             BIGSERIAL PRIMARY KEY,
    player_id      TEXT REFERENCES players(player_id),
    source         TEXT REFERENCES projection_sources(source),
    season         INT NOT NULL,
    stat_line      JSONB,                            -- raw projected stats
    fpts           NUMERIC,                          -- fallback if no stat_line
    games          NUMERIC,
    proj_high      NUMERIC, proj_low NUMERIC,
    scoring_native BOOLEAN DEFAULT false,            -- true if fpts already in our scoring
    as_of          DATE NOT NULL,
    UNIQUE (player_id, source, season, as_of)
);

CREATE TABLE projection_blend (
    player_id    TEXT REFERENCES players(player_id),
    season       INT NOT NULL,
    config_id    TEXT NOT NULL,
    fpg          NUMERIC NOT NULL,
    sigma_source NUMERIC NOT NULL,
    games        NUMERIC NOT NULL,
    n_sources    INT,
    imputed      BOOLEAN DEFAULT false,
    as_of        DATE NOT NULL,
    PRIMARY KEY (player_id, season, config_id, as_of)
);

-- --------------------------------------------------------------- leagues ---

CREATE TABLE league_configs (
    config_id     TEXT PRIMARY KEY,
    display_name  TEXT,
    teams         INT NOT NULL,
    scoring       JSONB NOT NULL,
    starters      JSONB NOT NULL,
    flex_slots    JSONB NOT NULL,
    waiver_buffer JSONB NOT NULL,
    pos_groups    JSONB NOT NULL,                    -- true pos -> lineup group
    roster_size   INT, taxi_size INT,
    best_ball     BOOLEAN DEFAULT false,
    config_hash   TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE replacement_levels (
    config_id   TEXT REFERENCES league_configs(config_id),
    season      INT NOT NULL,
    pos_group   TEXT NOT NULL,
    slots       INT NOT NULL,                        -- startable league-wide
    repl_rank   INT NOT NULL,
    repl_fpg    NUMERIC NOT NULL,
    as_of       DATE NOT NULL,
    PRIMARY KEY (config_id, season, pos_group, as_of)
);

-- ---------------------------------------------------------------- model ----

CREATE TABLE model_params (
    param_set_id  SERIAL PRIMARY KEY,
    label         TEXT,
    age_curves    JSONB NOT NULL,                    -- pos -> [peak, c_up, c_dn]
    mileage       JSONB NOT NULL,
    hazards       JSONB NOT NULL,
    cv_base       JSONB NOT NULL,
    drift_vol     JSONB NOT NULL,
    strategies    JSONB NOT NULL,                    -- d, horizon, usability, lambda
    misc          JSONB NOT NULL,                    -- gamma, theta, decays, regressions
    backtest_ref  TEXT,                              -- git tag / experiment id justifying it
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE player_values (
    id            BIGSERIAL PRIMARY KEY,
    player_id     TEXT REFERENCES players(player_id),
    season        INT NOT NULL,
    config_id     TEXT REFERENCES league_configs(config_id),
    strategy      TEXT NOT NULL CHECK (strategy IN ('contender','balanced','rebuilder')),
    dv_raw        NUMERIC NOT NULL,                  -- pre-scale discounted value
    trade_value   NUMERIC NOT NULL,                  -- 0-10000
    fpg           NUMERIC, repl_fpg NUMERIC, vorg NUMERIC,
    age_eff       NUMERIC,
    p_above_repl  NUMERIC, p_elite NUMERIC, p_starter_3y NUMERIC,
    p_breakout    NUMERIC, p_collapse_1y NUMERIC,
    floor_p20     NUMERIC, ceiling_p85 NUMERIC,
    confidence    NUMERIC, volatility NUMERIC,
    explain       JSONB,
    data_quality  NUMERIC,                           -- 0-1, drops with imputation
    model_version TEXT NOT NULL,
    param_set_id  INT REFERENCES model_params(param_set_id),
    as_of         DATE NOT NULL,
    UNIQUE (player_id, season, config_id, strategy, model_version, param_set_id, as_of)
);
CREATE INDEX ON player_values (config_id, strategy, as_of, trade_value DESC);
CREATE INDEX ON player_values (player_id, as_of);

CREATE TABLE value_paths (                           -- career-value chart data
    player_id     TEXT, season INT, config_id TEXT, strategy TEXT,
    t             INT NOT NULL,
    age           NUMERIC, age_eff NUMERIC,
    mu_fpg        NUMERIC, sigma NUMERIC, games NUMERIC,
    ssv           NUMERIC, survival NUMERIC, expected NUMERIC,
    model_version TEXT, param_set_id INT, as_of DATE NOT NULL,
    PRIMARY KEY (player_id, season, config_id, strategy, t, as_of)
);

-- --------------------------------------------------------------- market ----

CREATE TABLE market_sources (
    source     TEXT PRIMARY KEY,
    mkt_type   TEXT NOT NULL CHECK (mkt_type IN ('crowd','trade_derived','expert')),
    weight     NUMERIC DEFAULT 1.0
);

CREATE TABLE market_values (
    player_id  TEXT REFERENCES players(player_id),
    source     TEXT REFERENCES market_sources(source),
    format     TEXT NOT NULL,                        -- 1qb / sf, tep tier, idp flag
    value      NUMERIC NOT NULL,                     -- normalised 0-10000
    raw_value  NUMERIC,
    as_of      DATE NOT NULL,
    PRIMARY KEY (player_id, source, format, as_of)
);

CREATE TABLE market_gaps (
    player_id        TEXT, config_id TEXT, season INT,
    model_value      NUMERIC, market_consensus NUMERIC,
    dispersion       NUMERIC, liquidity NUMERIC,
    gap              NUMERIC, alpha NUMERIC,
    momentum_30d     NUMERIC,
    gap_first_seen   DATE,                           -- persistence guard for BUY signals
    signal           TEXT,
    blended_value    NUMERIC,
    as_of            DATE NOT NULL,
    PRIMARY KEY (player_id, config_id, season, as_of)
);

-- ----------------------------------------------------------- news events ---

CREATE TABLE news_event_types (
    event_type        TEXT PRIMARY KEY,
    default_impact    JSONB NOT NULL,                -- mu_pct, role_delta, sigma_mult, hazard_mult
    default_half_life INT NOT NULL
);

CREATE TABLE news_events (
    event_id              TEXT PRIMARY KEY,
    player_id             TEXT REFERENCES players(player_id),
    event_type            TEXT REFERENCES news_event_types(event_type),
    effective_date        DATE NOT NULL,
    confidence            NUMERIC NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source_reliability    NUMERIC NOT NULL,
    already_in_projection BOOLEAN NOT NULL DEFAULT false,
    impact                JSONB,                     -- overrides default_impact
    duration_days         INT, half_life_days INT,
    notes                 TEXT,
    created_at            TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------- rookie picks ---

CREATE TABLE rookie_pick_outcomes (
    format       TEXT NOT NULL,                      -- sf_tep_idp, 1qb_ppr, ...
    overall_slot INT  NOT NULL,
    p_hit NUMERIC, v_hit NUMERIC,
    p_mid NUMERIC, v_mid NUMERIC,
    p_miss NUMERIC, v_miss NUMERIC,
    sample_n INT, seasons_covered TEXT,
    param_set_id INT REFERENCES model_params(param_set_id),
    PRIMARY KEY (format, overall_slot, param_set_id)
);

CREATE TABLE draft_class_strength (
    class_year INT, format TEXT, position TEXT,
    strength   NUMERIC,                              -- multiplier ~0.85-1.15
    as_of      DATE NOT NULL,
    PRIMARY KEY (class_year, format, position, as_of)
);

-- ------------------------------------------------------------- backtests ---

CREATE TABLE model_experiments (
    experiment_id  SERIAL PRIMARY KEY,
    label          TEXT NOT NULL,
    param_set_id   INT REFERENCES model_params(param_set_id),
    ablation       TEXT,                             -- what was turned off
    target         TEXT NOT NULL,                    -- T1..T8
    fold           TEXT NOT NULL,
    pos            TEXT,
    metric         TEXT NOT NULL,                    -- spearman, mae, brier, ndcg@24
    value          NUMERIC NOT NULL,
    baseline       TEXT,                             -- B0..B4
    baseline_value NUMERIC,
    n_rows         INT,
    run_at         TIMESTAMPTZ DEFAULT now()
);

-- ------------------------------------------------------------ user layer ---

CREATE TABLE user_rosters (
    user_id     TEXT, league_id TEXT, config_id TEXT,
    player_id   TEXT REFERENCES players(player_id),
    acquired_at DATE,
    as_of       DATE NOT NULL,
    PRIMARY KEY (user_id, league_id, player_id, as_of)
);

CREATE TABLE roster_reports (
    user_id TEXT, league_id TEXT, config_id TEXT,
    starter_ppg NUMERIC,
    contender_capital NUMERIC, rebuilder_capital NUMERIC, now_future_ratio NUMERIC,
    window_peak_season INT,
    positional_surplus JSONB,
    age_concentration NUMERIC, risk_concentration NUMERIC, liquidity NUMERIC,
    direction TEXT,                                  -- contend / retool / rebuild
    as_of DATE NOT NULL,
    PRIMARY KEY (user_id, league_id, as_of)
);
