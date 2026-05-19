"""Lädt Agent-Definitionen aus YAML-Dateien in config/agents/."""
import yaml
from functools import lru_cache
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "agents"


def load_agent(name: str) -> dict:
    """Einzelne Agent-Definition laden."""
    path = AGENTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Agent-Definition nicht gefunden: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_all_agents() -> tuple[dict, ...]:
    """Alle Agent-Definitionen laden (gecacht)."""
    agents = []
    for path in sorted(AGENTS_DIR.glob("*.yaml")):
        with open(path) as f:
            agents.append(yaml.safe_load(f))
    return tuple(agents)


def load_agents_by_team(team: str) -> list[dict]:
    """Agents eines bestimmten Teams laden."""
    return [a for a in load_all_agents() if a.get("team") == team]


def get_agent_prompt(name: str) -> str:
    """Prompt eines Agents per Name laden."""
    return load_agent(name)["prompt"]
