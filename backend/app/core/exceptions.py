from typing import Optional, Dict, Any

class LumariError(Exception):
    def __init__(
        self, 
        message: str, 
        error_code: str = "LUM_ERROR",
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
        should_retry: bool = False
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        self.should_retry = should_retry

class AgentResponseError(LumariError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            error_code="AGENT_ERROR",
            status_code=502, 
            details=details,
            should_retry=True
        )

class TemplateNotFoundError(LumariError):
    def __init__(self, template_id: str):
        super().__init__(
            message=f"Template {template_id} not found.",
            error_code="TEMPLATE_NOT_FOUND",
            status_code=404,
            details={"template_id": template_id},
            should_retry=False
        )

class StorageError(LumariError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            error_code="STORAGE_ERROR",
            status_code=503,
            details=details,
            should_retry=True
        )

class OrchestrationError(LumariError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, should_retry: bool = False):
        super().__init__(
            message=message,
            error_code="ORCHESTRATION_ERROR",
            status_code=500,
            details=details,
            should_retry=should_retry
        )
