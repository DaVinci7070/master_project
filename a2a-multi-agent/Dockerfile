
FROM python:3.10-slim
 
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app:/app/a2a-multi-agent"
 
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates rsync \
    && rm -rf /var/lib/apt/lists/*
 
WORKDIR /app
 

COPY requirements.txt /app/requirements.txt
 
RUN python3 -m pip install --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt


# 2) Code kopieren (ohne große Modelle)
#   Entweder gezielt einzelne Ordner/Dateien:
#COPY agent_domain /app/agents/construction
#COPY agent_orchestrator /app/agents/orchestrator
#COPY agent_summarizer /app/agents/summarizer
#COPY report_templates /app/agents/report_templates
#COPY test_prompts /app/agents/test_prompts
#COPY factory/agent_template.py /app/agents/agent_template.py
#COPY factory/VLLMClient.py /app/agents/VLLMClient.py
#COPY agents_registry.yaml /app/agents/agents_registry.yaml
#COPY __init__.py /app/agents/__init__.py

COPY . /app/a2a-multi-agent

# 3) Nur das AWQ-Modell (Pfad relativ zu ./agents)
#COPY models/agents_models/llama-3.1-8b-instruct \
 #    /models/llama-3.1-8b-instruct

# 4) Entrypoint (liegt im Context als ./docker/entrypoint.sh)
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
