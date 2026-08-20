"""Cross-position bridge layer — one owner for offense↔IDP translation evidence.

A *specialist* source answers "who is better within this domain".  A *bridge*
answers "what is that domain position worth against the overall market".
Conflating them is what lets an IDP-only board claim cross-position
information it does not possess.

This package owns what a bridge IS, what it DECLARES, what is MEASURED about
it, and whether it may translate.  It deliberately does not own how several
bridges' opinions are combined — that has an existing canonical owner in the
valuation pipeline, and a second one here would be a second methodology.
"""

from src.bridges.assess import assess_bridge, assess_bridges, usable_bridges
from src.bridges.descriptor import (
    BRIDGE_KINDS,
    CARDINAL,
    ORDINAL,
    BridgeAssessment,
    BridgeCapability,
    BridgeDescriptor,
    measure_capability,
)
from src.bridges.states import (
    BRIDGE_STATES,
    COMPARABILITY_STATUSES,
    DEPENDENT_SOURCE_FAMILY,
    DISPROVEN,
    INSUFFICIENT_COVERAGE,
    NOT_COMPARABLE,
    PENDING,
    QUALIFIED,
    USABLE_BRIDGE_STATES,
    VALID,
)

__all__ = [
    "BRIDGE_KINDS",
    "BRIDGE_STATES",
    "CARDINAL",
    "COMPARABILITY_STATUSES",
    "DEPENDENT_SOURCE_FAMILY",
    "DISPROVEN",
    "INSUFFICIENT_COVERAGE",
    "NOT_COMPARABLE",
    "ORDINAL",
    "PENDING",
    "QUALIFIED",
    "USABLE_BRIDGE_STATES",
    "VALID",
    "BridgeAssessment",
    "BridgeCapability",
    "BridgeDescriptor",
    "assess_bridge",
    "assess_bridges",
    "measure_capability",
    "usable_bridges",
]
