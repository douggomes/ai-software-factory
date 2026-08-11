"""Failure taxonomy — normalized categories for worker and operational failures.

Failures are classified into stable categories that determine the disposition
(retry, failover, repair, escalate). Unknown failures default to
HumanIntervention — never automatic retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class FailureCategory(Enum):
    """Normalized failure categories from the domain model."""

    QUOTA_EXHAUSTED = auto()
    RATE_LIMITED = auto()
    NETWORK_ERROR = auto()
    TIMEOUT = auto()
    WORKER_CRASH = auto()
    WORKER_INTERRUPTED = auto()
    QUALITY_GATE_FAILURE = auto()
    CONFIGURATION_ERROR = auto()
    AUTHENTICATION_ERROR = auto()
    WORKTREE_ERROR = auto()
    SPEC_VALIDATION_ERROR = auto()
    HUMAN_INTERVENTION = auto()


class FailureDisposition(Enum):
    """What the system should do in response to a failure."""

    RETRY_SAME_WORKER = auto()
    FAILOVER_TO_OTHER_WORKER = auto()
    REPAIR_WITH_FEEDBACK = auto()
    ESCALATE_TO_HUMAN = auto()
    ABORT = auto()


@dataclass(frozen=True, slots=True)
class NormalizedFailure:
    """A failure normalized to the domain taxonomy.

    Immutable record linking a failure to its source attempt and category.
    The disposition is determined by policy based on category and context.
    """

    category: FailureCategory
    message: str
    attempt_id: str
    worker_id: str
    disposition: FailureDisposition | None = None
    retryable: bool = False


DEFAULT_DISPOSITIONS: dict[FailureCategory, FailureDisposition] = {
    FailureCategory.QUOTA_EXHAUSTED: FailureDisposition.FAILOVER_TO_OTHER_WORKER,
    FailureCategory.RATE_LIMITED: FailureDisposition.RETRY_SAME_WORKER,
    FailureCategory.NETWORK_ERROR: FailureDisposition.RETRY_SAME_WORKER,
    FailureCategory.TIMEOUT: FailureDisposition.RETRY_SAME_WORKER,
    FailureCategory.WORKER_CRASH: FailureDisposition.FAILOVER_TO_OTHER_WORKER,
    FailureCategory.WORKER_INTERRUPTED: FailureDisposition.FAILOVER_TO_OTHER_WORKER,
    FailureCategory.QUALITY_GATE_FAILURE: FailureDisposition.REPAIR_WITH_FEEDBACK,
    FailureCategory.CONFIGURATION_ERROR: FailureDisposition.ESCALATE_TO_HUMAN,
    FailureCategory.AUTHENTICATION_ERROR: FailureDisposition.ESCALATE_TO_HUMAN,
    FailureCategory.WORKTREE_ERROR: FailureDisposition.ESCALATE_TO_HUMAN,
    FailureCategory.SPEC_VALIDATION_ERROR: FailureDisposition.ABORT,
    FailureCategory.HUMAN_INTERVENTION: FailureDisposition.ESCALATE_TO_HUMAN,
}


def resolve_disposition(failure: NormalizedFailure) -> FailureDisposition:
    """Determine the disposition for a normalized failure.

    If the failure already has a disposition, use it. Otherwise, look up
    the default for the category. Unknown categories escalate to human.
    """
    if failure.disposition is not None:
        return failure.disposition
    return DEFAULT_DISPOSITIONS.get(failure.category, FailureDisposition.ESCALATE_TO_HUMAN)
