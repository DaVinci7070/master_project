# Lumari Agent System - Detaillierte Agent Beschreibungen

## Übersicht

Das Lumari System verwendet eine Multi-Agent-Architektur basierend auf dem A2A (Agent-to-Agent) Protokoll. Jeder Agent ist für eine spezifische Aufgabe im Report-Generierungsprozess verantwortlich.

## Agent-Pipeline

Die Agenten werden in folgender Reihenfolge aufgerufen:

```
1. Template Agent    → Wählt passendes Template
2. Question Agent    → Prüft Vollständigkeit, stellt Fragen
3. RAG Agent         → Holt relevanten Kontext
4. Summarizer Agent  → Generiert den Bericht
5. Guard Agent       → Prüft auf Halluzinationen
```

---

## 1. Orchestrator Agent

### Was macht er?

Der Orchestrator Agent ist der zentrale Koordinator des gesamten Workflows. Er orchestriert alle anderen Agenten und verwaltet den Zustand des Generierungsprozesses.

### Wie arbeitet er?

1. **Empfängt Anfrage** vom Backend (Transcript + Optional: Template ID, Antworten)
2. **Ruft spezialisierte Agenten auf** in der richtigen Reihenfolge
3. **Verarbeitet Signals** (CONTINUE, SUSPEND, ERROR) von jedem Agent
4. **Verwaltet den State** (speichert Zwischenergebnisse, Artefakte)
5. **Handhabt HITL** (Human-in-the-Loop) - pausiert bei Fragen, nimmt Antworten entgegen
6. **Aggregiert Ergebnisse** und gibt finalen Report zurück

### Technische Details

- **Port:** 8000
- **Endpunkte:**
  - `POST /process` - Startet neuen Workflow
  - `POST /resume` - Setzt HITL-Workflow fort
  - `GET /status/{run_id}` - Prüft Workflow-Status
- **State Management:** Persistiert Zustand in JSON-Dateien oder Redis
- **Protokoll:** JSON-RPC über HTTP

### Input

```json
{
  "transcript": "Baustellenbericht vom...",
  "template_id": "uuid (optional)",
  "run_id": "uuid (optional, für Resume)",
  "answers": {} (optional, für HITL)
}
```

### Output

**Bei Erfolg:**
```json
{
  "status": "completed",
  "report_content": "# Baustellenbericht\n...",
  "metadata": {
    "template_id": "uuid",
    "tags": ["..."]
  }
}
```

**Bei HITL (Fragen benötigt):**
```json
{
  "status": "waiting_for_user",
  "questions": [...],
  "run_id": "uuid"
}
```

### Beispiel-Workflow

```python
# 1. Orchestrator erhält Anfrage
request = {
    "transcript": "Baustellenbericht..."
}

# 2. Ruft Template Agent
template_result = await invoke_agent("template", request)

# 3. Ruft Question Agent
question_result, signal = await invoke_agent("question", {
    "transcript": request["transcript"],
    "template": template_result
})

# 4. Wenn Signal == SUSPEND:
if signal.type == "SUSPEND":
    # Speichere State
    save_state(run_id, artifacts)
    # Gebe Fragen zurück
    return {"status": "waiting_for_user", "questions": [...]}

# 5. Sonst: Weiter mit RAG...
```

---

## 2. Template Agent

### Was macht er?

Der Template Agent wählt das passende Berichts-Template basierend auf dem Inhalt des Transcripts aus.

### Wie arbeitet er?

1. **Sucht ähnliche Templates** in Qdrant via MCP Server (Semantic Search)
2. **Analysiert Transcript** mit LLM (Gemini 2.0 Flash)
3. **Wählt bestes Template** basierend auf Inhalt und Kontext
4. **Extrahiert Template-Schema** für nachfolgende Agenten

### Technische Details

- **Port:** 8006
- **LLM:** Gemini 2.0 Flash
- **Qdrant Integration:** Via MCP Server
- **Temperatur:** 0.1 (deterministisch)

### Input

```json
{
  "transcript": "Baustellenbericht vom 14. Dezember..."
}
```

### Output

```json
{
  "template_result": {
    "template_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "Baustellenbericht Standard",
    "schema": {
      "fields": [
        {
          "name": "date",
          "type": "date",
          "required": true
        },
        {
          "name": "weather",
          "type": "object",
          "fields": [
            {"name": "morning", "type": "string"},
            {"name": "afternoon", "type": "string"}
          ]
        },
        {
          "name": "personnel",
          "type": "array",
          "required": true
        },
        {
          "name": "activities",
          "type": "array",
          "required": true
        }
      ]
    }
  },
  "signal": "CONTINUE"
}
```

### Entscheidungsprozess

**Prompt an LLM:**
```
Analysiere das folgende Transcript und wähle das passende Template:

Transcript: "{transcript}"

Verfügbare Templates:
1. Baustellenbericht Standard - Für tägliche Baustellendokumentation
2. Sicherheitsbericht - Für Sicherheitsvorfälle
3. Qualitätsbericht - Für Qualitätsprüfungen

Welches Template passt am besten? Begründe deine Wahl.
```

**LLM Antwort:**
```
Template: Baustellenbericht Standard
Begründung: Das Transcript enthält typische Elemente eines Baustellenberichts:
- Datum (14. Dezember)
- Wetterbedingungen
- Personalangaben
- Tätigkeitsbeschreibung
```

### Signal

- Immer: **CONTINUE** (niemals SUSPEND oder ERROR)
- Template-Auswahl blockiert nicht, auch wenn kein perfektes Match

---

## 3. Question Agent (QA)

### Was macht er?

Der Question Agent validiert, ob das Transcript alle notwendigen Informationen für einen vollständigen Bericht enthält. Wenn Informationen fehlen, generiert er spezifische Rückfragen an den User.

### Wie arbeitet er?

1. **Vergleicht Transcript gegen Template** - prüft Required Fields
2. **Identifiziert fehlende Informationen** mit LLM
3. **Generiert spezifische Fragen** für jedes fehlende Feld
4. **Entscheidet:** CONTINUE (komplett) oder SUSPEND (Fragen nötig)

### Technische Details

- **Port:** 8007
- **LLM:** Gemini 2.0 Flash
- **Temperatur:** 0.1
- **HITL-Trigger:** Dieser Agent ist der einzige, der SUSPEND zurückgeben kann

### Input

```json
{
  "transcript": "Baustellenbericht vom 14. Dezember...",
  "template_result": {
    "schema": {...}
  }
}
```

### Output (Vollständig)

```json
{
  "question_result": {
    "has_questions": false
  },
  "signal": "CONTINUE"
}
```

### Output (Unvollständig - HITL)

```json
{
  "question_result": {
    "has_questions": true,
    "questions": [
      {
        "id": "q1",
        "question": "Wie war die genaue Temperatur am Morgen?",
        "field_name": "weather.morning.temperature",
        "kind": "text",
        "required": true
      },
      {
        "id": "q2",
        "question": "Welche Betongüte wurde verwendet?",
        "field_name": "concrete_grade",
        "kind": "text",
        "required": true
      },
      {
        "id": "q3",
        "question": "Wie viele Kubikmeter Beton wurden verarbeitet?",
        "field_name": "concrete_volume",
        "kind": "number",
        "required": false
      }
    ]
  },
  "signal": "SUSPEND"
}
```

### LLM Prompt

```
Du bist ein hyper-kritischer Qualitätsmanager für professionelle Baustellenberichte.
Deine Aufgabe ist es, ein Transkript gegen ein Bericht-Template zu prüfen.

TRANSKRIPT:
{transcript}

TEMPLATE:
{template_json}

AUFGABE:
1. Prüfe das Transkript basierend auf dem TEMPLATE.
2. WICHTIG: Du musst IMMER mindestens 3 detaillierte Rückfragen stellen.
3. Suche gezielt nach fehlenden Details:
   - WETTER (morgens/mittags)
   - PERSONAL (Namen/Firmen)
   - GERÄTE (Typ, Anzahl)
   - TÄTIGKEITEN (ortsgenau, Mengenangaben)

Antworte AUSSCHLIESSLICH als JSON:
{
  "has_questions": true,
  "questions": [...]
}
```

### Signal

- **CONTINUE:** Transcript ist vollständig
- **SUSPEND:** Fragen benötigt → HITL-Workflow wird gestartet

### HITL-Workflow

1. **Question Agent gibt SUSPEND zurück**
2. **Orchestrator speichert State** (run_id, Artefakte)
3. **Backend gibt Fragen an User zurück**
4. **User beantwortet Fragen**
5. **Backend sendet Antworten an Orchestrator** (`POST /resume`)
6. **Orchestrator lädt State** und mergt Antworten ins Transcript
7. **Question Agent wird erneut aufgerufen** mit angereichertem Transcript
8. **Gibt CONTINUE zurück** (hoffentlich)

---

## 4. RAG Agent

### Was macht er?

Der RAG (Retrieval-Augmented Generation) Agent holt relevante historische Berichte aus der Qdrant Vector Database, um Kontext für die Berichtsgenerierung zu liefern.

### Wie arbeitet er?

1. **Generiert Embeddings** für das aktuelle Transcript
2. **Sucht ähnliche Berichte** in Qdrant via MCP Server
3. **Ranked Retrieval** - Top K ähnlichste Berichte
4. **Filtert nach Relevanz** (Similarity Threshold)
5. **Gibt Kontext zurück** an Orchestrator

### Technische Details

- **Port:** 8004
- **MCP Server:** Port 9000
- **Top K:** 5 (konfigurierbar)
- **Similarity Threshold:** 0.7 (Cosine Similarity)
- **Embedding Model:** Via MCP Server

### Input

```json
{
  "transcript": "Baustellenbericht vom 14. Dezember...",
  "template_result": {...}
}
```

### Output

```json
{
  "rag_context": [
    {
      "report_id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "Baustellenbericht - 12.12.2025",
      "content": "Wetter: bewölkt, Personal: ...",
      "similarity": 0.89,
      "tags": ["Betonarbeiten", "Erdgeschoss"]
    },
    {
      "report_id": "660e8400-e29b-41d4-a716-446655440001",
      "title": "Baustellenbericht - 10.12.2025",
      "content": "Betonarbeiten fortgeführt...",
      "similarity": 0.82,
      "tags": ["Betonarbeiten"]
    }
  ],
  "signal": "CONTINUE"
}
```

### Retrieval-Prozess

```python
# 1. Generate embeddings für Transcript
embedding = await mcp_client.generate_embedding(transcript)

# 2. Similarity Search in Qdrant
results = await qdrant_client.search(
    collection_name="reports",
    query_vector=embedding,
    limit=5,
    score_threshold=0.7,
    query_filter={
        "user_id": current_user_id  # Nur eigene Berichte
    }
)

# 3. Extract relevante Informationen
rag_context = [
    {
        "title": result.payload["title"],
        "content": result.payload["content"],
        "similarity": result.score,
        "tags": result.payload["tags"]
    }
    for result in results
]
```

### Warum RAG?

**Ohne RAG:**
```
LLM generiert Bericht nur basierend auf aktuellem Transcript
→ Keine Konsistenz mit früheren Berichten
→ Keine Wiederverwendung von Formulierungen
→ Keine Berücksichtigung von Projekt-Historie
```

**Mit RAG:**
```
LLM hat Zugriff auf ähnliche frühere Berichte
→ Konsistente Terminologie
→ Wiederverwendung bewährter Formulierungen
→ Kontext über Projekt-Verlauf
→ Bessere Qualität
```

### Signal

- Immer: **CONTINUE** (auch wenn keine Ergebnisse gefunden)
- Leerer Kontext ist OK → Summarizer arbeitet trotzdem

---

## 5. Summarizer Agent

### Was macht er?

Der Summarizer Agent ist der Kern der Berichtsgenerierung. Er nimmt alle gesammelten Informationen (Transcript, Template, RAG-Kontext, User-Antworten) und generiert daraus einen strukturierten Bericht.

### Wie arbeitet er?

1. **Aggregiert alle Inputs:**
   - Original Transcript
   - Template Schema
   - RAG Kontext (ähnliche Berichte)
   - User Antworten (falls HITL)
2. **Konstruiert umfassenden Prompt** für LLM
3. **Generiert strukturierten Bericht** basierend auf Template
4. **Formatiert Output** (Markdown, Text, oder JSON)

### Technische Details

- **Port:** 8001
- **LLM:** Gemini 2.0 Flash
- **Temperatur:** 0.3 (etwas kreativer als Template/Question)
- **Max Tokens:** 4096
- **Structured Output:** Via Instructor (Pydantic Models)

### Input

```json
{
  "transcript": "Baustellenbericht vom 14. Dezember...",
  "template_result": {...},
  "rag_context": [...],
  "answers": {
    "q1": "15 Grad Celsius",
    "q2": "C25/30"
  }
}
```

### Output

```json
{
  "report_content": "# Baustellenbericht - 14.12.2025\n\n## Datum\n14. Dezember 2025\n\n## Wetter\n- Morgens: bewölkt, 15°C\n- Mittags: sonnig\n\n## Personal\n- 5 Mitarbeiter\n- Firma: Müller Bau GmbH\n\n## Tätigkeiten\n- Betonarbeiten im Erdgeschoss fortgeführt\n- Betongüte: C25/30\n- Schalung gestellt\n\n## Geräte\n- Betonmischer\n- Rüttler\n\n## Besondere Vorkommnisse\nKeine",
  "metadata": {
    "title": "Baustellenbericht - 14.12.2025",
    "tags": ["Betonarbeiten", "Erdgeschoss"],
    "format": "markdown"
  },
  "signal": "CONTINUE"
}
```

### LLM Prompt (Vereinfacht)

```
Du bist ein professioneller Baustellendokumentations-Experte.
Erstelle einen strukturierten Baustellenbericht basierend auf folgenden Informationen:

ORIGINAL TRANSCRIPT:
{transcript}

USER ANTWORTEN (falls vorhanden):
{answers}

TEMPLATE SCHEMA:
{template_schema}

ÄHNLICHE FRÜHERE BERICHTE (für Kontext und Stil):
{rag_context}

AUFGABE:
1. Erstelle einen vollständigen, professionellen Bericht
2. Folge genau der Template-Struktur
3. Integriere alle Informationen aus Transcript und Antworten
4. Nutze den Stil und die Terminologie aus den früheren Berichten
5. Sei präzise und faktenbasiert
6. WICHTIG: Erfinde KEINE Informationen! Nutze nur das, was gegeben ist.

Formatiere als Markdown mit klaren Überschriften und Bullet Points.
```

### Signal

- Immer: **CONTINUE**
- Selbst wenn Generation fehlschlägt, gibt der Agent ein Fehler-Signal zurück (nicht SUSPEND)

---

## 6. Guard Agent

### Was macht er?

Der Guard Agent ist die letzte Sicherheitsschicht. Er prüft den generierten Bericht auf Halluzinationen - d.h. Informationen, die der LLM erfunden hat und nicht im Original-Transcript stehen.

### Wie arbeitet er?

1. **Vergleicht generierten Bericht** gegen Original-Transcript
2. **Identifiziert Claims** (Aussagen/Fakten) im Bericht
3. **Verifiziert jeden Claim** gegen die Quelle
4. **Erkennt Halluzinationen:**
   - Erfundene Zahlen
   - Nicht erwähnte Personen/Firmen
   - Zusätzliche Details ohne Quellenbeleg
5. **Entscheidet:** CONTINUE (OK) oder ERROR (Halluzination gefunden)

### Technische Details

- **Port:** 8005
- **LLM:** Gemini 2.0 Flash
- **Temperatur:** 0.0 (maximal deterministisch)
- **Retry-Mechanismus:** Bei ERROR wird Summarizer neu aufgerufen

### Input

```json
{
  "report_content": "# Baustellenbericht...",
  "original_transcript": "Baustellenbericht vom 14. Dezember...",
  "answers": {...}
}
```

### Output (Keine Halluzination)

```json
{
  "validation_result": {
    "is_valid": true,
    "hallucinations": []
  },
  "signal": "CONTINUE"
}
```

### Output (Halluzination gefunden)

```json
{
  "validation_result": {
    "is_valid": false,
    "hallucinations": [
      {
        "claim": "10 Kubikmeter Beton wurden verarbeitet",
        "reason": "Mengenangabe nicht im Original-Transcript erwähnt",
        "severity": "high"
      },
      {
        "claim": "Temperaturen erreichten 22 Grad",
        "reason": "Keine Temperaturangabe im Transcript",
        "severity": "medium"
      }
    ]
  },
  "signal": "ERROR"
}
```

### LLM Prompt

```
Du bist ein Fakten-Checker. Prüfe den generierten Bericht auf Halluzinationen.

ORIGINAL TRANSCRIPT:
{transcript}

USER ANTWORTEN:
{answers}

GENERIERTER BERICHT:
{report_content}

AUFGABE:
1. Extrahiere alle faktischen Claims aus dem Bericht
2. Prüfe jeden Claim gegen das Original-Transcript und User-Antworten
3. Markiere Claims, die NICHT in den Quellen belegt sind
4. Kategorisiere Halluzinationen nach Schwere:
   - high: Erfundene Zahlen, Personen, Ereignisse
   - medium: Zusätzliche Details, Interpretationen
   - low: Stilistische Ausschmückungen

Antworte als JSON:
{
  "is_valid": boolean,
  "hallucinations": [...]
}
```

### Error-Handling

**Wenn Halluzination erkannt:**

```python
# 1. Guard gibt ERROR zurück
guard_result, signal = await guard_agent.execute(...)

if signal.type == "ERROR":
    # 2. Orchestrator loggt Fehler
    logger.warning(f"Hallucination detected: {guard_result.hallucinations}")

    # 3. Re-invoke Summarizer mit strengerem Prompt
    summarizer_result = await summarizer_agent.execute(
        ...,
        additional_instruction="SEHR WICHTIG: Erfinde KEINE Informationen! "
                              "Nutze NUR Fakten aus dem Transcript."
    )

    # 4. Re-check mit Guard
    guard_result, signal = await guard_agent.execute(...)

    # 5. Nach 3 Versuchen: Fehler an User
    if attempts >= 3:
        return {"error": "Report generation failed quality check"}
```

### Signal

- **CONTINUE:** Bericht ist valide
- **ERROR:** Halluzination gefunden → Trigger Re-generation

---

## Agent-Kommunikation: A2A Protokoll

### Signal Types

Jeder Agent gibt ein **Signal** zurück, das dem Orchestrator sagt, wie es weitergeht:

```python
class SignalType(Enum):
    CONTINUE = "continue"    # Alles OK, weiter zum nächsten Agent
    SUSPEND = "suspend"      # Pause (z.B. für User-Input)
    ERROR = "error"          # Fehler, Re-try oder Abbruch
```

### Envelope Format

Agenten kommunizieren via JSON-RPC über HTTP mit standardisierten Envelopes:

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "execute",
  "params": {
    "input": {...}
  },
  "id": "request-uuid"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "output": {...},
    "signal": {
      "type": "continue",
      "data": {},
      "reason": null
    }
  },
  "id": "request-uuid"
}
```

### Retry-Logik

Jeder Agent-Aufruf hat automatische Retry-Logik:

```python
@retry(
    max_attempts=3,
    backoff_base=1.0,  # Exponential backoff: 1s, 2s, 4s
    on_exceptions=[HTTPError, TimeoutError]
)
async def invoke_agent(agent_name: str, inputs: dict):
    response = await http_client.post(
        f"{agent_url}/process",
        json={"input": inputs},
        timeout=30.0
    )
    return response.json()
```

---

## Performance & Skalierung

### Latenzübersicht

| Agent | Durchschnittliche Latenz | Hauptaufwand |
|-------|-------------------------|--------------|
| Orchestrator | 50-100ms | State Management |
| Template | 1-2s | Qdrant Search + LLM |
| Question | 2-3s | LLM Inference |
| RAG | 200-500ms | Qdrant Search |
| Summarizer | 3-5s | LLM Inference (longest) |
| Guard | 2-3s | LLM Inference |
| **Gesamt** | **8-14s** | (ohne HITL) |

### Optimierungsmöglichkeiten

**1. Parallele Ausführung:**
```python
# Template und RAG könnten parallel laufen
template_task = asyncio.create_task(invoke_template_agent(...))
rag_task = asyncio.create_task(invoke_rag_agent(...))

template_result, rag_context = await asyncio.gather(template_task, rag_task)
```

**2. Caching:**
```python
# Template-Lookups cachen
@cache(ttl=3600)
async def get_template(template_id: str):
    return await template_agent.execute(...)
```

**3. Streaming:**
```python
# Summarizer könnte Report streamen
async for chunk in summarizer_agent.stream_generate(...):
    yield chunk
```

### Skalierung

**Horizontal Scaling:**
- Jeder spezialisierte Agent kann unabhängig skaliert werden
- Load Balancer vor Agenten
- Orchestrator bleibt Single-Instance (State Management)

**Beispiel Docker Compose:**
```yaml
lumari-summarizer:
  image: lumari-agents:latest
  command: summarizer
  deploy:
    replicas: 3  # 3 Summarizer-Instanzen
```

---

## Monitoring & Debugging

### Logging

Jeder Agent loggt strukturiert:

```json
{
  "timestamp": "2025-12-14T10:30:15Z",
  "level": "INFO",
  "agent": "summarizer_agent",
  "message": "Report generation started",
  "context": {
    "run_id": "660e8400-...",
    "user_id": "user-123",
    "transcript_length": 1234
  }
}
```

### Tracing

Mit Correlation IDs durchs System:

```
Request ID: req-abc123

[Backend API] req-abc123: Received /transcripts/generate
[Orchestrator] req-abc123: Starting workflow, run_id=run-xyz789
[Template Agent] req-abc123, run-xyz789: Template selection started
[Template Agent] req-abc123, run-xyz789: Selected template: Baustellenbericht
[Question Agent] req-abc123, run-xyz789: Validation started
...
```

### Health Checks

Jeder Agent hat `/health` Endpoint:

```bash
curl http://localhost:8001/health
```

```json
{
  "status": "healthy",
  "agent": "summarizer_agent",
  "version": "1.0.0",
  "llm_connection": "ok",
  "uptime_seconds": 3600
}
```

---

## Zusammenfassung

### Agent-Übersicht

| Agent | Aufgabe | Kann blocken? | LLM-Nutzung |
|-------|---------|---------------|-------------|
| **Orchestrator** | Koordination | Nein | Nein |
| **Template** | Template-Auswahl | Nein | Ja (Auswahl) |
| **Question** | Validierung | **Ja (HITL)** | Ja (Fragen generieren) |
| **RAG** | Kontext-Retrieval | Nein | Nein (nur Embeddings) |
| **Summarizer** | Report-Generierung | Nein | Ja (Generation) |
| **Guard** | Halluzinations-Check | Nein (aber Retry) | Ja (Validierung) |

### Datenfluss

```
User Input (Transcript)
    ↓
Orchestrator empfängt
    ↓
Template Agent → Template Schema
    ↓
Question Agent → Fragen oder OK
    ↓ (wenn OK)
RAG Agent → Historischer Kontext
    ↓
Summarizer Agent → Generierter Bericht
    ↓
Guard Agent → Validierung
    ↓ (wenn valide)
Orchestrator → Zurück an Backend
    ↓
User erhält Bericht
```

### Best Practices

1. **Jeder Agent ist zustandslos** - State liegt beim Orchestrator
2. **Idempotente Operationen** - Retry-safe
3. **Fail-Fast** - Bei Fehlern schnell abbrechen
4. **Strukturierte Outputs** - Pydantic Models für Validierung
5. **Monitoring** - Jeder Agent loggt strukturiert
6. **Timeouts** - Jeder Agent-Call hat Timeout (30s default)