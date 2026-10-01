import logging
from threading import Event, Thread
from time import sleep

import pytest
from fastapi.testclient import TestClient

from app.brokers.base import BrokerAuthenticationError, BrokerIntegrationNotConfigured, BrokerTimeoutError
from app.brokers.mock import MockBrokerAdapter
from app.brokers.real import AngelOneAdapter, FyersAdapter, GrowwAdapter, UpstoxAdapter, ZerodhaAdapter
from app.brokers.registry import BrokerRegistry
from app.core.config import Settings
from app.domain.models import (
    BrokerIntegrationStatus,
    BrokerName,
    ExecutePortfolioRequest,
    Order,
    OrderAction,
    OrderSide,
    OrderStatus,
    OrderType,
)
from app.notifications.service import NotificationService
from app.main import create_app
from app.repositories.executions import ExecutionRepository
from app.services.execution import ExecutionService


def payload(execution_type: str = "FIRST_TIME", orders: list[dict] | None = None) -> dict:
    return {
        "broker": "mock",
        "execution_type": execution_type,
        "orders": orders or [{"symbol": "INFY", "quantity": 5, "side": "BUY"}],
    }


def make_service(adapter: MockBrokerAdapter, *, retry_attempts: int = 3) -> ExecutionService:
    return ExecutionService(
        BrokerRegistry({BrokerName.MOCK: adapter}),
        ExecutionRepository(),
        NotificationService(),
        Settings(retry_attempts=retry_attempts, idempotency_wait_seconds=1),
    )


def test_health_endpoints(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert client.get("/health").json() == {"status": "ok"}


def test_broker_discovery_distinguishes_scaffolds_from_mock(client):
    response = client.get("/api/v1/brokers")
    assert response.status_code == 200
    body = response.json()
    assert {"zerodha", "fyers", "angelone", "groww", "upstox", "mock"}.issubset(body["brokers"])
    statuses = {item["name"]: item["integration_status"] for item in body["adapters"]}
    assert statuses["mock"] == "MOCK"
    assert all(statuses[name] == "SCAFFOLD" for name in {"zerodha", "fyers", "angelone", "groww", "upstox"})
    assert client.get("/brokers").status_code == 200


def test_first_time_buy_executes_and_notifies(harness):
    client, _, notifier = harness
    response = client.post("/api/v1/portfolios/execute", headers={"Idempotency-Key": "first-1"}, json=payload())
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "SUCCESS"
    assert body["results"][0]["side"] == "BUY"
    assert body["results"][0]["action"] == "BUY"
    assert notifier.results[0].execution_id == body["execution_id"]


def test_rebalance_supports_explicit_sell_buy_adjust_and_mixed_instructions(harness):
    client, _, _ = harness
    request = payload(
        "REBALANCE",
        [
            {"symbol": "TCS", "quantity": 2, "side": "SELL", "action": "SELL"},
            {"symbol": "RELIANCE", "quantity": 3, "side": "BUY", "action": "BUY"},
            {"symbol": "INFY", "quantity": 1, "side": "SELL", "action": "ADJUST"},
        ],
    )
    response = client.post("/portfolios/execute", headers={"Idempotency-Key": "rebalance-1"}, json=request)
    body = response.json()
    assert response.status_code == 200
    assert body["successful_count"] == 3
    assert [(item["action"], item["side"]) for item in body["results"]] == [
        ("SELL", "SELL"), ("BUY", "BUY"), ("ADJUST", "SELL")
    ]


def test_rebalance_adjust_can_increase_an_existing_position(harness):
    client, _, _ = harness
    request = payload("REBALANCE", [{"symbol": "INFY", "quantity": 2, "side": "BUY", "action": "ADJUST"}])
    response = client.post("/api/v1/portfolios/execute", headers={"Idempotency-Key": "adjust-buy-1"}, json=request)
    assert response.status_code == 200
    assert response.json()["results"][0]["action"] == "ADJUST"
    assert response.json()["results"][0]["side"] == "BUY"


def test_validation_rejects_invalid_quantity_duplicates_and_invalid_actions(harness):
    client, _, _ = harness
    invalid_quantity = payload(orders=[{"symbol": "INFY", "quantity": 0, "side": "BUY"}])
    assert client.post("/api/v1/portfolios/execute", headers={"Idempotency-Key": "bad-1"}, json=invalid_quantity).status_code == 422

    duplicate = payload(orders=[
        {"symbol": "INFY", "quantity": 1, "side": "BUY"},
        {"symbol": "INFY", "quantity": 1, "side": "SELL"},
    ])
    assert client.post("/api/v1/portfolios/execute", headers={"Idempotency-Key": "bad-2"}, json=duplicate).status_code == 422

    first_time_adjust = payload(orders=[{"symbol": "INFY", "quantity": 1, "side": "BUY", "action": "ADJUST"}])
    assert client.post("/api/v1/portfolios/execute", headers={"Idempotency-Key": "bad-3"}, json=first_time_adjust).status_code == 422

    mismatched_action = payload("REBALANCE", [{"symbol": "INFY", "quantity": 1, "side": "SELL", "action": "BUY"}])
    assert client.post("/api/v1/portfolios/execute", headers={"Idempotency-Key": "bad-4"}, json=mismatched_action).status_code == 422

    missing_limit_price = payload(orders=[{"symbol": "INFY", "quantity": 1, "side": "BUY", "order_type": "LIMIT"}])
    assert client.post("/api/v1/portfolios/execute", headers={"Idempotency-Key": "bad-5"}, json=missing_limit_price).status_code == 422


def test_unsupported_broker_and_missing_idempotency_key(client):
    invalid_broker = {**payload(), "broker": "not-a-broker"}
    assert client.post("/api/v1/portfolios/execute", json=invalid_broker).status_code == 422
    assert client.post("/api/v1/portfolios/execute", headers={"Idempotency-Key": "unsupported-1"}, json=invalid_broker).status_code == 422
    assert client.post("/api/v1/portfolios/execute", json=payload()).status_code == 422


def test_named_brokers_are_safely_disabled_not_falsely_live(client):
    request = {**payload(), "broker": "zerodha"}
    response = client.post("/api/v1/portfolios/execute", headers={"Idempotency-Key": "named-1"}, json=request)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "FAILURE"
    assert body["results"][0]["error_code"] == "LIVE_TRADING_DISABLED"


def test_authentication_failure_is_structured():
    class FailingAdapter(MockBrokerAdapter):
        def authenticate(self) -> None:
            raise BrokerAuthenticationError("login failed")

    service = make_service(FailingAdapter())
    result = service.execute(ExecutePortfolioRequest.model_validate(payload()), "auth-1")
    assert result.status == "FAILURE"
    assert result.results[0].error_code == "AUTHENTICATION_FAILED"
    assert result.results[0].message == "login failed"


def test_partial_failure_keeps_successful_orders_and_continues(harness):
    client, adapter, _ = harness
    adapter.fail_symbols = {"FAIL"}
    response = client.post(
        "/api/v1/portfolios/execute",
        headers={"Idempotency-Key": "partial-1"},
        json=payload(orders=[{"symbol": "GOOD", "quantity": 1, "side": "BUY"}, {"symbol": "FAIL", "quantity": 1, "side": "BUY"}]),
    )
    body = response.json()
    assert body["status"] == "PARTIAL_FAILURE"
    assert body["successful_count"] == 1
    assert body["failed_count"] == 1
    assert body["results"][1]["status"] == "REJECTED"


def test_mock_failure_symbols_setting_is_available_for_http_demo():
    with TestClient(create_app(settings=Settings(mock_fail_symbols="FAIL"))) as client:
        response = client.post(
            "/api/v1/portfolios/execute",
            headers={"Idempotency-Key": "configured-partial-1"},
            json=payload(orders=[{"symbol": "GOOD", "quantity": 1, "side": "BUY"}, {"symbol": "FAIL", "quantity": 1, "side": "BUY"}]),
        )
    assert response.json()["status"] == "PARTIAL_FAILURE"


def test_same_idempotency_key_and_same_request_returns_the_identical_execution(harness):
    client, adapter, notifier = harness
    headers = {"Idempotency-Key": "same-1"}
    response1 = client.post("/api/v1/portfolios/execute", headers=headers, json=payload())
    response2 = client.post("/api/v1/portfolios/execute", headers=headers, json=payload())
    assert response1.json() == response2.json()
    assert sum(adapter.calls.values()) == 1
    assert len(notifier.results) == 1


def test_reusing_an_idempotency_key_for_a_different_request_returns_conflict(harness):
    client, _, _ = harness
    headers = {"Idempotency-Key": "conflict-1"}
    assert client.post("/api/v1/portfolios/execute", headers=headers, json=payload()).status_code == 200
    changed = payload(orders=[{"symbol": "INFY", "quantity": 6, "side": "BUY"}])
    response = client.post("/api/v1/portfolios/execute", headers=headers, json=changed)
    assert response.status_code == 409
    assert "different request payload" in response.json()["detail"]


def test_unexpected_execution_error_completes_the_idempotency_reservation():
    class BrokenRegistry:
        def get(self, broker):
            raise RuntimeError("registry unavailable")

    service = ExecutionService(
        BrokenRegistry(),
        ExecutionRepository(),
        NotificationService(),
        Settings(idempotency_wait_seconds=1),
    )
    request = ExecutePortfolioRequest.model_validate(payload())
    first = service.execute(request, "broken-1")
    replay = service.execute(request, "broken-1")
    assert first.status == "FAILURE"
    assert first.execution_id == replay.execution_id


def test_concurrent_duplicate_requests_share_one_execution():
    class BlockingAdapter(MockBrokerAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.started = Event()
            self.release = Event()

        def place_order(self, order: Order):
            self.started.set()
            assert self.release.wait(timeout=1)
            return super().place_order(order)

    adapter = BlockingAdapter()
    service = make_service(adapter)
    request = ExecutePortfolioRequest.model_validate(payload())
    results = []

    def execute() -> None:
        results.append(service.execute(request, "concurrent-1"))

    first = Thread(target=execute)
    second = Thread(target=execute)
    first.start()
    assert adapter.started.wait(timeout=1)
    second.start()
    sleep(0.02)
    adapter.release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert len(results) == 2
    assert results[0].execution_id == results[1].execution_id
    assert sum(adapter.calls.values()) == 1


def test_bounded_safe_retry_only_retries_pre_acceptance_failures():
    adapter = MockBrokerAdapter(transient_failures=2)
    result = make_service(adapter).execute(ExecutePortfolioRequest.model_validate(payload()), "retry-1")
    assert result.status == "SUCCESS"
    assert result.results[0].attempts == 3
    assert sum(adapter.calls.values()) == 3


def test_known_rejection_is_not_retried():
    adapter = MockBrokerAdapter(fail_symbols={"FAIL"})
    request = ExecutePortfolioRequest.model_validate(payload(orders=[{"symbol": "FAIL", "quantity": 1, "side": "BUY"}]))
    result = make_service(adapter).execute(request, "rejected-1")
    assert result.results[0].status == OrderStatus.REJECTED
    assert result.results[0].attempts == 1
    assert sum(adapter.calls.values()) == 1


def test_ambiguous_timeout_is_not_retried():
    class AmbiguousAdapter(MockBrokerAdapter):
        def place_order(self, order: Order):
            self.calls[order.client_order_id] += 1
            raise BrokerTimeoutError("broker response timed out after submission")

    adapter = AmbiguousAdapter()
    result = make_service(adapter).execute(ExecutePortfolioRequest.model_validate(payload()), "timeout-1")
    assert result.status == "FAILURE"
    assert result.results[0].status == OrderStatus.AMBIGUOUS
    assert result.results[0].error_code == "AMBIGUOUS_ORDER_PLACEMENT"
    assert sum(adapter.calls.values()) == 1


def test_mock_broker_order_lifecycle():
    adapter = MockBrokerAdapter()
    order = Order(
        client_order_id="lifecycle-1",
        symbol="INFY",
        quantity=1,
        side=OrderSide.BUY,
        action=OrderAction.BUY,
        order_type=OrderType.MARKET,
    )
    accepted = adapter.place_order(order)
    assert accepted.status == OrderStatus.ACCEPTED
    assert adapter.get_order_status(accepted.broker_order_id).status == OrderStatus.ACCEPTED
    adapter.cancel_order(accepted.broker_order_id)
    assert adapter.get_order_status(accepted.broker_order_id).status == OrderStatus.CANCELLED


@pytest.mark.parametrize("adapter_type", [ZerodhaAdapter, FyersAdapter, AngelOneAdapter, GrowwAdapter, UpstoxAdapter])
def test_named_adapter_scaffolds_expose_translation_response_and_error_boundaries(adapter_type):
    adapter = adapter_type()
    order = Order(
        client_order_id="translation-1",
        symbol="INFY",
        quantity=1,
        side=OrderSide.BUY,
        action=OrderAction.BUY,
        order_type=OrderType.MARKET,
    )
    assert adapter.describe().integration_status == BrokerIntegrationStatus.SCAFFOLD
    assert adapter.translate_order(order)
    assert adapter.translate_response({}, order).status == OrderStatus.REJECTED
    assert isinstance(adapter.translate_error(TimeoutError()), BrokerTimeoutError)
    with pytest.raises(BrokerIntegrationNotConfigured):
        adapter.place_order(order)


def test_console_notification_contains_execution_summary(caplog):
    adapter = MockBrokerAdapter()
    with caplog.at_level(logging.INFO):
        make_service(adapter).execute(ExecutePortfolioRequest.model_validate(payload()), "notify-1")
    assert "portfolio_execution_complete" in caplog.text
    assert "successful_trades" in caplog.text
