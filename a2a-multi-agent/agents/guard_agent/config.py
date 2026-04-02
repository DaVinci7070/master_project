import os

def get_host() -> str:
    return os.getenv("GUARD_BIND_HOST", "0.0.0.0")

def get_port() -> int:
    return int(os.getenv("GUARD_PORT", str(COMMON_GUARD_PORT)))