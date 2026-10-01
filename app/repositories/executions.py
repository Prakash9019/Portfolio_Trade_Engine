from dataclasses import dataclass, field
from threading import Event, Lock

from app.domain.models import PortfolioExecutionResult


class IdempotencyConflictError(Exception):
    """The caller reused an idempotency key for a materially different request."""


class IdempotencyInProgressError(Exception):
    """The original request has not completed within the configured wait window."""


@dataclass
class _ExecutionRecord:
    fingerprint: str
    completed: Event = field(default_factory=Event)
    result: PortfolioExecutionResult | None = None


@dataclass(frozen=True)
class IdempotencyReservation:
    key: str
    record: _ExecutionRecord
    is_owner: bool


class ExecutionRepository:
    """In-memory idempotency coordinator for the assignment runtime.

    The reservation prevents two concurrent requests with the same key from
    placing duplicate orders in one process. It is deliberately not durable
    across process restarts; production needs a database-backed unique record.
    """

    def __init__(self):
        self._records: dict[str, _ExecutionRecord] = {}
        self._lock = Lock()

    def reserve(self, key: str, fingerprint: str) -> IdempotencyReservation:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                record = _ExecutionRecord(fingerprint=fingerprint)
                self._records[key] = record
                return IdempotencyReservation(key=key, record=record, is_owner=True)
            if record.fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "Idempotency-Key was already used with a different request payload"
                )
            return IdempotencyReservation(key=key, record=record, is_owner=False)

    def complete(self, reservation: IdempotencyReservation, result: PortfolioExecutionResult) -> None:
        if not reservation.is_owner:
            raise ValueError("only the reservation owner can complete an execution")
        with self._lock:
            reservation.record.result = result.model_copy(deep=True)
            reservation.record.completed.set()

    def result_for(self, reservation: IdempotencyReservation, wait_seconds: float) -> PortfolioExecutionResult:
        if not reservation.record.completed.wait(timeout=wait_seconds):
            raise IdempotencyInProgressError(
                "An execution with this Idempotency-Key is still in progress; retry later with the same key"
            )
        with self._lock:
            if reservation.record.result is None:
                raise IdempotencyInProgressError("The idempotent execution did not produce a result")
            return reservation.record.result.model_copy(deep=True)

