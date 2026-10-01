import hashlib
import json
import logging
from time import sleep
from uuid import uuid4

from app.brokers.base import (
    AmbiguousOrderPlacementError,
    BrokerAuthenticationError,
    BrokerError,
    BrokerLiveTradingDisabledError,
    BrokerRejectedOrderError,
    TransientBrokerError,
)
from app.brokers.registry import BrokerRegistry
from app.core.config import Settings
from app.domain.models import (
    BrokerName,
    BrokerOrderResult,
    ExecutePortfolioRequest,
    ExecutionStatus,
    Order,
    OrderStatus,
    PortfolioExecutionResult,
)
from app.notifications.service import NotificationService
from app.repositories.executions import ExecutionRepository

logger = logging.getLogger(__name__)


class ExecutionService:
    def __init__(
        self,
        registry: BrokerRegistry,
        repository: ExecutionRepository,
        notifier: NotificationService,
        settings: Settings,
    ):
        self.registry = registry
        self.repository = repository
        self.notifier = notifier
        self.settings = settings

    def execute(self, request: ExecutePortfolioRequest, idempotency_key: str) -> PortfolioExecutionResult:
        reservation = self.repository.reserve(idempotency_key, self._fingerprint(request))
        if not reservation.is_owner:
            return self.repository.result_for(reservation, self.settings.idempotency_wait_seconds)

        try:
            result = self._execute_reserved_request(request)
        except Exception:  # Always release same-key waiters, even on an orchestration bug.
            logger.exception("portfolio_execution_unexpected_failure")
            result = self._all_orders_failed(
                str(uuid4()),
                request,
                BrokerRejectedOrderError("unexpected execution failure before completion"),
            )
        self.repository.complete(reservation, result)
        self._notify_safely(result)
        return result

    def _execute_reserved_request(self, request: ExecutePortfolioRequest) -> PortfolioExecutionResult:
        execution_id = str(uuid4())
        adapter = self.registry.get(request.broker)

        if request.broker != BrokerName.MOCK and not self.settings.live_trading_enabled:
            return self._all_orders_failed(
                execution_id,
                request,
                BrokerLiveTradingDisabledError(
                    "live trading is disabled; only the mock adapter can execute in this environment"
                ),
            )

        try:
            adapter.authenticate()
        except BrokerAuthenticationError as exc:
            return self._all_orders_failed(execution_id, request, exc)

        outcomes: list[BrokerOrderResult] = []
        for index, instruction in enumerate(request.orders, start=1):
            order = Order(client_order_id=f"{execution_id}-{index}", **instruction.model_dump())
            try:
                outcomes.append(self._place_with_safe_retries(adapter, order))
            except AmbiguousOrderPlacementError as exc:
                outcomes.append(self._failed_order(order, OrderStatus.AMBIGUOUS, exc))
            except BrokerError as exc:
                outcomes.append(self._failed_order(order, OrderStatus.FAILED, exc))
            except Exception as exc:  # Keep one unexpected provider failure isolated to its order.
                outcomes.append(self._failed_order(order, OrderStatus.FAILED, adapter.translate_error(exc)))
        return self._result(execution_id, request, outcomes)

    def _place_with_safe_retries(self, adapter, order: Order) -> BrokerOrderResult:
        for attempt in range(1, self.settings.retry_attempts + 1):
            try:
                result = adapter.place_order(order)
                return result.model_copy(update={"attempts": attempt})
            except Exception as exc:
                error = exc if isinstance(exc, BrokerError) else adapter.translate_error(exc)
                if not isinstance(error, TransientBrokerError):
                    raise error
                if attempt == self.settings.retry_attempts:
                    raise error
                if self.settings.retry_backoff_seconds:
                    sleep(self.settings.retry_backoff_seconds * attempt)
        raise RuntimeError("retry loop exhausted")

    def _all_orders_failed(
        self,
        execution_id: str,
        request: ExecutePortfolioRequest,
        error: BrokerError,
    ) -> PortfolioExecutionResult:
        outcomes = [
            self._failed_order(
                Order(client_order_id=f"{execution_id}-{index}", **instruction.model_dump()),
                OrderStatus.FAILED,
                error,
                attempts=0,
            )
            for index, instruction in enumerate(request.orders, start=1)
        ]
        return self._result(execution_id, request, outcomes)

    @staticmethod
    def _failed_order(
        order: Order,
        status: OrderStatus,
        error: BrokerError,
        *,
        attempts: int = 1,
    ) -> BrokerOrderResult:
        return BrokerOrderResult(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            action=order.action,
            quantity=order.quantity,
            status=status,
            message=str(error),
            error_code=ExecutionService._error_code(error),
            attempts=attempts,
        )

    @staticmethod
    def _error_code(error: BrokerError) -> str:
        if isinstance(error, BrokerLiveTradingDisabledError):
            return "LIVE_TRADING_DISABLED"
        if isinstance(error, BrokerAuthenticationError):
            return "AUTHENTICATION_FAILED"
        if isinstance(error, AmbiguousOrderPlacementError):
            return "AMBIGUOUS_ORDER_PLACEMENT"
        if isinstance(error, TransientBrokerError):
            return "SAFE_RETRY_EXHAUSTED"
        if isinstance(error, BrokerRejectedOrderError):
            return "BROKER_REJECTED"
        return "BROKER_ERROR"

    @staticmethod
    def _fingerprint(request: ExecutePortfolioRequest) -> str:
        serialized = json.dumps(
            request.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _result(
        execution_id: str,
        request: ExecutePortfolioRequest,
        outcomes: list[BrokerOrderResult],
    ) -> PortfolioExecutionResult:
        failed_count = sum(outcome.status != OrderStatus.ACCEPTED for outcome in outcomes)
        status = (
            ExecutionStatus.SUCCESS
            if failed_count == 0
            else ExecutionStatus.PARTIAL_FAILURE
            if failed_count < len(outcomes)
            else ExecutionStatus.FAILURE
        )
        return PortfolioExecutionResult(
            execution_id=execution_id,
            status=status,
            broker=request.broker,
            execution_type=request.execution_type,
            results=outcomes,
            successful_count=len(outcomes) - failed_count,
            failed_count=failed_count,
        )

    def _notify_safely(self, result: PortfolioExecutionResult) -> None:
        try:
            self.notifier.notify(result)
        except Exception:  # Notifications must not rewrite a completed execution result.
            logger.exception("portfolio_execution_notification_failed execution_id=%s", result.execution_id)
