import pytest
from fastapi.testclient import TestClient

from app.brokers.mock import MockBrokerAdapter
from app.brokers.registry import BrokerRegistry
from app.core.config import Settings
from app.main import create_app
from app.notifications.service import NotificationService
from app.repositories.executions import ExecutionRepository


class RecordingNotifier(NotificationService):
    def __init__(self) -> None:
        self.results = []

    def notify(self, result) -> None:
        self.results.append(result)


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def harness():
    adapter = MockBrokerAdapter()
    notifier = RecordingNotifier()
    app = create_app(
        settings=Settings(),
        broker_registry=BrokerRegistry({"mock": adapter}),
        execution_repository=ExecutionRepository(),
        notification_service=notifier,
    )
    with TestClient(app) as test_client:
        yield test_client, adapter, notifier

