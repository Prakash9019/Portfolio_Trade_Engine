from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from app.domain.models import BrokerAdapterInfo, BrokerOrderResult, Order


class BrokerError(Exception):
    """Base adapter error translated into a normalized execution result."""


class BrokerAuthenticationError(BrokerError):
    """Credentials, session, or broker authorization is invalid."""


class BrokerIntegrationNotConfigured(BrokerAuthenticationError):
    """A named provider adapter exists, but no verified official client is wired in."""


class BrokerLiveTradingDisabledError(BrokerAuthenticationError):
    """The process safety switch intentionally blocks live brokerage calls."""


class BrokerRejectedOrderError(BrokerError):
    """The broker definitely rejected the order; retrying will not help."""


class TransientBrokerError(BrokerError):
    """The broker failed before accepting an order; a bounded retry is safe."""


class AmbiguousOrderPlacementError(BrokerError):
    """The network outcome is unknown; never automatically retry placement."""


class BrokerTimeoutError(AmbiguousOrderPlacementError):
    """A placement timeout whose acceptance state must be reconciled, not retried."""


class BrokerAdapter(ABC):
    """Provider boundary. The execution service only depends on this contract."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def describe(self) -> BrokerAdapterInfo: ...

    @abstractmethod
    def authenticate(self) -> None: ...

    @abstractmethod
    def get_holdings(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def translate_order(self, order: Order) -> Mapping[str, Any]: ...

    @abstractmethod
    def translate_response(self, raw_response: Mapping[str, Any], order: Order) -> BrokerOrderResult: ...

    @abstractmethod
    def translate_error(self, error: Exception) -> BrokerError: ...

    @abstractmethod
    def place_order(self, order: Order) -> BrokerOrderResult: ...

    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> BrokerOrderResult: ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> None: ...

