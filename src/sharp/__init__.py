"""Sharp Tracker — market intelligence from a QUALIFIED manager cohort.

Deliberately separate from ``src/intel/``'s Insider Trading product.
They share the transaction ledger (``src.intel.ledger``) and nothing
else: different cohorts, different scope, different questions.

    Insider Trading   the managers in ONE league, no skill filter,
                      answering "who in my league already wants this
                      player" — league-scoped by necessity.

    Sharp Tracker     a skill-qualified cohort drawn from every league
                      we observe, answering "what is the smart money
                      doing" — deliberately NOT league-scoped.

Modules:
    score.py    the Sharp Score: eligibility gates, components,
                confidence, and qualification
    service.py  cohort status + board assembly over the shared ledger
"""

from __future__ import annotations
