# Minimal Python sandbox image for code execution
FROM python:3.11-alpine

# Security: Create non-root user
RUN adduser -D -u 1000 sandbox

# Install pytest for test execution
RUN pip install --no-cache-dir pytest==8.0.0

# Security: Set working directory
WORKDIR /sandbox

# Security: Switch to non-root user
USER sandbox

# Default command (overridden by epicbox)
CMD ["python3", "--version"]
