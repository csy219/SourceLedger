"""SourceLedger capability handlers."""

from runtime.api.capabilities import (
    CapabilityRegistry,
)
from runtime.capabilities.retrieval import (
    register_retrieval_capabilities,
)
from runtime.capabilities.resilience import (
    register_core_resilience_capabilities,
)
from runtime.capabilities.security import (
    register_security_capabilities,
)


def register_default_capabilities(
    registry: CapabilityRegistry,
) -> None:
    register_retrieval_capabilities(
        registry
    )
    register_core_resilience_capabilities(
        registry
    )
    register_security_capabilities(
        registry
    )