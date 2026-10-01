from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.domain.models import ExecutePortfolioRequest, PortfolioExecutionResult
from app.repositories.executions import IdempotencyConflictError, IdempotencyInProgressError
from app.services.execution import ExecutionService

router = APIRouter(prefix="/api/v1")
compatibility_router = APIRouter(include_in_schema=False)


def get_service(request: Request) -> ExecutionService:
    return ExecutionService(
        registry=request.app.state.broker_registry,
        repository=request.app.state.execution_repository,
        notifier=request.app.state.notification_service,
        settings=request.app.state.settings,
    )


@router.get("/health")
@compatibility_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/brokers")
@compatibility_router.get("/brokers")
def brokers(request: Request) -> dict[str, object]:
    registry = request.app.state.broker_registry
    return {"brokers": registry.names(), "adapters": registry.describe()}


@router.post("/portfolios/execute", response_model=PortfolioExecutionResult)
@compatibility_router.post("/portfolios/execute", response_model=PortfolioExecutionResult)
def execute_portfolio(
    payload: ExecutePortfolioRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    service: ExecutionService = Depends(get_service),
) -> PortfolioExecutionResult:
    key = idempotency_key.strip()
    if not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key cannot be empty")
    try:
        return service.execute(payload, key)
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IdempotencyInProgressError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

