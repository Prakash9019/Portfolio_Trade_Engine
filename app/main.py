import logging

from fastapi import FastAPI

from app.api.routes import compatibility_router, router
from app.brokers.registry import BrokerRegistry
from app.core.config import Settings, get_settings
from app.notifications.service import NotificationService
from app.repositories.executions import ExecutionRepository


def create_app(
    *,
    settings: Settings | None = None,
    broker_registry: BrokerRegistry | None = None,
    execution_repository: ExecutionRepository | None = None,
    notification_service: NotificationService | None = None,
) -> FastAPI:
    """Application factory makes production wiring and test doubles explicit."""

    resolved_settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, resolved_settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    application = FastAPI(title=resolved_settings.app_name, version="1.0.0")
    application.state.settings = resolved_settings
    mock_fail_symbols = {
        symbol.strip().upper()
        for symbol in resolved_settings.mock_fail_symbols.split(",")
        if symbol.strip()
    }
    application.state.broker_registry = broker_registry or BrokerRegistry(mock_fail_symbols=mock_fail_symbols)
    application.state.execution_repository = execution_repository or ExecutionRepository()
    application.state.notification_service = notification_service or NotificationService()
    application.include_router(router)
    application.include_router(compatibility_router)
    return application


app = create_app()
