"""Operational diagnostics: durable scrape telemetry and /proc probes.

Deliberately dependency-free (pure stdlib) and free of import-time side
effects, because two very different callers import it:

* ``server.py`` — the live FastAPI process;
* ``scripts/scrape_resource_sampler.py`` — a detached sampler process
  whose entire job is to keep running *after* ``server.py`` has been
  killed, and which therefore must never import ``server.py``.
"""
