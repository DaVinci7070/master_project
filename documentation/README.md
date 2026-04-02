# Lumari Backend

KI-gestütztes Berichtserstellungssystem mit Multi-Agenten-Orchestrierung zur Umwandlung unstrukturierter Transkripte in strukturierte Berichte.

## Inhaltsverzeichnis

1. [Funktionsweise](#funktionsweise)
2. [Systemdesign & Methodik](#systemdesign--methodik)
3. [Technologie-Stack](#technologie-stack)
4. [Funktionen](#funktionen)
5. [Systemarchitektur](#systemarchitektur)
6. [Voraussetzungen](#voraussetzungen)
5. [API-Dokumentation](#api-dokumentation)
6. [Entwickler-Handbuch](#entwickler-handbuch)

## Funktionsweise

1. Benutzer reicht ein Transkript ein (z. B. Transkription einer Sprachaufzeichnung)
2. System wählt basierend auf dem Inhalt die passende Vorlage aus
3. KI-Agenten validieren die Vollständigkeit und stellen bei Bedarf Klärungsfragen
4. System ruft relevante historische Berichte für den Kontext ab (RAG)
5. KI generiert strukturierten Bericht gemäß Vorlage
6. Halluzinationserkennung stellt Genauigkeit sicher
7. Benutzer überprüft und finalisiert den Bericht

## Systemdesign & Methodik

Das System implementiert ein deterministisches, aber flexibles Multi-Agenten-Design, um die Herausforderungen unstrukturierter Baudaten zu bewältigen.

### Agenten-Interaktion
Statt eines monolithischen LLM-Ansatzes (der zu Halluzinationen und Kontextverlust neigt), zerlegt Lumari den Prozess in spezialisierte Agenten:
*   **Orchestrator**: Verwaltet den globalen Zustand und den Kontrollfluss (State Machine). Er verhindert "Context Rot" bei langen Transkripten, indem er nur relevante Informationen an Sub-Agenten weiterleitet.
*   **Spezialisierte Agenten** (Claim, Defect, Safety, Quality): Fokussieren sich ausschließlich auf ihre Domäne. Dies ermöglicht gezieltes Prompt-Engineering und einfachere Evaluierung.
*   **Guard Agent**: Fungiert als "Adversarial Critic", der generierte Fakten gegen das Quelltranskript prüft.

### Strukturierte Datengenerierung (Instructor)
Um die Brücke zwischen probabilistischen LLM-Ausgaben und deterministischen Systemen zu schlagen, verwendet Lumari die `instructor`-Bibliothek.
*   **Pydantic-Modelle**: Dienen als "Vertrag" zwischen Agenten.
*   **Validierung**: Erzwingt Typ-Sicherheit und logische Konsistenz (z.B. "Ein Mangel muss einen Schweregrad haben") direkt bei der Generierung.

### Modell-Abstraktion (vLLM Client)
Das System ist modell-agnostisch konzipiert durch eine eigene Abstraktionsschicht (`VLLM_Client`).
*   **Standardisierte Schnittstelle**: Kapselt provider-spezifische APIs (OpenAI, Google Gemini).
*   **Einheitliche Ausgaben**: Stellt sicher, dass alle Agenten, unabhängig vom darunterliegenden Modell, das gleiche Antwortformat liefern.

## Technologie-Stack

| Kategorie | Technologien |
|-----------|--------------|
| **Core Backend** | Python 3.10+, FastAPI, Pydantic |
| **KI & ML** | Gemini 2.0 Flash, Instructor (Structured Outputs), vLLM Adapter |
| **Datenbanken** | PostgreSQL (Metadaten), Qdrant (Vektorsuche/RAG) |
| **Infrastruktur** | Docker, Docker Compose, Supabase (Auth) |
| **Architektur** | Microservices-ready (A2A Protocol), Event-driven Design |

## Funktionen

- **Vorlagenbasierte Erstellung**: Automatische Vorlagenauswahl für konsistente Berichtsstruktur
- **Human-in-the-Loop (HITL)**: Interaktiver Workflow mit Klärungsfragen
- **Semantische Suche**: RAG-gestützter Kontextabruf aus historischen Berichten
- **Multi-Agenten-Orchestrierung**: Spezialisierte Agenten für verschiedene Aufgaben (Vorlage, Frage, RAG, Zusammenfassung, Wächter, Claim, Mangel, Sicherheit, Qualität)
- **Halluzinationserkennung**: KI-gestützte Faktenüberprüfung gegen das Quelltranskript
- **JWT-Authentifizierung**: Sichere Benutzerauthentifizierung über Supabase
- **Vektordatenbank-Integration**: Qdrant für semantische Suche und Ähnlichkeitsabgleich
- **Zustandspersistenz**: Wiederaufnahme von Workflows nach Benutzereingaben
- **RESTful API**: Sauberes API-Design mit umfassender Dokumentation

## Systemarchitektur

Lumari besteht aus mehreren miteinander verbundenen Komponenten:

### Kernkomponenten

- **Backend API (FastAPI)**: API-Gateway, Geschäftslogik und Datenzugriff
- **Agentensystem (A2A-Protokoll)**: Multi-Agenten-Orchestrierung für die Berichtserstellung
- **PostgreSQL**: Relationale Datenbank für Berichte und Vorlagen
- **Qdrant**: Vektordatenbank für semantische Suche
- **Supabase**: Authentifizierung und Benutzerverwaltung
- **Gemini 2.0 Flash**: Large Language Model für KI-Verarbeitung

### Architekturdiagramm

```
┌────▼─────────────────────────────────────┐
│          Agent System (A2A)              │
│  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ Template │  │ Question │  │  RAG   │  │
│  └──────────┘  └──────────┘  └────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │  Claim   │  │  Defect  │  │ Safety │  │
│  └──────────┘  └──────────┘  └────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ Quality  │  │Summarizer│  │  Guard │  │
│  └──────────┘  └──────────┘  └────────┘  │
│                   │                      │
                    ▼                      │
│           ┌──────────────┐               │
│           │ vLLM Adapter │               │
│           └──────┬───────┘               │
└──────────────┬───┼───────────────────────┘
               │   │
    ┌──────────┘   ▼
    ▼          ┌────────────┐
┌───────────┐  │ Gemini API │
│ PostgreSQL│  └────────────┘
└───────────┘
    │
    ▼
┌────────┐
│ Qdrant │
└────────┘
```

Für eine detaillierte Architekturdokumentation siehe [ARCHITECTURE.md](ARCHITECTURE.md).

## Voraussetzungen

### Erforderliche Software

- **Docker** 20.10+ und **Docker Compose** 2.0+
- **Python** 3.10 oder höher (für lokale Entwicklung)
- **PostgreSQL** 16+ (verwaltet über Docker oder extern)
- **Qdrant** aktuell (verwaltet über Docker oder Cloud)

### Erforderliche Konten

- **Supabase-Konto**: Für Authentifizierung (kostenloses Tier verfügbar)
  - Registrieren unter https://supabase.com
  - Projekt erstellen
  - Projekt-URL und Anon-Key notieren

- **Google Cloud-Konto**: Für Gemini API-Zugriff
  - Generative Language API aktivieren
  - API-Schlüssel erstellen
  - API-Schlüssel notieren


## API-Dokumentation

### Schnellstart-Beispiel

**1. Authentifizierungs-Token erhalten**

```bash
curl -X POST "https://your-project.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: your-anon-key" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "your-password"
  }'
```

**2. Bericht aus Transkript generieren**

```bash
curl -X POST "http://localhost:80/api/v1/transcripts/generate" \
  -H "Authorization: Bearer eyJhbGci..." \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "Baustellenbericht vom 14. Dezember 2025. Wetter: morgens bewölkt, mittags sonnig. Personal: 5 Mitarbeiter von Firma Müller Bau anwesend. Tätigkeiten: Betonarbeiten im Erdgeschoss fortgeführt."
  }'
```

**3. Bericht finalisieren**

```bash
curl -X POST "http://localhost:80/api/v1/reports/{report_id}/finalize" \
  -H "Authorization: Bearer eyJhbGci..." \
  -H "Content-Type: application/json" \
  -d '{
    "tags": ["Betonarbeiten", "Erdgeschoss"]
  }'
```

### Übersicht der API-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/api/v1/transcripts/generate` | POST | Bericht aus Transkript generieren |
| `/api/v1/transcripts/intake` | POST | Vereinfachte Transkript-Annahme |
| `/api/v1/templates` | POST | Neue Vorlage hochladen |
| `/api/v1/templates/user` | GET | Vorlagen des Benutzers auflisten |
| `/api/v1/templates/{id}` | GET | Vorlagendetails abrufen |
| `/api/v1/templates/{id}` | DELETE | Vorlage löschen |
| `/api/v1/reports/user` | GET | Berichte des Benutzers auflisten |
| `/api/v1/reports/{id}/finalize` | POST | Entwurfsbericht finalisieren |
| `/api/v1/reports/batch` | POST | Batch-Upload von Berichten |
| `/api/v1/reports/{id}` | DELETE | Bericht löschen |
| `/api/v1/assistant/check-questions` | POST | Auf Fragen prüfen |
| `/api/v1/assistant/ask` | POST | Frage zu Berichten stellen |
| `/api/v1/orchestration/resume` | POST | HITL-Workflow fortsetzen |

## Entwickler-Handbuch

### Codestruktur

#### Backend (`/backend/app/`)

```
app/
├── api/v1/endpoints/     - REST API Endpunkte
│   ├── transcripts.py    - Transkript-Übermittlung
│   ├── templates.py      - Vorlagen-Management
│   ├── reports.py        - Berichts-Operationen
│   ├── assistant.py      - KI-Assistent
│   └── orchestration.py  - Workflow-Management
├── services/             - Geschäftslogik
│   ├── report_service.py
│   ├── template_service.py
│   └── assistant_service.py
├── repositories/         - Datenzugriffsschicht
│   ├── postgres_repository.py
│   └── qdrant_repository.py
├── adapters/             - Adapter für externe Dienste
│   └── orchestrator_adapter.py
├── models/               - Datenmodelle
│   ├── api/             - Pydantic Request/Response-Modelle
│   ├── sql/             - SQLAlchemy ORM-Modelle
│   └── qdrant/          - Qdrant Punkt-Modelle
├── core/                 - Kern-Utilities
│   ├── config.py        - Konfiguration
│   ├── security.py      - Sicherheits-Utilities
│   ├── middleware.py    - Middleware
│   ├── logging.py       - Logging-Setup
│   └── exceptions.py    - Benutzerdefinierte Exceptions
└── dependencies/         - FastAPI-Abhängigkeiten
    └── auth.py          - Authentifizierung
```

#### Agentensystem (`/a2a-multi-agent/`)

```
a2a-multi-agent/
├── agents/               - Spezialisierte Agenten
│   ├── orchestrator_agent/   - Workflow-Koordinator
│   │   ├── executor.py      - Haupt-Orchestrierungslogik
│   │   ├── planning.py      - Workflow-Planung
│   │   ├── persistence.py   - Zustandsverwaltung
│   │   └── app.py           - FastAPI App
│   ├── template_agent/       - Vorlagenauswahl
│   ├── question_agent/       - Validierung & Fragen
│   ├── rag_agent/            - Kontextabruf
│   ├── summarizer_agent/     - Berichtserstellung
│   ├── guard_agent/          - Hallucinationserkennung
│   ├── claim_agent/          - Nachtragsanalyse
│   ├── defect_agent/         - Mängelanalyse
│   ├── safety_agent/         - Sicherheitsanalyse
│   └── quality_agent/        - Qualitätsanalyse
├── a2a_common/           - Geteiltes Framework
│   ├── schemas/         - Agent I/O Schemata
│   ├── signals.py       - Kontrollfluss-Signale
│   ├── envelope.py      - Nachrichten-Wrapping
│   └── remote_agent.py  - Agenten-Kommunikation
├── VLLM_Client/          - LLM-Integration
└── config/               - Agenten-Registry
```


### Neue Agenten hinzufügen

1. **Agenten-Verzeichnis erstellen**

```bash
mkdir a2a-multi-agent/my_agent
cd a2a-multi-agent/my_agent
touch __init__.py app.py executor.py models.py agent_card.py
```

2. **Input/Output Schemata definieren**

Erstellen in `/a2a-multi-agent/a2a_common/schemas/my_agent.py`:

```python
from pydantic import BaseModel

class MyAgentInput(BaseModel):
    input_data: str

class MyAgentOutput(BaseModel):
    output_data: str
```

3. **Executor implementieren**

In `executor.py`:

```python
from a2a_common.schemas.my_agent import MyAgentInput, MyAgentOutput
from a2a_common.signals import create_continue_signal

async def execute(inputs: MyAgentInput):
    output = MyAgentOutput(output_data=f"Processed: {inputs.input_data}")
    signal = create_continue_signal()
    return output, signal
```

4. **FastAPI App erstellen**

In `app.py`:

```python
from fastapi import FastAPI
from .executor import execute

app = FastAPI()

@app.post("/process")
async def process(inputs: dict):
    output, signal = await execute(MyAgentInput(**inputs))
    return {"output": output.dict(), "signal": signal.dict()}
```

5. **In Agenten-Registry registrieren**

Aktualisieren `/a2a-multi-agent/config/agent_registry.yaml`:

```yaml
agents:
  - name: my_agent
    url: http://localhost:8008
    port: 8008
```

6. **Docker Compose aktualisieren**

Hinzufügen zu `deploy/agents/docker-compose.yml`:

```yaml
lumari-my-agent:
  image: lumari-agents:latest
  environment:
    ROLE: agent_my_agent
  command: uvicorn my_agent.app:app --host 0.0.0.0 --port 8008
  ports:
    - "8008:8008"
```