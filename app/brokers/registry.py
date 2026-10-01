from app.brokers.base import BrokerAdapter
from app.brokers.mock import MockBrokerAdapter
from app.brokers.real import AngelOneAdapter, FyersAdapter, GrowwAdapter, UpstoxAdapter, ZerodhaAdapter
from app.domain.models import BrokerAdapterInfo, BrokerName


class BrokerRegistry:
    def __init__(
        self,
        adapters: dict[BrokerName | str, BrokerAdapter] | None = None,
        *,
        mock_fail_symbols: set[str] | None = None,
    ):
        default_adapters: dict[BrokerName, BrokerAdapter] = {
            BrokerName.ZERODHA: ZerodhaAdapter(), BrokerName.FYERS: FyersAdapter(),
            BrokerName.ANGELONE: AngelOneAdapter(), BrokerName.GROWW: GrowwAdapter(),
            BrokerName.UPSTOX: UpstoxAdapter(), BrokerName.MOCK: MockBrokerAdapter(fail_symbols=mock_fail_symbols),
        }
        self._adapters = (
            {BrokerName(name): adapter for name, adapter in adapters.items()}
            if adapters is not None
            else default_adapters
        )

    def get(self, broker: BrokerName) -> BrokerAdapter:
        return self._adapters[broker]

    def names(self) -> list[str]:
        return [name.value for name in self._adapters]

    def describe(self) -> list[BrokerAdapterInfo]:
        return [adapter.describe() for adapter in self._adapters.values()]
