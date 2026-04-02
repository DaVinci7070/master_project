import os

def get_host() -> str:
    return os.getenv("RAG_BIND_HOST", "0.0.0.0")

def get_port() -> int:
    return int(os.getenv("RAG_PORT", str(COMMON_RAG_PORT)))