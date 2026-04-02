"""
Intervention module for real-time capability building.

Phase 10: Real-Time Intervention

This module implements the autonomous intervention loop that:
1. Receives blocked challenges from Phase 9 pre-execution analysis
2. Builds missing capabilities using Developer Team
3. Injects capabilities without system restart
4. Re-assesses and resolves challenges

Per CONTEXT decisions:
- Fully autonomous - no user approval gates
- 5 attempts max before notifying user
- Build critical/important gaps first
- Mark capabilities as provisional for review

Usage:
    from app.orchestration.intervention import (
        InterventionOrchestrator,
        create_intervention_orchestrator
    )

    orchestrator = await create_intervention_orchestrator(db)

    # Process single challenge
    response = await orchestrator.process_single_challenge(challenge_id)

    # Or run continuous loop (as background task)
    await orchestrator.run_intervention_loop()
"""
from app.orchestration.intervention.queue_manager import BlockedChallengeQueue
from app.orchestration.intervention.retry_strategy import (
    RetryStrategy,
    ApproachSelector,
    ApproachConfig,
    ApproachType
)
from app.orchestration.intervention.capability_builder import CapabilityBuilder
from app.orchestration.intervention.injector import CapabilityInjector
from app.orchestration.intervention.orchestrator import (
    InterventionOrchestrator,
    create_intervention_orchestrator
)

__all__ = [
    # Core orchestrator
    "InterventionOrchestrator",
    "create_intervention_orchestrator",
    # Queue management
    "BlockedChallengeQueue",
    # Capability building
    "CapabilityBuilder",
    "CapabilityInjector",
    # Retry strategy
    "RetryStrategy",
    "ApproachSelector",
    "ApproachConfig",
    "ApproachType",
]
