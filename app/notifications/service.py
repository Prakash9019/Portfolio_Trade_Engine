import logging

from app.domain.models import PortfolioExecutionResult

logger = logging.getLogger(__name__)


class NotificationService:
    """Completion-notification boundary; console logging is the assignment implementation."""

    def notify(self, result: PortfolioExecutionResult) -> None:
        successful_trades = [
            f"{item.action.value}:{item.side.value} {item.quantity} {item.symbol}"
            for item in result.results
            if item.status.value == "ACCEPTED"
        ]
        failed_trades = [
            f"{item.action.value}:{item.side.value} {item.quantity} {item.symbol} ({item.error_code})"
            for item in result.results
            if item.status.value != "ACCEPTED"
        ]
        logger.info(
            "portfolio_execution_complete execution_id=%s broker=%s status=%s successful_trades=%s failed_trades=%s",
            result.execution_id, result.broker.value, result.status,
            successful_trades, failed_trades,
        )
