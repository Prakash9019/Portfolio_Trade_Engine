"""Provider-specific translation seams for official broker clients.

These adapters deliberately make no network calls in this take-home repository.
Their translation methods document the normalized-to-provider boundary, while a
future official SDK/HTTP client can be injected behind the same interface only
after credentials, instrument resolution, account permissions, and regulatory
requirements have been verified.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from app.brokers.base import (
    AmbiguousOrderPlacementError,
    BrokerAdapter,
    BrokerAuthenticationError,
    BrokerError,
    BrokerIntegrationNotConfigured,
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
    OrderType,
)


def _price(order: Order) -> str:
    return str(order.limit_price if order.limit_price is not None else Decimal("0"))


class ConfiguredBrokerAdapter(BrokerAdapter):
    """Base for a named broker whose live client has intentionally not been wired."""

    broker: BrokerName
    official_docs_url: str
    integration_limitations: str

    @property
    def name(self) -> str:
        return self.broker.value

    def describe(self) -> BrokerAdapterInfo:
        return BrokerAdapterInfo(
            name=self.broker,
            integration_status=BrokerIntegrationStatus.SCAFFOLD,
            live_execution_enabled=False,
            official_docs_url=self.official_docs_url,
            limitations=self.integration_limitations,
        )

    def authenticate(self) -> None:
        raise BrokerIntegrationNotConfigured(
            f"{self.broker.value} is an integration scaffold: no verified official client, "
            "credential/session provider, or live-trading approval is configured"
        )

    def get_holdings(self) -> list[dict[str, Any]]:
        self.authenticate()
        raise AssertionError("authenticate always raises for a scaffold")

    def place_order(self, order: Order) -> BrokerOrderResult:
        self.authenticate()
        raise AssertionError("authenticate always raises for a scaffold")

    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult:
        self.authenticate()
        raise AssertionError("authenticate always raises for a scaffold")

    def cancel_order(self, broker_order_id: str) -> None:
        self.authenticate()

    def translate_error(self, error: Exception) -> BrokerError:
        if isinstance(error, BrokerError):
            return error
        if isinstance(error, TimeoutError):
            return BrokerTimeoutError("provider timeout after an order may have been submitted")
        if isinstance(error, ConnectionError):
            return TransientBrokerError("provider connection failed before order acceptance")
        return BrokerRejectedOrderError(str(error) or "provider rejected the request")

    @staticmethod
    def _result(
        order: Order,
        *,
        accepted: bool,
        broker_order_id: str | None,
        message: str | None = None,
    ) -> BrokerOrderResult:
        return BrokerOrderResult(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            action=order.action,
            quantity=order.quantity,
            status=OrderStatus.ACCEPTED if accepted else OrderStatus.REJECTED,
            broker_order_id=broker_order_id,
            message=message,
            error_code=None if accepted else "BROKER_REJECTED",
        )


class ZerodhaAdapter(ConfiguredBrokerAdapter):
    broker = BrokerName.ZERODHA
    official_docs_url = "https://kite.trade/docs/connect/v3/orders/"
    integration_limitations = (
        "Scaffold only. Wire the official Kite Connect client/session flow and an instrument catalog; "
        "do not enable live trading until account permissions and order postbacks are verified."
    )

    def translate_order(self, order: Order) -> Mapping[str, Any]:
        return {
            "exchange": "NSE",
            "tradingsymbol": order.symbol,
            "transaction_type": order.side.value,
            "quantity": order.quantity,
            "order_type": order.order_type.value,
            "product": "CNC",
            "validity": "DAY",
            "price": _price(order),
            "tag": order.client_order_id[-20:],
        }

    def translate_response(self, raw_response: Mapping[str, Any], order: Order) -> BrokerOrderResult:
        data = raw_response.get("data") if isinstance(raw_response.get("data"), Mapping) else {}
        order_id = data.get("order_id") if isinstance(data, Mapping) else None
        return self._result(
            order,
            accepted=raw_response.get("status") == "success" and isinstance(order_id, str),
            broker_order_id=order_id if isinstance(order_id, str) else None,
            message=raw_response.get("message") if isinstance(raw_response.get("message"), str) else None,
        )


class FyersAdapter(ConfiguredBrokerAdapter):
    broker = BrokerName.FYERS
    official_docs_url = "https://myapi.fyers.in/docsv3#tag/Order-Placement-Guide"
    integration_limitations = (
        "Scaffold only. Verify the active FYERS API v3 app, static-IP and retail-algo permissions, "
        "then wire the official client and current instrument-symbol resolver."
    )

    def translate_order(self, order: Order) -> Mapping[str, Any]:
        return {
            "symbol": f"NSE:{order.symbol}-EQ",
            "qty": order.quantity,
            "type": 2 if order.order_type == OrderType.MARKET else 1,
            "side": 1 if order.side.value == "BUY" else -1,
            "productType": "CNC",
            "limitPrice": float(order.limit_price or 0),
            "stopPrice": 0,
            "validity": "DAY",
            "offlineOrder": False,
            "orderTag": order.client_order_id[-20:],
        }

    def translate_response(self, raw_response: Mapping[str, Any], order: Order) -> BrokerOrderResult:
        order_id = raw_response.get("id")
        return self._result(
            order,
            accepted=raw_response.get("s") == "ok" and isinstance(order_id, str),
            broker_order_id=order_id if isinstance(order_id, str) else None,
            message=raw_response.get("message") if isinstance(raw_response.get("message"), str) else None,
        )


class AngelOneAdapter(ConfiguredBrokerAdapter):
    broker = BrokerName.ANGELONE
    official_docs_url = "https://smartapi.angelone.in/docs"
    integration_limitations = (
        "Scaffold only. An official SmartAPI client requires credential/session handling, a symbol-token "
        "resolver, and current static-IP/compliance checks before any live order path can be enabled."
    )

    def translate_order(self, order: Order) -> Mapping[str, Any]:
        return {
            "variety": "NORMAL",
            "tradingsymbol": f"{order.symbol}-EQ",
            "symboltoken": None,
            "exchange": "NSE",
            "transactiontype": order.side.value,
            "ordertype": order.order_type.value,
            "producttype": "DELIVERY",
            "duration": "DAY",
            "price": _price(order),
            "quantity": str(order.quantity),
            "ordertag": order.client_order_id[-20:],
            "_requires": "Resolve symboltoken from the current Angel One instrument master before submission.",
        }

    def translate_response(self, raw_response: Mapping[str, Any], order: Order) -> BrokerOrderResult:
        data = raw_response.get("data") if isinstance(raw_response.get("data"), Mapping) else {}
        order_id = data.get("orderid") if isinstance(data, Mapping) else None
        return self._result(
            order,
            accepted=raw_response.get("status") is True and isinstance(order_id, str),
            broker_order_id=order_id if isinstance(order_id, str) else None,
            message=raw_response.get("message") if isinstance(raw_response.get("message"), str) else None,
        )


class GrowwAdapter(ConfiguredBrokerAdapter):
    broker = BrokerName.GROWW
    official_docs_url = "https://groww.in/trade-api/docs/curl/orders"
    integration_limitations = (
        "Scaffold only. Wire the official API token flow and account/instrument validation before enabling "
        "the documented order_reference_id reconciliation path."
    )

    def translate_order(self, order: Order) -> Mapping[str, Any]:
        return {
            "trading_symbol": order.symbol,
            "quantity": order.quantity,
            "price": float(order.limit_price or 0),
            "validity": "DAY",
            "exchange": "NSE",
            "segment": "CASH",
            "product": "CNC",
            "order_type": order.order_type.value,
            "transaction_type": order.side.value,
            "order_reference_id": order.client_order_id[-20:],
        }

    def translate_response(self, raw_response: Mapping[str, Any], order: Order) -> BrokerOrderResult:
        payload = raw_response.get("payload") if isinstance(raw_response.get("payload"), Mapping) else {}
        order_id = payload.get("groww_order_id") if isinstance(payload, Mapping) else None
        return self._result(
            order,
            accepted=raw_response.get("status") == "SUCCESS" and isinstance(order_id, str),
            broker_order_id=order_id if isinstance(order_id, str) else None,
            message=payload.get("remark") if isinstance(payload, Mapping) and isinstance(payload.get("remark"), str) else None,
        )


class UpstoxAdapter(ConfiguredBrokerAdapter):
    broker = BrokerName.UPSTOX
    official_docs_url = "https://upstox.com/developer/api-documentation/v3/place-order/"
    integration_limitations = (
        "Scaffold only. An official Upstox client needs OAuth/session handling and a current instrument-token "
        "resolver; use its sandbox before enabling a reviewed live path."
    )

    def translate_order(self, order: Order) -> Mapping[str, Any]:
        return {
            "quantity": order.quantity,
            "product": "D",
            "validity": "DAY",
            "price": float(order.limit_price or 0),
            "instrument_token": None,
            "order_type": order.order_type.value,
            "transaction_type": order.side.value,
            "tag": order.client_order_id[-20:],
            "_requires": "Resolve instrument_token from the current Upstox instrument master before submission.",
        }

    def translate_response(self, raw_response: Mapping[str, Any], order: Order) -> BrokerOrderResult:
        data = raw_response.get("data") if isinstance(raw_response.get("data"), Mapping) else {}
        order_id = data.get("order_id") if isinstance(data, Mapping) else None
        return self._result(
            order,
            accepted=raw_response.get("status") == "success" and isinstance(order_id, str),
            broker_order_id=order_id if isinstance(order_id, str) else None,
            message=raw_response.get("message") if isinstance(raw_response.get("message"), str) else None,
        )

