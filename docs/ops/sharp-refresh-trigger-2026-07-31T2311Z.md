# Sharp production refresh trigger

Triggered at **2026-07-31 23:11 UTC** after the production Sharp Tracker still showed no market data.

Purpose:

- force a fresh production deployment of the latest `main` commit;
- restart the backend so `/api/sharp/market` and `/api/sharp/market/audit` are registered;
- run the deploy-time Sharp systemd bootstrap;
- start the Sleeper discovery/records population pass;
- start the public-only FFPC collection pass;
- allow the production Sharp smoke workflow to verify non-zero population.

This file is an auditable one-time deployment trigger. It contains no application logic or credentials.
