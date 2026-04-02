import structlog
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import LumariError

log = structlog.get_logger()

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        loc = ".".join(str(l) for l in error.get("loc", []))
        msg = error.get("msg", "Invalid input")
        typ = error.get("type", "error")
        errors.append({
            "field": loc,
            "error": msg,
            "type": typ
        })

    log.warning("validation_error", errors=errors)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error_code": "validation_error",
            "detail": errors,
            "request_id": request.state.request_id
        },
    )

async def lumari_exception_handler(request: Request, exc: LumariError):
    log.error("domain_error", 
              error_code=exc.error_code, 
              message=exc.message, 
              details=exc.details,
              should_retry=exc.should_retry)

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.error_code,
            "detail": exc.message,
            "details": exc.details, 
            "request_id": getattr(request.state, "request_id", "unknown"),
            "retryable": exc.should_retry
        },
    )

from fastapi.encoders import jsonable_encoder

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder({
            "error_code": "http_error",
            "detail": exc.detail,
            "request_id": getattr(request.state, "request_id", "unknown")
        }),
    )

async def generic_exception_handler(request: Request, exc: Exception):
    log.exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": "internal_server_error",
            "detail": "An unexpected error occurred. Please contact support.",
            "request_id": getattr(request.state, "request_id", "unknown")
        },
    )
