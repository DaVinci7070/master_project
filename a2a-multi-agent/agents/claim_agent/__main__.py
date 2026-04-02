
from __future__ import annotations

import uvicorn

from .app import create_app
from a2a_common.config import CLAIM_PORT, DEFAULT_HOST

if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=DEFAULT_HOST,
        port=CLAIM_PORT
    )
