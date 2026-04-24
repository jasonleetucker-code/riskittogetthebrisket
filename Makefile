# ──────────────────────────────────────────────────────────────────────
# Makefile — one-command ergonomics for the Python stack.
#
# The CI pipeline and local dev MUST use the same install path so a
# "works on my machine" gap is impossible.  Every target here shells
# out to the same manifests (requirements.txt + requirements-dev.txt)
# GitHub Actions installs from.
#
# Quick start on a clean checkout:
#
#     make setup   # creates .venv and installs runtime + dev deps
#     make check   # pip check + import validation
#     make test    # runs pytest exactly like CI does
#
# Run ``make help`` to list every target.
# ──────────────────────────────────────────────────────────────────────

VENV_DIR ?= .venv
PYTHON   ?= python3
VENV_PY  := $(VENV_DIR)/bin/python
VENV_PIP := $(VENV_DIR)/bin/pip

.DEFAULT_GOAL := help

.PHONY: help setup install check test lint syntax clean \
        install-playwright freeze

help:  ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[1m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup:  ## Create venv + install runtime & dev deps + run preflight check.
	@bash scripts/setup.sh

install:  ## Re-install deps into an existing venv (idempotent).
	@test -x "$(VENV_PY)" || { echo "No venv at $(VENV_DIR); run 'make setup' first."; exit 1; }
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PIP) install -r requirements-dev.txt
	$(VENV_PIP) check

check:  ## Preflight: pip check + env import validation.
	@test -x "$(VENV_PY)" || { echo "No venv at $(VENV_DIR); run 'make setup' first."; exit 1; }
	$(VENV_PIP) check
	$(VENV_PY) scripts/check_env.py

test: check  ## Run unit tests (same args CI uses).
	$(VENV_PY) -m pytest tests/ -x -q --tb=short

syntax:  ## Python syntax gate on the critical files CI compiles.
	@test -x "$(VENV_PY)" || { echo "No venv at $(VENV_DIR); run 'make setup' first."; exit 1; }
	$(VENV_PY) -m py_compile server.py "Dynasty Scraper.py"
	$(VENV_PY) -m py_compile src/api/data_contract.py

lint: syntax  ## Lint-equivalent gate (syntax + preflight).
	@$(MAKE) check

install-playwright:  ## Install the Playwright Chromium browser.
	@test -x "$(VENV_PY)" || { echo "No venv at $(VENV_DIR); run 'make setup' first."; exit 1; }
	$(VENV_PY) -m playwright install chromium

freeze:  ## Write a reproducible lockfile of the current env.
	@test -x "$(VENV_PY)" || { echo "No venv at $(VENV_DIR); run 'make setup' first."; exit 1; }
	$(VENV_PIP) freeze > requirements.lock.txt
	@echo "Wrote requirements.lock.txt ($$(wc -l < requirements.lock.txt) lines)"

clean:  ## Remove the virtualenv.
	rm -rf "$(VENV_DIR)"
