import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv()

from litellm import acompletion
import litellm

litellm.drop_params = True
litellm.set_verbose = False


@dataclass
class ModelCheckResult:
    model_id: str
    tier: str
    available: bool
    content: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    thinking_tokens: int | None = None
    latency_ms: int = 0
    error: str = ""
    raw_usage: dict = None

    def __post_init__(self):
        if self.raw_usage is None:
            self.raw_usage = {}


MODELS = [
    ("gemini/gemini-2.0-flash", "T-Weak"),
    ("gemini/gemini-2.5-flash", "T-Medium"),
    ("gemini/gemini-3.5-flash", "T-Strong"),
]

JUDGE_MODEL = "gemini/gemini-3.5-flash"

TEST_PROMPT = [
    {
        "role": "user",
        "content": (
            "Du bist ein Baustelleninspektor. Beschreibe in genau 2 Sätzen "
            "den Zustand einer fiktiven Baustelle. Antworte auf Deutsch."
        ),
    }
]

JUDGE_PROMPT = [
    {
        "role": "user",
        "content": (
            "Bewerte folgenden Text auf einer Skala von 0.0 bis 1.0 — "
            "wie gut beschreibt er eine Baustelle? "
            "Antworte NUR mit einer JSON-Struktur: {\"score\": 0.85, \"reason\": \"...\"}\n\n"
            "Text: 'Die Baustelle zeigt fortgeschrittene Rohbauarbeiten im dritten Stockwerk. "
            "Der Kran ist in Betrieb und Sicherheitsnetze sind korrekt angebracht.'"
        ),
    }
]


async def check_model(model_id: str, tier: str, messages: list[dict]) -> ModelCheckResult:
    """Testet ein einzelnes Modell."""
    result = ModelCheckResult(model_id=model_id, tier=tier, available=False)

    try:
        start = time.monotonic()
        response = await acompletion(
            model=model_id,
            messages=messages,
            temperature=0.7,
            max_tokens=256,
            timeout=30.0,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        usage = response.usage

        result.available = True
        result.content = choice.message.content or ""
        result.latency_ms = elapsed_ms

        usage_dict = dict(usage) if usage else {}
        result.raw_usage = usage_dict
        result.prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        result.completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        result.total_tokens = getattr(usage, "total_tokens", 0) or 0

        thinking = None
        if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
            details = usage.completion_tokens_details
            thinking = getattr(details, "reasoning_tokens", None)
            if thinking is None:
                thinking = getattr(details, "thinking_tokens", None)
        if thinking is None and isinstance(usage_dict, dict):
            details_dict = usage_dict.get("completion_tokens_details", {})
            if isinstance(details_dict, dict):
                thinking = details_dict.get("reasoning_tokens") or details_dict.get("thinking_tokens")
        result.thinking_tokens = thinking

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"

    return result


def print_result(r: ModelCheckResult) -> None:
    """Formatierte Ausgabe eines Check-Ergebnisses."""
    status = "✅ VERFÜGBAR" if r.available else "❌ NICHT ERREICHBAR"
    print(f"\n{'='*60}")
    print(f"  {r.tier} — {r.model_id}")
    print(f"  Status: {status}")

    if r.available:
        print(f"  Latenz: {r.latency_ms}ms")
        print(f"  Tokens: prompt={r.prompt_tokens}, completion={r.completion_tokens}, total={r.total_tokens}")

        if r.thinking_tokens is not None:
            print(f"  🧠 Thinking-Tokens: {r.thinking_tokens}")
        elif "2.5" in r.model_id:
            print(f"  ⚠️  Thinking-Tokens: NICHT EXTRAHIERBAR")
            print(f"      Raw usage keys: {list(r.raw_usage.keys()) if r.raw_usage else 'leer'}")

        preview = r.content[:120].replace("\n", " ")
        print(f"  Antwort: \"{preview}...\"" if len(r.content) > 120 else f"  Antwort: \"{preview}\"")
    else:
        print(f"  Fehler: {r.error}")

    print(f"{'='*60}")


async def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Sprint 0: Modell-Verfügbarkeitscheck                  ║")
    print("║  Ziel: Go/No-Go für Modellvergleich-Evaluation         ║")
    print("╚══════════════════════════════════════════════════════════╝")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\n❌ GEMINI_API_KEY nicht gesetzt! Abbruch.")
        sys.exit(1)
    print(f"\n🔑 API-Key: ...{api_key[-6:]}")

    print("\n── Phase 1: Zielmodelle testen ──")
    results = []
    for model_id, tier in MODELS:
        print(f"\n⏳ Teste {tier} ({model_id})...")
        r = await check_model(model_id, tier, TEST_PROMPT)
        results.append(r)
        print_result(r)

    print("\n── Phase 2: Judge-Modell testen ──")
    print(f"\n⏳ Teste Judge ({JUDGE_MODEL})...")
    judge_result = await check_model(JUDGE_MODEL, "Judge", JUDGE_PROMPT)
    print_result(judge_result)

    if judge_result.available:
        try:
            content = judge_result.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(content)
            print(f"  ✅ Judge-Output parsebar: score={parsed.get('score')}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  ⚠️  Judge-Output nicht als JSON parsebar: {e}")
            print(f"      Raw: {judge_result.content[:200]}")

    print("\n── Phase 3: Raw Usage Details ──")
    for r in results:
        if r.available:
            print(f"\n{r.tier} raw_usage:")
            for k, v in sorted(r.raw_usage.items()):
                if v and v != 0:
                    print(f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("  ZUSAMMENFASSUNG")
    print("=" * 60)

    all_available = all(r.available for r in results)
    judge_ok = judge_result.available

    for r in results:
        icon = "✅" if r.available else "❌"
        print(f"  {icon} {r.tier:10s} ({r.model_id}): {r.latency_ms}ms" if r.available
              else f"  {icon} {r.tier:10s} ({r.model_id}): {r.error[:50]}")

    icon_j = "✅" if judge_ok else "❌"
    print(f"  {icon_j} {'Judge':10s} ({JUDGE_MODEL})")

    medium = next((r for r in results if "2.5" in r.model_id), None)
    if medium and medium.available:
        if medium.thinking_tokens is not None:
            print(f"\n  🧠 Thinking-Tokens extrahierbar: JA ({medium.thinking_tokens} tokens)")
        else:
            print(f"\n  ⚠️  Thinking-Tokens extrahierbar: NEIN — Fallback nötig")

    print()
    if all_available and judge_ok:
        print("  🟢 GO — Alle Modelle erreichbar. Sprint 1 kann starten.")
    elif judge_ok and sum(r.available for r in results) >= 2:
        unavailable = [r for r in results if not r.available]
        print(f"  🟡 TEILWEISE — {unavailable[0].tier} nicht verfügbar.")
        print(f"     Plan anpassen oder alternatives Modell wählen.")
    else:
        print("  🔴 NO-GO — Kritische Modelle nicht erreichbar.")

    print()

    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "models": [
            {
                "model_id": r.model_id,
                "tier": r.tier,
                "available": r.available,
                "latency_ms": r.latency_ms,
                "tokens": {
                    "prompt": r.prompt_tokens,
                    "completion": r.completion_tokens,
                    "total": r.total_tokens,
                    "thinking": r.thinking_tokens,
                },
                "error": r.error or None,
            }
            for r in results
        ],
        "judge": {
            "model_id": JUDGE_MODEL,
            "available": judge_result.available,
            "latency_ms": judge_result.latency_ms,
        },
        "verdict": "GO" if (all_available and judge_ok) else "PARTIAL" if judge_ok else "NO-GO",
    }

    output_path = os.path.join(os.path.dirname(__file__), "..", "..", "results", "sprint0_check.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"  📄 Ergebnis gespeichert: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())