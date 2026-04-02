import os

import uvicorn

from a2a_common.logging import setup_logging, get_logger
from a2a_common.config import SUMMARIZER_PORT
from .app import create_app

logger = get_logger(__name__)

if __name__ == "__main__":
    setup_logging()  

    port = int(os.getenv("SUMMARIZER_PORT", str(SUMMARIZER_PORT)))
    logger.info("Starte SUMMARIZER auf Port %s", port)

    uvicorn.run(create_app(), host="0.0.0.0", port=port)
