import re
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class BrokerName(StrEnum):
    ZERODHA = "zerodha"
    FYERS = "fyers"
    ANGELONE = "angelone"
    GROWW = "groww"
    UPSTOX = "upstox"
    MOCK = "mock"


class BrokerIntegrationStatus(StrEnum):
    MOCK = "MOCK"
    SCAFFOLD = "SCAFFOLD"


class ExecutionType(StrEnum):
    FIRST_TIME = "FIRST_TIME"
    REBALANCE = "REBALANCE"


class ExecutionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILURE = "FAILURE"


class OrderAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    ADJUST = "ADJUST"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"
    CANCELLED = "CANCELLED"


class OrderInstruction(BaseModel):
    """An explicit trade instruction; REBALANCE never implies delta calculation."""

    symbol: str = Field(min_length=1, max_length=30)
    quantity: int = Field(gt=0)
    side: OrderSide
    action: OrderAction | None = None
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = Field(default=None, gt=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9&.-]*", value):
            raise ValueError("symbol must contain only letters, numbers, '&', '.', or '-'")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> "OrderInstruction":
        if self.action is None:
            self.action = OrderAction(self.side.value)
        if self.action == OrderAction.BUY and self.side != OrderSide.BUY:
            raise ValueError("BUY action requires BUY side")
        if self.action == OrderAction.SELL and self.side != OrderSide.SELL:
            raise ValueError("SELL action requires SELL side")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT orders")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price is only valid for LIMIT orders")
        return self


class ExecutePortfolioRequest(BaseModel):
    broker: BrokerName
    execution_type: ExecutionType
    orders: list[OrderInstruction] = Field(min_length=1, max_length=100)

    @field_validator("orders")
    @classmethod
    def validate_orders(cls, orders: list[OrderInstruction]) -> list[OrderInstruction]:
        symbols = [order.symbol for order in orders]
        if len(symbols) != len(set(symbols)):
            raise ValueError("duplicate or conflicting instructions for the same symbol are not allowed")
        return orders

    @model_validator(mode="after")
    def validate_execution_semantics(self) -> "ExecutePortfolioRequest":
        if self.execution_type == ExecutionType.FIRST_TIME:
            invalid = [order.symbol for order in self.orders if order.action != OrderAction.BUY]
            if invalid:
                raise ValueError("FIRST_TIME executions may contain BUY instructions only")
        return self


class Order(BaseModel):
    client_order_id: str
    symbol: str
    quantity: int
    side: OrderSide
    action: OrderAction
    order_type: OrderType
    limit_price: Decimal | None = None


class BrokerOrderResult(BaseModel):
    client_order_id: str
    symbol: str
    side: OrderSide
    action: OrderAction
    quantity: int = Field(ge=0)
    status: OrderStatus
    broker_order_id: str | None = None
    message: str | None = None
    error_code: str | None = None
    attempts: int = Field(default=1, ge=0)


class PortfolioExecutionResult(BaseModel):
    execution_id: str
    status: ExecutionStatus
    broker: BrokerName
    execution_type: ExecutionType
    results: list[BrokerOrderResult]
    successful_count: int
    failed_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BrokerAdapterInfo(BaseModel):
    name: BrokerName
    integration_status: BrokerIntegrationStatus
    live_execution_enabled: bool
    official_docs_url: str | None = None
    limitations: str
