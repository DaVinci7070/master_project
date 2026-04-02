from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AuthErrorResponse(BaseModel):
    error: str  
    error_code: str  
    expired_at: Optional[datetime] = None  

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "error": "Token has expired",
                    "error_code": "token_expired",
                    "expired_at": "2026-01-23T12:00:00Z"
                },
                {
                    "error": "Invalid token",
                    "error_code": "token_invalid"
                },
                {
                    "error": "Authorization header missing",
                    "error_code": "token_missing"
                }
            ]
        }
