from collections import defaultdict
from collections.abc import Mapping
from threading import Lock
from typing import Any

from app.brokers.base import (
    BrokerAdapter,
    BrokerError,
    BrokerRejectedOrderError,
    BrokerTimeoutError,
    TransientBrokerError,
)
from app.domain.models import (
    BrokerAdapterInfo,
    BrokerIntegrationStatus,
    BrokerName,
    BrokerOrderResult,
    Order,
    OrderStatus,
)


class MockBrokerAdapter(BrokerAdapter):
    """Deterministic in-memory adapter used for all assignment demonstrations."""

    @property
    def name(self) -> str:
        return BrokerName.MOCK.value

    def __init__(
        self,
        *,
        fail_symbols: set[str] | None = None,
        transient_failures: int = 0,
        holdings: list[dict[str, Any]] | None = None,
    ):
        self.fail_symbols = {symbol.upper() for symbol in (fail_symbols or set())}
        self.transient_failures = transient_failures
        self.holdings = holdings or []
        self.calls: defaultdict[str, int] = defaultdict(int)
        self._orders: dict[str, BrokerOrderResult] = {}
        self._by_client_order_id: dict[str, str] = {}
        self._lock = Lock()

    def describe(self) -> BrokerAdapterInfo:
        return BrokerAdapterInfo(
            name=BrokerName.MOCK,
            integration_status=BrokerIntegrationStatus.MOCK,
            live_execution_enabled=False,
            limitations="Deterministic local-only broker. It never contacts a brokerage or exchange.",
        )

    def authenticate(self) -> None:
        return None

    def get_holdings(self) -> list[dict[str, Any]]:
        return [holding.copy() for holding in self.holdings]

    def translate_order(self, order: Order) -> Mapping[str, Any]:
        return order.model_dump(mode="json")

    def translate_response(self, raw_response: Mapping[str, Any], order: Order) -> BrokerOrderResult:
        accepted = raw_response.get("status") == "accepted"
        broker_order_id = raw_response.get("broker_order_id")
        return BrokerOrderResult(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            action=order.action,
            quantity=order.quantity,
            status=OrderStatus.ACCEPTED if accepted else OrderStatus.REJECTED,
            broker_order_id=broker_order_id if isinstance(broker_order_id, str) else None,
            message=raw_response.get("message") if isinstance(raw_response.get("message"), str) else None,
            error_code=None if accepted else "MOCK_REJECTED",
        )

    def translate_error(self, error: Exception) -> BrokerError:
        if isinstance(error, BrokerError):
            return error
        if isinstance(error, TimeoutError):
            return BrokerTimeoutError("mock timeout after simulated submission")
        return BrokerRejectedOrderError(str(error) or "mock broker error")

    def place_order(self, order: Order) -> BrokerOrderResult:
        with self._lock:
            existing_id = self._by_client_order_id.get(order.client_order_id)
            if existing_id:
                return self._orders[existing_id].model_copy(deep=True)

            self.calls[order.client_order_id] += 1
            attempt = self.calls[order.client_order_id]
            if attempt <= self.transient_failures:
                raise TransientBrokerError("temporary mock rate limit before acceptance")

            if order.symbol in self.fail_symbols:
                return BrokerOrderResult(
                    client_order_id=order.client_order_id,
                    symbol=order.symbol,
                    side=order.side,
                    action=order.action,
                    quantity=order.quantity,
                    status=OrderStatus.REJECTED,
                    message="mock rejection for deterministic failure testing",
                    error_code="MOCK_REJECTED",
                    attempts=attempt,
                )

            broker_order_id = f"MOCK-{order.client_order_id}"
            result = BrokerOrderResult(
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                action=order.action,
                quantity=order.quantity,
                status=OrderStatus.ACCEPTED,
                broker_order_id=broker_order_id,
                message="accepted by mock broker",
                attempts=attempt,
            )
            self._orders[broker_order_id] = result
            self._by_client_order_id[order.client_order_id] = broker_order_id
            return result.model_copy(deep=True)

    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult:
        with self._lock:
            result = self._orders.get(broker_order_id)
            if result is None:
                raise BrokerRejectedOrderError(f"mock order {broker_order_id} was not found")
            return result.model_copy(deep=True)

    def cancel_order(self, broker_order_id: str) -> None:
        with self._lock:
            result = self._orders.get(broker_order_id)
            if result is None:
                raise BrokerRejectedOrderError(f"mock order {broker_order_id} was not found")
            if result.status == OrderStatus.CANCELLED:
                return None
            if result.status != OrderStatus.ACCEPTED:
                raise BrokerRejectedOrderError(f"mock order {broker_order_id} cannot be cancelled")
            self._orders[broker_order_id] = result.model_copy(update={
                "status": OrderStatus.CANCELLED,
                "message": "cancelled by mock broker",
            })
        return None

