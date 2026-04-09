#!/usr/bin/env Rscript

# prep_scoring_data.R
# ------------------------------------------------------------------------------
# Purpose:
#   Build scoring-translation / format-fit preprocessing datasets for Python.
#
# Outputs (written to data/):
#   - player_scoring_fit.csv
#   - player_confidence.csv
#   - player_archetypes.csv
#   - rookie_fit_profiles.csv
#   - format_edge_report.csv
#
# Guardrails:
#   - Python remains source of truth for valuation.
#   - This script does NOT replace dynasty source stack or market-value logic.
#   - This script provides a bounded, auditable preprocessing layer only.
# ------------------------------------------------------------------------------

options(stringsAsFactors = FALSE)

log_info <- function(msg) {
  cat(sprintf("[prep_scoring_data] %s\n", msg))
}

safe_numeric <- function(x, default = NA_real_) {
  if (is.null(x) || length(x) == 0) {
    return(default)
  }
  v <- suppressWarnings(as.numeric(x[[1]]))
  if (!is.finite(v)) {
    return(default)
  }
  v
}

clamp <- function(x, lo, hi) {
  pmax(lo, pmin(hi, x))
}

`%||%` <- function(a, b) {
  if (
    is.null(a) ||
      (length(a) == 1 && is.na(a)) ||
      (is.character(a) && length(a) == 1 && !nzchar(trimws(a)))
  ) {
    b
  } else {
    a
  }
}

normalize_name <- function(x) {
  x <- tolower(trimws(x %||% ""))
  x <- gsub("[.'’-]", "", x)
  x <- gsub("[^a-z0-9 ]", " ", x)
  x <- gsub("\\s+", " ", x)
  trimws(x)
}

get_script_path <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)
  if (length(file_arg) > 0) {
    return(normalizePath(sub("^--file=", "", file_arg[[1]]), winslash = "/", mustWork = FALSE))
  }
  NA_character_
}

get_project_root <- function() {
  script_path <- get_script_path()
  if (!is.na(script_path) && nzchar(script_path)) {
    return(normalizePath(file.path(dirname(script_path), ".."), winslash = "/", mustWork = TRUE))
  }
  normalizePath(getwd(), winslash = "/", mustWork = TRUE)
}

ensure_directory <- function(path) {
  if (!dir.exists(path)) {
    dir.create(path, recursive = TRUE, showWarnings = FALSE)
  }
}

list_files_by_patterns <- function(project_root, patterns) {
  roots <- c(project_root, file.path(project_root, "data"))
  files <- character()
  for (d in roots) {
    if (!dir.exists(d)) next
    for (p in patterns) {
      files <- c(files, Sys.glob(file.path(d, p)))
    }
  }
  unique(normalizePath(files, winslash = "/", mustWork = FALSE))
}

choose_latest_file <- function(files, label) {
  if (length(files) == 0) {
    return(NA_character_)
  }
  info <- file.info(files)
  latest <- files[[which.max(info$mtime)]]
  log_info(sprintf("Using %s: %s", label, latest))
  latest
}

load_source_export <- function(path) {
  if (is.na(path) || !nzchar(path) || !file.exists(path)) {
    stop("No dynasty_full*.csv file found in project root or data/ directory.")
  }

  df <- tryCatch(
    read.csv(path, check.names = FALSE, stringsAsFactors = FALSE),
    error = function(e) stop(sprintf("Failed to read CSV '%s': %s", path, e$message))
  )

  required <- c("Player", "Composite", "Sites")
  missing <- setdiff(required, names(df))
  if (length(missing) > 0) {
    stop(sprintf("Missing required columns in '%s': %s", path, paste(missing, collapse = ", ")))
  }

  df$Player <- trimws(df$Player)
  df$Composite <- safe_numeric(df$Composite, NA_real_)
  df$Sites <- safe_numeric(df$Sites, 0)
  df
}

is_pick_asset <- function(name) {
  grepl(
    "^\\s*20\\d{2}\\s+((Pick\\s+)?[1-6]\\.\\d{2}|(Early|Mid|Late)\\s+[1-6](st|nd|rd|th))\\s*$",
    name,
    ignore.case = TRUE
  )
}

load_rookie_name_set <- function(project_root) {
  path <- file.path(project_root, "rookie_must_have.txt")
  if (!file.exists(path)) {
    return(character())
  }
  lines <- readLines(path, warn = FALSE, encoding = "UTF-8")
  lines <- trimws(lines)
  lines <- lines[nzchar(lines)]
  lines <- lines[!startsWith(lines, "#")]
  unique(vapply(lines, normalize_name, character(1)))
}

load_optional_player_meta <- function(project_root) {
  # Optional metadata from latest dynasty_data_*.json for richer fields
  # (position bucket and prior fit debug values). If jsonlite is unavailable,
  # gracefully continue with CSV-only preprocessing.
  out <- data.frame(
    player_name = character(),
    player_norm = character(),
    position = character(),
    years_exp = numeric(),
    format_ppg_test = numeric(),
    format_ppg_custom = numeric(),
    format_fit_raw = numeric(),
    format_fit_shrunk = numeric(),
    format_fit_final = numeric(),
    format_fit_confidence = numeric(),
    format_fit_source = character(),
    format_fit_rookie = logical(),
    format_fit_low_sample = logical(),
    stringsAsFactors = FALSE
  )

  if (!requireNamespace("jsonlite", quietly = TRUE)) {
    log_info("jsonlite not installed; skipping optional dynasty_data JSON enrichment.")
    return(out)
  }

  json_candidates <- list_files_by_patterns(project_root, c("dynasty_data_*.json"))
  json_path <- choose_latest_file(json_candidates, "dynasty_data JSON")
  if (is.na(json_path) || !file.exists(json_path)) {
    return(out)
  }

  raw <- tryCatch(
    jsonlite::fromJSON(json_path, simplifyVector = FALSE),
    error = function(e) {
      log_info(sprintf("Could not parse %s (%s). Continuing without JSON enrichment.", json_path, e$message))
      NULL
    }
  )
  if (is.null(raw) || is.null(raw$players) || !length(raw$players)) {
    return(out)
  }

  rows <- vector("list", length(raw$players))
  nm <- names(raw$players)
  for (i in seq_along(raw$players)) {
    player_name <- nm[[i]] %||% ""
    p <- raw$players[[i]]

    rows[[i]] <- data.frame(
      player_name = player_name,
      player_norm = normalize_name(player_name),
      position = toupper(as.character(p$position %||% p$POS %||% "")),
      years_exp = safe_numeric(p$`_yearsExp`, NA_real_),
      format_ppg_test = safe_numeric(p$`_formatFitPPGTest`, NA_real_),
      format_ppg_custom = safe_numeric(p$`_formatFitPPGCustom`, NA_real_),
      format_fit_raw = safe_numeric(p$`_formatFitRaw`, NA_real_),
      format_fit_shrunk = safe_numeric(p$`_formatFitShrunk`, NA_real_),
      format_fit_final = safe_numeric(p$`_formatFitFinal`, NA_real_),
      format_fit_confidence = safe_numeric(p$`_formatFitConfidence`, NA_real_),
      format_fit_source = as.character(p$`_formatFitSource` %||% ""),
      format_fit_rookie = isTRUE(p$`_formatFitRookie`),
      format_fit_low_sample = isTRUE(p$`_formatFitLowSample`),
      stringsAsFactors = FALSE
    )
  }

  out <- do.call(rbind, rows)
  out <- out[nzchar(out$player_norm), ]
  rownames(out) <- NULL
  out
}

infer_position_bucket <- function(position, is_pick, idp_source_count) {
  pos <- toupper(trimws(position %||% ""))
  if (isTRUE(is_pick)) return("PICK")
  if (pos %in% c("QB", "RB", "WR", "TE", "DL", "LB", "DB", "EDGE", "DE", "DT", "CB", "S")) {
    if (pos %in% c("EDGE", "DE", "DT")) return("DL")
    if (pos %in% c("CB", "S")) return("DB")
    return(pos)
  }
  if (!is.na(idp_source_count) && idp_source_count > 0) return("IDP")
  "OFF"
}

compute_source_spread <- function(source_matrix) {
  apply(source_matrix, 1, function(row) {
    vals <- row[is.finite(row) & row > 0]
    if (length(vals) < 2) return(NA_real_)
    m <- mean(vals)
    if (!is.finite(m) || m <= 0) return(NA_real_)
    sd(vals) / m
  })
}

build_player_base <- function(source_df, meta_df, rookie_name_set) {
  source_cols <- setdiff(names(source_df), c("Player", "Composite", "Sites"))
  if (length(source_cols) == 0) {
    stop("No source columns found in dynasty_full export.")
  }

  source_values <- as.data.frame(lapply(source_df[source_cols], safe_numeric), stringsAsFactors = FALSE)
  for (nm in names(source_values)) {
    source_values[[nm]] <- ifelse(is.na(source_values[[nm]]), NA_real_, as.numeric(source_values[[nm]]))
  }

  idp_cols <- intersect(c("idpTradeCalc"), names(source_values))
  idp_source_count <- if (length(idp_cols) > 0) rowSums(as.data.frame(lapply(source_values[idp_cols], function(v) is.finite(v) & v > 0))) else rep(0, nrow(source_df))
  source_count <- rowSums(as.data.frame(lapply(source_values, function(v) is.finite(v) & v > 0)))
  source_spread <- compute_source_spread(as.matrix(source_values))

  base <- data.frame(
    player_name = trimws(source_df$Player),
    player_norm = vapply(source_df$Player, normalize_name, character(1)),
    composite_value = as.numeric(source_df$Composite),
    composite_rank = as.integer(rank(-as.numeric(source_df$Composite), ties.method = "min", na.last = "keep")),
    site_count = as.integer(safe_numeric(source_df$Sites, 0)),
    source_count = as.integer(source_count),
    idp_source_count = as.integer(idp_source_count),
    source_spread = as.numeric(source_spread),
    is_pick = vapply(source_df$Player, is_pick_asset, logical(1)),
    stringsAsFactors = FALSE
  )

  if (nrow(meta_df) > 0) {
    meta_keep <- unique(meta_df[, c(
      "player_norm", "position", "years_exp", "format_ppg_test", "format_ppg_custom",
      "format_fit_raw", "format_fit_shrunk", "format_fit_final", "format_fit_confidence",
      "format_fit_source", "format_fit_rookie", "format_fit_low_sample"
    )])
    base <- merge(base, meta_keep, by = "player_norm", all.x = TRUE, sort = FALSE)
  } else {
    base$position <- NA_character_
    base$years_exp <- NA_real_
    base$format_ppg_test <- NA_real_
    base$format_ppg_custom <- NA_real_
    base$format_fit_raw <- NA_real_
    base$format_fit_shrunk <- NA_real_
    base$format_fit_final <- NA_real_
    base$format_fit_confidence <- NA_real_
    base$format_fit_source <- ""
    base$format_fit_rookie <- FALSE
    base$format_fit_low_sample <- FALSE
  }

  base$position <- mapply(infer_position_bucket, base$position, base$is_pick, base$idp_source_count)
  base$rookie_flag <- base$format_fit_rookie |
    (!is.na(base$years_exp) & base$years_exp == 0) |
    (base$player_norm %in% rookie_name_set)
  base$low_sample_flag <- base$format_fit_low_sample |
    (base$source_count <= 2) |
    (base$site_count <= 2)

  # Keep only players for scoring-fit outputs (picks remain excluded from this layer).
  base <- base[!base$is_pick & nzchar(base$player_name), ]
  rownames(base) <- NULL
  base
}

build_archetypes <- function(base) {
  archetype_for_pos <- function(pos, rookie, low_sample) {
    p <- toupper(pos %||% "")
    if (p == "QB") return(if (rookie || low_sample) "development_qb" else "franchise_qb")
    if (p == "RB") return(if (rookie || low_sample) "committee_back" else "workhorse_back")
    if (p == "WR") return(if (rookie || low_sample) "ascending_receiver" else "target_earner")
    if (p == "TE") return(if (rookie || low_sample) "development_te" else "volume_te")
    if (p == "DL") return("pressure_dl")
    if (p == "LB") return("tackle_lb")
    if (p == "DB") return("tackle_db")
    if (p == "IDP") return("idp_balanced")
    "balanced_offense"
  }

  deps_for_pos <- function(pos) {
    p <- toupper(pos %||% "")
    if (p == "QB") return(c(fd = 0.55, rec = 0.00, carry = 0.35, td = 0.70))
    if (p == "RB") return(c(fd = 0.60, rec = 0.55, carry = 0.85, td = 0.70))
    if (p == "WR") return(c(fd = 0.55, rec = 0.80, carry = 0.10, td = 0.60))
    if (p == "TE") return(c(fd = 0.52, rec = 0.76, carry = 0.00, td = 0.70))
    if (p == "DL") return(c(fd = 0.00, rec = 0.00, carry = 0.00, td = 0.50))
    if (p == "LB") return(c(fd = 0.00, rec = 0.00, carry = 0.00, td = 0.25))
    if (p == "DB") return(c(fd = 0.00, rec = 0.00, carry = 0.00, td = 0.20))
    if (p == "IDP") return(c(fd = 0.00, rec = 0.00, carry = 0.00, td = 0.30))
    c(fd = 0.35, rec = 0.35, carry = 0.35, td = 0.35)
  }

  out <- base
  deps <- t(vapply(out$position, deps_for_pos, numeric(4)))
  colnames(deps) <- c("first_down_dependency", "reception_dependency", "carry_dependency", "td_dependency")
  out <- cbind(out, deps)

  out$archetype <- mapply(archetype_for_pos, out$position, out$rookie_flag, out$low_sample_flag)
  out$role_bucket <- ifelse(out$rookie_flag, "projection_weighted", ifelse(out$low_sample_flag, "shallow_sample", "established"))

  out$volatility_flag <- (ifelse(is.na(out$source_spread), 0.45, out$source_spread) >= 0.45) |
    (out$td_dependency >= 0.70 & out$source_count <= 3)

  out$scoring_profile_tags <- apply(out[, c("first_down_dependency", "reception_dependency", "carry_dependency", "td_dependency")], 1, function(v) {
    tags <- c()
    if (v[[1]] >= 0.55) tags <- c(tags, "first_down_sensitive")
    if (v[[2]] >= 0.60) tags <- c(tags, "reception_sensitive")
    if (v[[3]] >= 0.60) tags <- c(tags, "carry_sensitive")
    if (v[[4]] >= 0.60) tags <- c(tags, "td_sensitive")
    if (length(tags) == 0) tags <- "balanced_profile"
    paste(tags, collapse = "|")
  })

  out[, c(
    "player_name", "position", "archetype", "role_bucket", "scoring_profile_tags",
    "first_down_dependency", "reception_dependency", "carry_dependency", "td_dependency",
    "volatility_flag"
  )]
}

build_confidence <- function(base, archetypes) {
  df <- merge(base[, c("player_name", "position", "site_count", "source_count", "source_spread", "rookie_flag", "low_sample_flag")],
              archetypes[, c("player_name", "td_dependency", "volatility_flag")],
              by = "player_name", all.x = TRUE, sort = FALSE)

  df$games_sample_score <- clamp((df$site_count %||% 0) / 8.0, 0.20, 1.00)
  df$season_sample_score <- clamp((df$source_count %||% 0) / 8.0, 0.20, 1.00)
  df$recency_score <- 0.90
  df$projection_quality_score <- ifelse(df$rookie_flag, 0.55, clamp((df$source_count + df$site_count) / 14.0, 0.35, 1.00))

  spread_adj <- clamp(1.0 - ifelse(is.na(df$source_spread), 0.40, df$source_spread), 0.20, 1.00)
  td_vol_penalty <- ifelse((df$td_dependency %||% 0) >= 0.70 & (df$volatility_flag %||% FALSE), 0.12, 0.00)
  df$role_stability_score <- clamp(spread_adj - td_vol_penalty, 0.20, 1.00)

  base_conf <- (
    (df$games_sample_score * 0.30) +
      (df$season_sample_score * 0.20) +
      (df$recency_score * 0.15) +
      (df$projection_quality_score * 0.20) +
      (df$role_stability_score * 0.15)
  )

  rookie_penalty <- ifelse(df$rookie_flag, 0.10, 0.00)
  low_sample_penalty <- ifelse(df$low_sample_flag, 0.08, 0.00)
  df$confidence <- clamp(base_conf - rookie_penalty - low_sample_penalty, 0.20, 1.00)

  df$final_confidence_bucket <- ifelse(df$confidence >= 0.80, "high",
                                       ifelse(df$confidence >= 0.55, "medium", "low"))

  df[, c(
    "player_name", "confidence", "games_sample_score", "season_sample_score", "recency_score",
    "projection_quality_score", "role_stability_score", "rookie_flag", "low_sample_flag",
    "final_confidence_bucket"
  )]
}

build_scoring_fit <- function(base, confidence_df, archetypes) {
  df <- merge(base, confidence_df[, c("player_name", "confidence", "final_confidence_bucket")], by = "player_name", all.x = TRUE, sort = FALSE)
  df <- merge(df, archetypes[, c(
    "player_name", "archetype", "role_bucket", "first_down_dependency", "reception_dependency",
    "carry_dependency", "td_dependency", "volatility_flag", "scoring_profile_tags"
  )], by = "player_name", all.x = TRUE, sort = FALSE)

  # Baseline PPG proxy:
  # - Prefer explicit format debug fields if present.
  # - Fallback to a scaled composite proxy (bounded, conservative).
  baseline_proxy <- clamp((df$composite_value %||% 0) / 500.0, 0.50, 28.00)
  baseline_ppg <- ifelse(is.finite(df$format_ppg_test) & df$format_ppg_test > 0, df$format_ppg_test, baseline_proxy)

  # Fit ratio estimate:
  # - Prefer explicit fit fields from prior pipeline output.
  # - Else derive a conservative archetype-driven ratio and shrink by confidence.
  archetype_raw <- 1.0 + (
    (df$first_down_dependency %||% 0.35) * 0.020 +
      (df$reception_dependency %||% 0.35) * 0.020 +
      (df$carry_dependency %||% 0.35) * 0.012 +
      (df$td_dependency %||% 0.35) * 0.010 -
      0.020
  )
  fit_ratio_raw <- ifelse(is.finite(df$format_fit_raw) & df$format_fit_raw > 0,
                          df$format_fit_raw,
                          archetype_raw)
  fit_ratio_raw <- clamp(fit_ratio_raw, 0.85, 1.20)

  conf <- clamp(ifelse(is.finite(df$confidence), df$confidence, 0.45), 0.20, 1.00)
  fit_shrunk <- 1.0 + ((fit_ratio_raw - 1.0) * conf)
  fit_shrunk <- clamp(fit_shrunk, 0.90, 1.12)

  if (any(df$volatility_flag %||% FALSE)) {
    vol_idx <- which(df$volatility_flag %||% FALSE)
    fit_shrunk[vol_idx] <- 1.0 + ((fit_shrunk[vol_idx] - 1.0) * 0.90)
  }

  # If pipeline exported explicit fitFinal/custom PPG, lightly prefer it.
  fit_final <- ifelse(is.finite(df$format_fit_final) & df$format_fit_final > 0,
                      (fit_shrunk * 0.75) + (df$format_fit_final * 0.25),
                      fit_shrunk)
  fit_final <- clamp(fit_final, 0.90, 1.12)

  custom_ppg_from_fit <- baseline_ppg * fit_final
  custom_ppg <- ifelse(is.finite(df$format_ppg_custom) & df$format_ppg_custom > 0,
                       (custom_ppg_from_fit * 0.70) + (df$format_ppg_custom * 0.30),
                       custom_ppg_from_fit)

  fit_ratio <- custom_ppg / pmax(baseline_ppg, 0.10)
  fit_ratio <- clamp(fit_ratio, 0.90, 1.12)
  fit_delta <- custom_ppg - baseline_ppg

  data_quality_flag <- ifelse(df$source_count >= 6 & conf >= 0.75, "high",
                              ifelse(df$source_count >= 3 & conf >= 0.50, "medium", "low"))

  profile_source <- ifelse(
    is.finite(df$format_ppg_test) | is.finite(df$format_fit_final),
    "python_fit_export_plus_r_shrink",
    ifelse(df$rookie_flag, "archetype_projection_fallback", "source_coverage_archetype")
  )

  out <- data.frame(
    player_name = df$player_name,
    position = df$position,
    baseline_ppg = round(baseline_ppg, 4),
    custom_ppg = round(custom_ppg, 4),
    fit_delta = round(fit_delta, 6),
    fit_ratio = round(fit_ratio, 6),
    fit_shrunk = round(fit_final, 6),
    confidence = round(conf, 6),
    sample_size = as.integer(pmax(df$source_count, df$site_count)),
    data_quality_flag = data_quality_flag,
    notes = df$scoring_profile_tags,
    profile_source = profile_source,
    stringsAsFactors = FALSE
  )

  out <- out[order(out$fit_ratio, decreasing = TRUE, na.last = TRUE), ]
  rownames(out) <- NULL
  out
}

build_rookie_fit_profiles <- function(base, scoring_fit, archetypes, confidence_df) {
  df <- merge(base[, c("player_name", "position", "rookie_flag", "low_sample_flag")], scoring_fit,
              by = c("player_name", "position"), all.x = TRUE, sort = FALSE)
  df <- merge(df, archetypes[, c("player_name", "archetype", "role_bucket")], by = "player_name", all.x = TRUE, sort = FALSE)
  df <- merge(df, confidence_df[, c("player_name", "confidence")], by = "player_name", all.x = TRUE, sort = FALSE)

  keep <- (df$rookie_flag %||% FALSE) | (df$low_sample_flag %||% FALSE)
  df <- df[keep, ]
  if (nrow(df) == 0) {
    return(data.frame(
      player_name = character(),
      position = character(),
      rookie_archetype = character(),
      estimated_baseline_ppg = numeric(),
      estimated_custom_ppg = numeric(),
      estimated_fit_ratio = numeric(),
      confidence = numeric(),
      projection_basis = character(),
      stringsAsFactors = FALSE
    ))
  }

  df$projection_basis <- ifelse(df$rookie_flag, "rookie_archetype_projection", "low_sample_archetype_projection")
  out <- data.frame(
    player_name = df$player_name,
    position = df$position,
    rookie_archetype = df$archetype %||% "unknown_profile",
    estimated_baseline_ppg = round(df$baseline_ppg %||% 0, 4),
    estimated_custom_ppg = round(df$custom_ppg %||% 0, 4),
    estimated_fit_ratio = round(df$fit_ratio %||% 1.0, 6),
    confidence = round(clamp(df$confidence %||% 0.35, 0.20, 1.00), 6),
    projection_basis = df$projection_basis,
    stringsAsFactors = FALSE
  )

  out <- out[order(out$estimated_fit_ratio, decreasing = TRUE, na.last = TRUE), ]
  rownames(out) <- NULL
  out
}

build_format_edge_report <- function(scoring_fit) {
  out <- scoring_fit[, c("player_name", "position", "baseline_ppg", "custom_ppg", "fit_delta", "fit_ratio", "confidence")]
  out$gain_loss_label <- ifelse(out$fit_delta >= 0.35, "GAIN",
                                ifelse(out$fit_delta <= -0.35, "LOSS", "NEUTRAL"))
  out <- out[order(abs(out$fit_delta), decreasing = TRUE, na.last = TRUE), ]
  rownames(out) <- NULL
  out
}

write_csv <- function(df, path) {
  write.csv(df, path, row.names = FALSE, na = "")
}

main <- function() {
  project_root <- get_project_root()
  data_dir <- file.path(project_root, "data")
  ensure_directory(data_dir)

  full_candidates <- list_files_by_patterns(project_root, c("dynasty_full.csv", "dynasty_full_*.csv"))
  full_csv <- choose_latest_file(full_candidates, "source export")
  source_df <- load_source_export(full_csv)

  rookie_name_set <- load_rookie_name_set(project_root)
  meta_df <- load_optional_player_meta(project_root)

  base <- build_player_base(source_df, meta_df, rookie_name_set)
  archetypes <- build_archetypes(base)
  confidence_df <- build_confidence(base, archetypes)
  scoring_fit <- build_scoring_fit(base, confidence_df, archetypes)
  rookie_profiles <- build_rookie_fit_profiles(base, scoring_fit, archetypes, confidence_df)
  edge_report <- build_format_edge_report(scoring_fit)

  outputs <- list(
    player_scoring_fit = file.path(data_dir, "player_scoring_fit.csv"),
    player_confidence = file.path(data_dir, "player_confidence.csv"),
    player_archetypes = file.path(data_dir, "player_archetypes.csv"),
    rookie_fit_profiles = file.path(data_dir, "rookie_fit_profiles.csv"),
    format_edge_report = file.path(data_dir, "format_edge_report.csv")
  )

  write_csv(scoring_fit, outputs$player_scoring_fit)
  write_csv(confidence_df, outputs$player_confidence)
  write_csv(archetypes, outputs$player_archetypes)
  write_csv(rookie_profiles, outputs$rookie_fit_profiles)
  write_csv(edge_report, outputs$format_edge_report)

  log_info(sprintf("Wrote %d rows -> %s", nrow(scoring_fit), outputs$player_scoring_fit))
  log_info(sprintf("Wrote %d rows -> %s", nrow(confidence_df), outputs$player_confidence))
  log_info(sprintf("Wrote %d rows -> %s", nrow(archetypes), outputs$player_archetypes))
  log_info(sprintf("Wrote %d rows -> %s", nrow(rookie_profiles), outputs$rookie_fit_profiles))
  log_info(sprintf("Wrote %d rows -> %s", nrow(edge_report), outputs$format_edge_report))
}

if (sys.nframe() == 0) {
  tryCatch(
    main(),
    error = function(e) {
      cat(sprintf("[prep_scoring_data] ERROR: %s\n", e$message), file = stderr())
      quit(status = 1)
    }
  )
}
