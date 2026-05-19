# Masterarbeit: Selbstverbesserndes Multi-Agenten-System — V2

## Titel
**Enabling Secure Structural Self-Evolution in Multi-Agent Systems via Retrieval-Augmented Blueprint Generation**

---

## 1. Vision & Kernidee

Diese Arbeit entwickelt ein **strukturell selbst-evolvierendes Multi-Agenten-System (Lumari)**. Anders als existierende Ansaetze (z.B. AgentOrchestra, Voyager), die nur neue Werkzeuge generieren, kann dieses System:

- **Neue Skills autonom entwickeln** durch ein 5-Rollen-Entwicklerteam
- **Team-Strukturen dynamisch assemblieren** per LLM-basiertem Planner
- **Aus vergangenen Ausfuehrungen lernen** durch Shared Memory (Hybrid RAG) und Strategy Memory
- **Sich selbst sicher verbessern** durch Sandbox-Testing, Semantische Validierung und A/B-Tests
- **Ergebnisse iterativ verfeinern** durch ein 3-stufiges Verify-Adapt-Eskalationsmodell

**Kernunterschied zu statischen MAS:** Das System erkennt, wenn seine aktuelle Konfiguration eine Aufgabe nicht loesen kann, und baut eigenstaendig die benoetigten Faehigkeiten — sei es neue Skills, verbesserte Prompts oder komplett neue Agenten. Provisorische Agenten werden nach Erfolg automatisch befoerdert.

---

## 2. Architektur: Fuenf-Phasen-Pipeline

Der zentrale Algorithmus verarbeitet Aufgaben in fuenf Phasen:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        STRUKTURELLE SELBST-EVOLUTION                         │
└─────────────────────────────────────────────────────────────────────────────┘

    Challenge ──► PHASE 1         PHASE 2           PHASE 3
    (Eingabe)     Pre-Execution   Gap Building      Team-Ausfuehrung
                  Analyse         (wenn noetig)     (Wave-basiert)
                       │               │                  │
                       ▼               ▼                  ▼
                  ┌──────────┐   ┌──────────┐      ┌──────────┐
                  │Challenge │   │Interventi│      │Hybrid    │
                  │Analyzer  │   │on-Orch.  │      │Orchestr. │
                  │Feasibil. │   │CapBuilder│      │TeamAssem.│
                  │Judge     │   │SkillTeam │      │GenericEx.│
                  └────┬─────┘   └────┬─────┘      └────┬─────┘
                       │               │                  │
                       ▼               ▼                  ▼
                  PHASE 4         PHASE 5
                  Verify-Adapt    Post-Execution
                  Loop            & Evolution
                       │               │
                       ▼               ▼
                  ┌──────────┐   ┌──────────┐
                  │Execution │   │Strategy  │
                  │Verifier  │   │Memory    │
                  │Adapt-    │   │Agent-    │
                  │Strategy  │   │Promotion │
                  └──────────┘   │Evo-Loop  │
                                 └──────────┘
```

### 2.1 Phase 1: Pre-Execution Analyse

Drei Komponenten analysieren die eingehende Aufgabe:

| Komponente | Aufgabe |
|------------|---------|
| **ChallengeAnalyzer** | Extrahiert benoetigte Capabilities (KNOWLEDGE vs. EXECUTION), matcht gegen aktuelle Topologie via Embeddings |
| **CapabilityMatcher** | Semantische Aehnlichkeitssuche zwischen benoetigten und vorhandenen Faehigkeiten |
| **FeasibilityJudge** | Prueft fuer EXECUTION-Capabilities, ob echte Tools/Skills vorhanden sind |

**Routing-Entscheidung:**
- `CAN_DO` → direkt zu Phase 3 (Team-Ausfuehrung)
- `MAYBE` / `CANNOT_DO` → Phase 2 (Gap Building)

### 2.2 Phase 2: Gap Building (Intervention)

Wenn Faehigkeiten fehlen, baut das System sie autonom:

```
InterventionOrchestrator
├── Gap-Plan erstellen (fixe Liste, sortiert nach Severity)
├── GapPlanExecutor (sequenziell, max 3 Zyklen)
│   ├── MISSING_SKILL  → SkillTeamOrchestrator (5-Rollen-Pipeline)
│   ├── WEAK_PROMPT    → PromptEngineer
│   ├── MISSING_AGENT  → DeveloperTeamOrchestrator
│   └── SCHEMA_MISMATCH → Skill oder Agent
├── CapabilityInjector → Topologie aktualisieren
└── Verify, nicht Re-Analyze → Closure pruefen
```

**Design-Entscheidung:** Gap-Plans sind bei Erstellung fixiert (keine Re-Analyse waehrend des Builds), um endlose Discovery-Zyklen zu vermeiden.

### 2.3 Phase 3: Team-Ausfuehrung

```
┌──────────────────────────────────────────────────────────────────────┐
│                      TEAM-AUSFUEHRUNG                                │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. TeamAssembler                                                    │
│     ├── SharedMemory: vergangene Strategien laden (StrategyMemory)   │
│     ├── LLM plant Team aus verfuegbarem Agenten-Pool                 │
│     ├── DAG-Validierung + Artifact-Dataflow-Pruefung                 │
│     └── Ergebnis: TeamPlan mit Waves ODER GapReport                  │
│                                                                      │
│  2. TopologyLoader                                                   │
│     ├── Agenten + Skills + Prompts laden (Cache bis Reload)          │
│     ├── Topologische Sortierung → Execution-Waves                    │
│     └── Zyklen-Erkennung (DAG-Pruefung)                              │
│                                                                      │
│  3. Wave-Execution (parallel innerhalb Waves)                        │
│     └── GenericAgentExecutor pro Agent:                               │
│         ├── Kontext: ArtifactPool + SharedMemory + Input             │
│         ├── Prompt-Konstruktion (Template-Variablen)                  │
│         ├── Tool-Calling Loop (max 15 Aufrufe)                       │
│         │   ├── LLM → Structured Output (AgentResponse)              │
│         │   ├── ToolCallDetector (Skill-Erkennung)                   │
│         │   ├── Argument-Validierung + Auto-Fixing                   │
│         │   └── Sandbox-Ausfuehrung (Docker)                         │
│         ├── Self-Healing bei Fehler (Reparatur → Retry)              │
│         └── Artifacts + Facts schreiben                               │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

**Agenten kommunizieren nicht direkt miteinander.** Stattdessen:
- **ArtifactPool** (intra-execution): Typisierte Zwischenergebnisse zwischen Agenten innerhalb einer Session
- **SharedMemory** (cross-execution): Persistierte Facts mit Embeddings fuer Cross-Run-Lernen

### 2.4 Phase 4: Verify-Adapt Loop

Nach der Ausfuehrung wird das Ergebnis bewertet und bei Bedarf iterativ verbessert:

```
                         ExecutionVerifier
                         (Pattern-Matching + LLM-Evaluation)
                                │
                          Score berechnet
                                │
                 ┌──────────────┼──────────────┬──────────────┐
                 ▼              ▼              ▼              ▼
           Score >= 0.85   0.4 - 0.85    0.1 - 0.4      < 0.1
                │              │              │              │
                ▼              ▼              ▼              ▼
             PASS      REPLAN_FEEDBACK  REPLAN_NEW    ESCALATE
                       Gleiche Agenten  TEAM          → Phase 2
                       + Feedback       Neues Team    Gap Building
                       injizieren       assemblieren  starten
```

**Auto-Eskalation:** Nach 2 gescheiterten REPLAN_FEEDBACK-Versuchen → automatisch REPLAN_NEW_TEAM.

### 2.5 Phase 5: Post-Execution & Evolution

Nach erfolgreicher Ausfuehrung:

| Mechanismus | Beschreibung |
|-------------|-------------|
| **StrategyMemory** | Speichert Outcome (Team, Score, Strategie, Dauer, Tokens) als SharedMemory-Fact — Erfolge UND Misserfolge |
| **AgentPromotion** | Provisorische Agenten mit Score >= 0.7 werden permanent befoerdert |
| **Evolution Loop** | Fire-and-Forget Background-Task: AnalysisPipeline → ProductOwner → ControlAgent → ImprovementOrchestrator → A/B-Test |

---

## 3. Zwei-Team-Architektur

### 3.1 Main Team (Report-Generierung)

```
Wave 1              Wave 2               Wave 3              Wave 4              Wave 5
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ transcript   │──►│ context      │──►│ report       │──►│ quality      │──►│ report       │
│ _analyzer    │   │ _retriever   │   │ _generator   │   │ _validator   │   │ _finalizer   │
│              │   │              │   │              │   │              │   │              │
│ Transkript   │   │ Historischen │   │ Bericht      │   │ Vollstaendig-│   │ Korrekturen  │
│ analysieren  │   │ Kontext aus  │   │ synthetisie- │   │ keit +       │   │ anwenden,    │
│ Sprecher,    │   │ SharedMemory │   │ ren aus      │   │ Richtigkeit  │   │ Endversion   │
│ Themen,      │   │ holen        │   │ Analyse +    │   │ pruefen      │   │ erstellen    │
│ Fakten       │   │              │   │ Kontext      │   │              │   │              │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
```

**Dynamische Team-Assembly:** Der TeamAssembler kann je nach Aufgabe andere oder zusaetzliche Agenten einplanen. Die obige Pipeline ist die Default-Topologie, nicht die einzige.

### 3.2 Developer Team (Selbst-Verbesserung)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     EVOLUTION TEAM                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌────────────────┐    ┌────────────────┐    ┌────────────────┐            │
│  │ Analyzer Agent │───►│ Product Owner  │───►│ Control Agent  │            │
│  │ 0-5 Findings   │    │ Priorisierung  │    │ Entscheidung   │            │
│  │ aus Telemetrie  │    │                │    │ (3-Strike-     │            │
│  └────────────────┘    └────────────────┘    │  Regel, max 3  │            │
│                                               │  Verbesserungen│            │
│                                               └───────┬────────┘            │
│                                            ┌──────────┴──────────┐         │
│                                            ▼                     ▼         │
│                                   ┌────────────────┐   ┌────────────────┐  │
│                                   │ Prompt         │   │ Tool           │  │
│                                   │ Engineer       │   │ Builder        │  │
│                                   └────────────────┘   └────────────────┘  │
│                                                                │           │
│                                                                ▼           │
│                                                     ┌────────────────┐     │
│                                                     │ A/B-Test       │     │
│                                                     │ Welch t-Test   │     │
│                                                     │ Cohen's d      │     │
│                                                     │ p<0.05, >10%  │     │
│                                                     └────────────────┘     │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                     SKILL DEVELOPMENT TEAM (5 Rollen)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│  │Researcher│─►│Architect │─►│Implement.│─►│Reviewer  │                   │
│  │Pakete +  │  │API +     │  │Code +    │  │Qualitaet │                   │
│  │Ansaetze  │  │Tests     │  │Double-   │  │+Sicher-  │                   │
│  │recherch. │  │designen  │  │Loop      │  │heit      │                   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘                   │
│                                                                             │
│  ┌──────────┐                                                               │
│  │Proposer  │  (Nur fuer Planning-Skills: Reasoning-Anweisungen)           │
│  └──────────┘                                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. SoK Skill-Modell: S = (C, pi, T, R)

Das Skill-Modell basiert auf der formalen Definition aus der State of Knowledge (SoK) Literatur:

```
S = (C, π, T, R)

C = Applicability Condition  → WANN soll der Skill eingesetzt werden?
    Beispiel: "Wenn ein Audio-Transkript in Text umgewandelt werden muss"

π = Instructions (Policy)    → WIE soll der Skill ausgefuehrt werden?
    Beispiel: "Verwende faster-whisper fuer lokale Transkription"

T = Termination Condition    → WANN ist der Skill fertig?
    Beispiel: "Wenn das Transkript vollstaendig als Text vorliegt"

R = Interface (Resources)    → WAS nimmt der Skill entgegen / gibt er zurueck?
    input_schema:  {"audio_path": "string"}
    output_schema: {"transcript": "string", "confidence": "number"}
```

### Zwei Skill-Typen

| Typ | Beschreibung | Code | Ausfuehrung |
|-----|-------------|------|-------------|
| **functional** | Ausfuehrbarer Python-Code | `def execute(input_data: dict) -> dict` | Docker Sandbox |
| **planning** | Reasoning-Anweisungen (kein Code) | NULL | Als Kontext in Agent-Prompt injiziert |

### Skill-Entwicklung: Double-Loop Self-Healing

```
┌───────────────────────────────────────────────────────────────────────┐
│                    DOUBLE-LOOP SELF-HEALING                            │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Aeussere Schleife (Session-Restart, max N Sessions):                 │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ Innere Schleife (Debug-Cycles, max 10 Iterationen):             │  │
│  │                                                                  │  │
│  │  Code schreiben → Sandbox-Test → Fehler?                        │  │
│  │                                   │                              │  │
│  │                    ┌──────────────┼──────────────┐               │  │
│  │                    ▼              ▼              ▼               │  │
│  │             IMPORT_ERROR    STRUCTURE_     LOGIC_ERROR           │  │
│  │             Alt. Pakete    ERROR           Ansatz                │  │
│  │             vorschlagen    Umschreiben    aendern                │  │
│  │                    │              │              │               │  │
│  │                    └──────────────┼──────────────┘               │  │
│  │                                   ▼                              │  │
│  │                    Library-Alternative nach 3x                   │  │
│  │                    gleiche Lib fehlgeschlagen                    │  │
│  │                    (torch→onnxruntime, pandas→polars, ...)       │  │
│  │                                   │                              │  │
│  │                    Oszillation nach 5 Iterationen?               │  │
│  │                    → Komplett-Regenerierung (aeussere Schleife)  │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 5. Shared Memory (Hybrid RAG)

### 5.1 Drei-Schichten-Architektur

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: Working Memory (Intra-Execution)                      │
│  = ArtifactPool (session-scoped, nicht persistiert)             │
│  → Agenten kommunizieren ueber typisierte Artifacts             │
│  → Validierung on-write (Fail-Fast)                             │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: Episodic (Rohdaten, PostgreSQL)                       │
│  = ExecutionTelemetry, AgentExecutionEvents                     │
│  → Append-only, NICHT in Prompts injiziert                      │
│  → Dient der Evolution-Analyse                                  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: Semantic (Cross-Execution, PostgreSQL + Qdrant)       │
│  = Facts mit Embeddings                                         │
│  → Nur Entry-Point-Agent bekommt Cross-Execution-Memory         │
│  → Score >= 0.30, max 8 Facts, ACON-komprimiert (max 4000 Tok) │
│  → Agent-spezifische Query (nicht generisch)                    │
└─────────────────────────────────────────────────────────────────┘
         ▲              ▲              ▲              ▲
         │              │              │              │
    ┌────┴────┐   ┌────┴────┐   ┌────┴────┐   ┌────┴────┐
    │ Agent 1 │   │ Agent 2 │   │ Agent 3 │   │ Agent N │
    └─────────┘   └─────────┘   └─────────┘   └─────────┘
```

### 5.2 Konfiguration

| Parameter | Wert | Begruendung |
|-----------|------|-------------|
| `shared_memory_max_items` | 8 | Complexity Trap: wenige relevante besser als viele zufaellige |
| `shared_memory_max_tokens` | 4000 | Konservatives Budget, ACON-komprimiert |
| `shared_memory_top_k` | 5 | Post-Filter Cap pro Agent |
| `shared_memory_score_threshold` | 0.30 | G-Memory: Score-Filter ist Pflicht |
| `embed_model_name` | `paraphrase-multilingual-MiniLM-L12-v2` | Multilinguales Embedding-Modell |

### 5.3 Memory-Optimierung (RQ2-relevant)

**Problem (Benchmark 2026-04-27):** Shared Memory verbesserte Pass@1 (+10 pp), erhoehte aber Tokens (+10.8%).

**Loesung (Sprint A+B):**
1. Dead-Code-Entfernung (dreifache Duplikation)
2. ACON-Kompression statt pretty-printed JSON (26-54% Token-Reduktion)
3. Score-Threshold 0.30 (statt ungefiltert)
4. Entry-Point-Only: Nur der erste Agent bekommt Cross-Execution-Memory
5. Agent-spezifische Query statt generischer Suche

**Ergebnis:** -49.7% Token-Verbrauch bei +3.3 pp Pass@1 gegenueber Cold-Baseline.

---

## 6. Sicherheitsarchitektur

### 6.1 Sandbox (Docker)

```
┌──────────────────────────────────────────────────────────────────────┐
│                           SANDBOX ARCHITEKTUR                         │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│    Generierter Skill-Code                                            │
│           │                                                          │
│           ▼                                                          │
│    ┌──────────────────────┐                                          │
│    │  1. Code-Review      │                                          │
│    │  (Reviewer-Agent)    │ ── Qualitaet, Sicherheit, Best Practices │
│    └──────────┬───────────┘                                          │
│               │ [OK]                                                 │
│               ▼                                                      │
│    ┌──────────────────────┐     ┌─────────────────────────┐         │
│    │  2. Sandbox-Exec     │────►│     Docker Container    │         │
│    │  (DynamicSandbox-    │     │  ┌─────────────────────┐│         │
│    │   Service)           │     │  │ • RAM: 2 GB         ││         │
│    └──────────┬───────────┘     │  │ • CPU: 1 Core       ││         │
│               │                  │  │ • Timeout: 600s     ││         │
│               │                  │  │ • Netzwerk: aktiv   ││         │
│               │                  │  │ • pip/apt: erlaubt  ││         │
│               │                  │  │ • /data Mount       ││         │
│               │                  │  └─────────────────────┘│         │
│               │                  └─────────────────────────┘         │
│               │ [Tests bestanden]                                    │
│               ▼                                                      │
│    ┌──────────────────────┐                                          │
│    │  3. Semantische      │                                          │
│    │  Validierung         │ ── Output-Typ-Pruefung (Threshold 0.7)   │
│    └──────────┬───────────┘                                          │
│               │ [OK]                                                 │
│               ▼                                                      │
│    ┌──────────────────────┐                                          │
│    │  4. A/B-Testing      │                                          │
│    │  (Evolution Loop)    │ ── Welch t-Test, Cohen's d               │
│    │                      │    p < 0.05 AND effect > 10%             │
│    └──────────────────────┘                                          │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.2 "Lying Tools" Erkennung

Ein generierter Skill koennte behaupten, etwas Harmloses zu tun, aber tatsaechlich schaedlichen Code ausfuehren. Schutzmaßnahmen:

1. **Reviewer-Agent** prueft Code-Qualitaet und Sicherheit vor Sandbox-Ausfuehrung
2. **Semantische Validierung** vergleicht tatsaechlichen Output mit erwarteter Beschreibung
3. **Docker-Isolation** begrenzt Ressourcen und verhindert Host-Zugriff
4. **Regressionstests** bei Skill-Updates (Parent-Tests muessen weiterhin bestehen)

---

## 7. Anwendungsfall: Baustellenberichte

**Eingabe:** Audio-Transkript einer Baustellenbesprechung
**Ausgabe:** Strukturierter Bericht nach Firmenstandards

Das System ist domaenen-agnostisch gebaut — die Bau-Domaene dient als Evaluations-Use-Case. Agent- und Skill-Schemas enthalten keine hardcodierten Fachfelder.

### 7.1 Seed-Agenten (Default-Topologie)

| Agent | Wave | Funktion |
|-------|------|----------|
| **transcript_analyzer** | 1 | Transkript analysieren: Sprecher, Themen, Fakten, Massnahmen |
| **context_retriever** | 2 | Historischen Kontext aus SharedMemory holen |
| **report_generator** | 3 | Bericht synthetisieren aus Analyse + Kontext |
| **quality_validator** | 4 | Vollstaendigkeit und Richtigkeit pruefen |
| **report_finalizer** | 5 | Korrekturen anwenden, Endversion erstellen |

### 7.2 Dynamische Erweiterung

Das System erkennt fehlende Faehigkeiten und baut sie autonom:
- **L1-Tasks** (einfach): Keine neuen Skills noetig, Default-Team reicht
- **L2-Tasks** (erweitert): 1-2 Skills werden gebaut (z.B. Kostenberechnung)
- **L3-Tasks** (komplex): Mehrere Skills + moeglicherweise neue Agenten
- **L4-Tasks** (unbekannt): Neuer Berichtstyp, neues Team, mehrere Zyklen

---

## 8. Technologie-Stack

```
┌─────────────────────────────────────────────────────────┐
│                      FRONTEND                            │
│  Next.js 16 + React 19 + Tailwind v4 + shadcn/ui        │
│  TypeScript | SSE-Streaming | API-Client (api.ts)        │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────────┐
│                      BACKEND                             │
│  FastAPI + Pydantic 2 + SQLAlchemy 2 (async)             │
│  Python 3.12 | asyncio | Instructor (Structured LLM)     │
│  OpenTelemetry | Rate Limiting | Security Middleware      │
└──┬──────────────┬──────────────┬────────────────────────┘
   │              │              │
   ▼              ▼              ▼
┌──────┐   ┌──────────┐   ┌──────────┐
│ LLM  │   │PostgreSQL│   │  Qdrant  │
│LiteLLM│  │ asyncpg  │   │ Vektoren │
│Gemini │  │Continuum │   │  (RAG)   │
│OpenAI │  │Versioning│   │ cosine   │
│Claude │  │          │   │ 0.30 min │
│vLLM   │  │ 20 Pool  │   │          │
│Ollama │  │ 20 Over  │   │          │
└──────┘   └──────────┘   └──────────┘
                              │
┌─────────────────────────────▼───────────────────────────┐
│                   SANDBOX                                │
│  Docker Container | 2GB RAM | 1 CPU | 600s Timeout       │
│  Netzwerk aktiv | pip/apt Installation | /data Mount      │
└─────────────────────────────────────────────────────────┘
```

| Komponente | Technologie | Zweck |
|------------|-------------|-------|
| **Backend** | FastAPI (Python 3.12) | REST API + Background Tasks |
| **Validierung** | Pydantic 2 + Instructor | Strukturierte LLM-Outputs, Schema-Validierung |
| **Datenbank (relational)** | PostgreSQL + asyncpg | Transaktionale Daten, Versionierung (16+ Tabellen) |
| **Vektordatenbank** | Qdrant | Semantische Suche (Fact-Embeddings, cosine similarity) |
| **Embedding** | sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2) | Multilinguales Embedding |
| **LLM-Abstraktion** | LiteLLM | Provider-agnostisch (Gemini, OpenAI, Claude, vLLM, Ollama) |
| **Structured Output** | Instructor | Pydantic-basierte LLM-Responses |
| **Versionierung** | SQLAlchemy-Continuum | Automatische Versionierung (Prompt, Agent, Skill) |
| **Sandbox** | Docker (direkt) | Isolierte Code-Ausfuehrung mit pip/apt |
| **Frontend** | Next.js 16 + React 19 | App Router, SSE-Streaming, shadcn/ui |
| **Observability** | OpenTelemetry | Distributed Tracing |

---

## 9. Datenbank-Schema (16+ Tabellen)

### 9.1 Versionierte Artefakte

```sql
Prompt {
    id: UUID PK,
    parent_id: UUID FK → Prompt,   -- Lineage fuer Rollback
    name: VARCHAR,
    content: TEXT,
    prompt_metadata: JSONB,
    is_active: BOOLEAN
}

Agent {
    id: UUID PK,
    name: VARCHAR UNIQUE,
    dependencies: JSONB,           -- Abhaengigkeiten zu anderen Agenten
    io_schema: JSONB,              -- input/output/consumes/produces
    is_active: BOOLEAN,
    prompt_id: UUID FK → Prompt,
    source: VARCHAR,               -- "seed" | "auto_generated" | "evolved"
    agent_metadata: JSONB          -- provisional, promoted_at, etc.
}

Skill {
    id: UUID PK,
    parent_id: UUID FK → Skill,    -- Versionskette
    name: VARCHAR,
    skill_type: VARCHAR,           -- "functional" | "planning"
    applicability: TEXT,           -- SoK C-Feld
    instructions: TEXT,            -- SoK π-Feld
    termination: TEXT,             -- SoK T-Feld
    interface: JSONB,              -- SoK R-Feld (input/output Schema)
    code: TEXT,                    -- Nur functional Skills
    dependencies: JSONB,           -- pip/apt Requirements
    test_cases: JSONB,
    is_active: BOOLEAN
}

SkillBinding {
    id: UUID PK,
    skill_id: UUID FK → Skill,
    agent_id: UUID FK → Agent,     -- NULL = global verfuegbar
    capability: VARCHAR,
    binding_type: VARCHAR,
    priority: INTEGER,
    is_active: BOOLEAN
}
```

### 9.2 Execution & Telemetrie

```sql
Execution {
    id: UUID PK,
    challenge_id: UUID,
    status: VARCHAR,               -- running, completed, failed
    results: JSONB,
    duration_ms: INTEGER
}

ExecutionTelemetry {
    id: UUID PK,
    agent_id: UUID,
    execution_id: UUID,
    latency_ms: FLOAT,
    tokens_total: INTEGER,
    outcome: VARCHAR,
    input_hash: VARCHAR            -- Fuer Deduplizierung
}

AgentExecutionEvent {
    id: UUID PK,
    execution_id: UUID FK,
    agent_name: VARCHAR,
    status: VARCHAR,
    result: JSONB,
    error: TEXT
}
```

### 9.3 Shared Memory

```sql
Fact {
    id: UUID PK,
    text: TEXT,
    confidence: FLOAT,
    source_agent_id: UUID,
    execution_id: UUID,
    project_id: UUID,
    embedding_id: VARCHAR          -- Qdrant Point ID
}

Relation {
    id: UUID PK,
    source_fact_id: UUID FK → Fact,
    target_fact_id: UUID FK → Fact,
    relation_type: VARCHAR
}
```

### 9.4 Evolution & Verbesserung

```sql
AnalysisFinding {
    id: UUID PK,
    execution_id: UUID,
    finding_type: VARCHAR,         -- error_pattern, capability_gap, etc.
    severity: VARCHAR,
    suggested_fix: TEXT,
    confidence: FLOAT,
    fingerprint: VARCHAR           -- Fuer 3-Strike-Regel
}

ImprovementAttempt {
    id: UUID PK,
    finding_id: UUID FK,
    artifact_type: VARCHAR,        -- "prompt" | "skill"
    status: VARCHAR,
    ab_test_id: UUID FK
}

ABTest {
    id: UUID PK,
    variant_a_id: UUID,
    variant_b_id: UUID,
    status: VARCHAR,
    winner: VARCHAR
}

SkillBuildAttempt {
    id: UUID PK,
    skill_name: VARCHAR,
    status: VARCHAR,
    error_log: TEXT,
    lesson_learned: TEXT           -- Reflexion-Memory (Reflexion-Pattern)
}
```

---

## 10. Forschungsfragen

### RQ1: Effektivitaet
> **Fuehrt Structural Self-Evolution (dynamische Erstellung neuer Agenten-Rollen und Skills) zu einer hoeheren Loesungsrate bei komplexen Aufgaben im Vergleich zu statischen MAS-Architekturen?**

**Messung:**
- Pass@1 auf eigenem Progressive-Complexity-Benchmark (30 Tasks, L1-L4)
- Vergleich: Full System vs. Baseline (statisch) vs. Ablation A (ohne Memory)
- Statistik: Wilcoxon Signed-Rank Test (gepaart, nicht-normalverteilt)

### RQ2: Effizienz
> **Reduziert die Wiederverwendung autonom generierter Blueprints den Ressourcenverbrauch bei nachfolgenden Aufgaben gleichen Typs?**

**Messung:**
- Build-Skip-Rate (% der Tasks die existierende Skills wiederverwenden)
- Token-Verbrauch pro Task (Cold vs. Warm Start)
- Effekt optimierter Memory-Injection auf Token-Overhead
- Latenz-Reduktion durch Skill-Reuse (Build-Phase entfaellt)

### RQ3: Sicherheit
> **Kann ein semantischer Gatekeeper-Mechanismus gefaehrliche Diskrepanzen in autogenerierten Agenten-Tools zuverlaessig erkennen und verhindern?**

**Messung:**
- False Positive Rate (faelschlich blockierte sichere Skills)
- False Negative Rate (durchgelassene unsichere Skills)
- Poisoned-Skills-Test-Set (20 gefaehrliche + 20 sichere Skills)
- Gatekeeper-Stufen einzeln und kombiniert testen

---

## 11. Evaluation & Methodik

### 11.1 Progressive Complexity Benchmark (Haupt-Evaluation)

Eigenes Benchmark-Set mit **Baustellenberichten in 4-5 Schwierigkeitsstufen**, 30+ Tasks:

| Level | Beschreibung | Erwartung |
|-------|-------------|-----------|
| **L1** (Standard) | Ein Sprecher, klare Struktur, kein Tool noetig | System loest ohne Intervention |
| **L2** (Erweitert) | Mehrere Sprecher, Domainmischung, leichte Berechnungen | 1-2 Skills werden gebaut |
| **L3** (Komplex) | Querverweise, Berechnungen, neuer Berichtstyp | Mehrere Skills + Topology-Anpassung |
| **L4** (Unbekannt) | Komplett neuer Typ (Brandschutz, Energieausweis) | Neue Agents + Skills, mehrere Zyklen |
| **L5** (Autonom) | Echte Tool-Nutzung (Datenbanken, Dateien, APIs) | Self-Healing + On-Demand-Skill-Build |

### 11.2 Cold Start vs. Warm Start

```
Durchlauf 1 (Cold Start):
  Tasks 1-30 sequenziell, System startet ohne Skills
  → Alles wird neu gebaut

Durchlauf 2 (Warm Start):
  Dieselben 30 Tasks, mit allen gelernten Skills/Memory
  → System nutzt vorhandene Skills wieder

Vergleich: Token-Verbrauch, Latenz, Pass@1, Build-Skip-Rate
```

### 11.3 Ablation Study

| Variante | Intervention | SharedMemory | Skill Reuse | Verify-Adapt | Team Assembly |
|----------|-------------|--------------|-------------|--------------|---------------|
| **Baseline** (statisch) | - | - | - | - | - |
| **Ablation A** (ohne Memory) | + | - | - | + | + |
| **Full System** | + | + | + | + | + |

Feature-Flags in `config.py` ermoeglichen Ablation ohne Code-Aenderung.

### 11.4 Statistische Auswertung

| Test | Anwendung |
|------|-----------|
| **Wilcoxon Signed-Rank** | Gepaarter Vergleich Cold vs. Warm (nicht-normalverteilt) |
| **Mann-Whitney U** | Ungepaartes Token/Latenz-Vergleich |
| **Welch t-Test** | A/B-Tests innerhalb Evolution Loop |
| **Cohen's d** | Effektstaerke |
| **Signifikanzniveau** | p < 0.05 |

### 11.5 Domain-Wechsel (Generalisierungstest)

Nach der Bau-Evaluation: System auf IT-Incident-Reports und Meeting-Protokolle testen.
- Skill Transfer Rate: Welche Bau-Skills funktionieren in neuer Domain?
- Adaptionsgeschwindigkeit: Wie viele Tasks bis >80% Erfolgsrate?

### 11.6 Benchmark-Ergebnisse (Stand Mai 2026)

| Run | Pass@1 | Tokens | Δ Tokens vs. Cold | Δ Pass@1 vs. Cold |
|-----|--------|--------|--------------------|--------------------|
| Cold Baseline | 56.7% | 2.363.934 | — | — |
| Warm Baseline | 66.7% | 2.594.965 | +9.8% | +10.0 pp |
| **Sprint A+B Cold** | **60.0%** | **1.188.091** | **-49.7%** | **+3.3 pp** |

---

## 12. Verify-Adapt Eskalationsmodell

```
┌───────────────────────────────────────────────────────────┐
│              VERIFY-ADAPT ESKALATION                       │
├───────────────────────────────────────────────────────────┤
│                                                           │
│  Score >= 0.85  ──────────────────────────► PASS          │
│                                                           │
│  0.4 <= Score < 0.85  ──► REPLAN_FEEDBACK                 │
│                            Gleiche Agenten + Feedback      │
│                            │                               │
│                            └─► 2. Failure → REPLAN_NEW_TEAM│
│                                                           │
│  0.1 <= Score < 0.4   ──► REPLAN_NEW_TEAM                 │
│                            Neues Team assemblieren          │
│                                                           │
│  Score < 0.1           ──► ESCALATE                        │
│  ODER Capability Gap       Gap Building starten            │
│                                                           │
│  Thresholds konfigurierbar in config.py                    │
│  Max Adapt-Runden: 3 (konfigurierbar)                     │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

---

## 13. Evolution Loop

```
HybridOrchestrator
    │ (nach erfolgreicher Ausfuehrung)
    ▼
AnalysisPipeline.analyze(execution_telemetry)
    │ → Analyzer Agent: 0-5 Findings
    │ → ProductOwner Agent: Priorisierung
    ▼
ControlAgent.decide(findings)
    │ → Max 3 Verbesserungen pro Zyklus
    │ → 3-Strike-Regel: Finding 3x abgelehnt → skip
    ▼
ImprovementOrchestrator.execute(decision)
    │ → artifact_type == "prompt" → PromptEngineer
    │ → artifact_type == "skill"  → ToolBuilder
    ▼
ABTestService.create(baseline, improved)
    │ → Welch t-Test, Cohen's d
    │ → p < 0.05 AND effect > 10%
    ▼
Winner → Aktivierung (oder Rollback)
```

**Fire-and-Forget:** Laeuft als asyncio Background Task nach jeder Execution. Exception-Logging explizit erzwungen (Silent-Failure-Praevention).

---

## 14. Feature-Flags (Ablation-Support)

| Flag | Default | Beschreibung |
|------|---------|-------------|
| `hot_reload_enabled` | True | In-Memory Skill Registry |
| `autonomous_evolution_enabled` | True | Post-Execution Evolution Loop |
| `shared_memory_enabled` | True | Cross-Run-Lernen via Qdrant |
| `skill_reuse_enabled` | True | Wiederverwendung gebauter Skills |
| `verify_adapt_enabled` | True | Verify-Adapt Loop |
| `team_assembly_enabled` | True | Dynamische Team-Komposition per LLM |
| `semantic_validation_enabled` | True | Output-Validierung (0.7 Threshold) |
| `intra_execution_self_healing_enabled` | True | On-Demand Skill Build bei unbekanntem Tool |
| `agent_promotion_enabled` | True | Provisorische Agents befoerdern |

---

## 15. Wichtige Konfigurationsparameter

| Parameter | Wert | Kontext |
|-----------|------|---------|
| `build_total_timeout` | 900s | Hard-Cap fuer Skill-Building |
| `self_healing_timeout` | 600s | Pro Skill-Build im Self-Healing |
| `self_healing_max_builds_per_execution` | 3 | Max On-Demand Skills pro Run |
| `max_tool_calls` | 15 | Max Tool-Aufrufe pro Agent |
| `max_adapt_rounds` | 3 | Max Verify-Adapt Iterationen |
| `verification_completeness_threshold` | 0.85 | Mindest-Score fuer PASS |
| `adapt_threshold_new_team` | 0.4 | Score-Schwelle fuer REPLAN_NEW_TEAM |
| `adapt_threshold_escalate` | 0.1 | Score-Schwelle fuer ESCALATE |
| `control_agent_max_batch` | 3 | Max Verbesserungen pro Evolution-Zyklus |
| `control_agent_max_strikes` | 3 | 3-Strike-Regel Limit |
| `rate_limit_per_minute` | 120 | API Rate Limiting |
| `llm_timeout` | 120s | LLM API Timeout |
| `pool_size` | 20 | DB Connection Pool |

---

## 16. API-Routing Uebersicht

| Flow | Endpoints | Services |
|------|-----------|----------|
| **Challenge analysieren** | `POST /challenges/analyze` | PreExecutionOrchestrator → ChallengeAnalyzer → FeasibilityJudge |
| **Challenge ausfuehren** | `POST /challenges/{id}/execute` | HybridOrchestrator → TeamAssembler → GenericAgentExecutor |
| **Skill bauen** | `POST /challenges/build-skill` | SkillTeamOrchestrator (5 Rollen) |
| **Evolution triggern** | `POST /evolution/executions/{id}/evolve` | EvolutionLoopService → AnalysisPipeline → ControlAgent |
| **Benchmark starten** | `POST /evaluation/runs` | BenchmarkRunner → Cold/Warm Setup → Task-Execution |
| **Live-Streaming** | `GET /events/execution/{id}` | SSE mit 0.5s Polling, Heartbeat alle 10s |
| **Topologie** | `GET /topology` + `GET /topology/reactflow` | TopologyLoader + ReactFlow-Format |

---

## 17. Verwandte Arbeiten & Abgrenzung

### 17.1 Schluessel-Referenzen

| Kategorie | Arbeit | Relevanz |
|-----------|--------|----------|
| Self-Evolving Agent | **Voyager** (Wang et al. 2023) | Skill-Library-as-Code + Auto-Curriculum |
| Self-Evolving Agent | **Reflexion** (Shinn et al. 2023) | Legitimiert SkillBuildAttempt.lesson_learned Pattern |
| Tool-Generation | **LATM** (Cai et al. 2023) | Zweistufige Architektur (Maker/User) |
| Tool-Generation | **ToolMaker** (Woelflein et al., ACL 2025) | Install-and-Verify-Gate = Gatekeeper-Pattern |
| Prompt-Optimization | **PromptBreeder** (Fernando et al. 2023) | Population als Baum — validiert Prompt.parent_id Lineage |
| Dynamic Topology | **GPTSwarm** (Zhuge et al. 2024) | Agents=Nodes, Edges=Channels |
| Dynamic Topology | **ADAS** (Hu et al. 2024) | Meta-Agent + Discovery-Archive |
| Memory | **G-Memory** (NeurIPS 2025) | Score-basiertes Filtern |
| Memory | **ACON** (arXiv:2510.00615) | Kontext-Kompression |
| Memory | **IMA** (arXiv:2508.08997) | Per-Agent-Relevanz statt Broadcast |

### 17.2 Unser Beitrag

- **Voyager** kann Skills + Curriculum, nicht Topologie
- **GPTSwarm / ADAS** koennen Topologie, nicht Skill-Generierung
- **PromptBreeder** kann Prompts, hat keine Tools

**Unsere Kombination (Skills + Prompts + Topologie + Shared Memory mit voller Evolution-Observability) ist in der Literatur nicht etabliert.**

---

## 18. Glossar

| Begriff | Definition |
|---------|------------|
| **Structural Self-Evolution** | Faehigkeit eines Systems, seine eigene Struktur (Agenten, Skills, Topologie) zur Laufzeit zu aendern |
| **Wave** | Gruppe von Agenten ohne gegenseitige Abhaengigkeiten, parallel ausfuehrbar |
| **Artifact** | Typisiertes Zwischenergebnis zwischen Agenten innerhalb einer Session |
| **Fact** | Persistiertes Wissen in SharedMemory mit Confidence-Score und Embedding |
| **Gap** | Fehlende Faehigkeit, die gebaut werden muss (Skill, Prompt, Agent) |
| **SoK** | State of Knowledge — formales Skill-Modell S=(C, pi, T, R) |
| **ACON** | Kompaktes Textformat fuer SharedMemory-Injection (statt JSON) |
| **3-Strike-Regel** | Gleiches Finding 3x abgelehnt → wird uebersprungen |
| **Double-Loop** | Aeussere Schleife (Session-Restart) + Innere Schleife (Debug-Cycles) |
| **Hot-Reload** | Skills werden nach Build sofort in-memory verfuegbar (kein Neustart) |
| **Provisional Agent** | Auto-generierter Agent, wird nach Erfolg permanent befoerdert |
| **TeamAssembler** | LLM-basierter Planner, der aufgabenspezifische Teams aus Agentenpool zusammenstellt |
| **StrategyMemory** | Cross-Run-Lernen: erfolgreiche/gescheiterte Strategien als Facts gespeichert |
| **Verify-Adapt Loop** | Iterative Ergebnis-Verbesserung mit 3 Eskalationsstufen |
| **Build-Skip-Rate** | Anteil der Tasks, die existierende Skills wiederverwenden statt neu zu bauen |
| **HITL** | Human-in-the-Loop — Mensch wird bei Unklarheiten einbezogen |
| **Capability Gap** | Erkannte Faehigkeitsluecke, die neue Skills/Agenten erfordert |

---

## 19. Zusammenfassung

Lumari ist ein **selbst-evolvierendes Multi-Agenten-System**, das:

1. **Strukturelle Evolution** ermoeglicht — nicht nur Tools, sondern Skills (SoK-Modell), Prompts und Team-Topologien werden dynamisch angepasst

2. **Aus Erfahrung lernt** — durch Hybrid-RAG (PostgreSQL + Qdrant), Strategy Memory und Skill-Reuse werden erfolgreiche Konfigurationen wiederverwendet

3. **Iterativ verfeinert** — der Verify-Adapt Loop mit 3 Eskalationsstufen verbessert Ergebnisse systematisch ohne menschliches Eingreifen

4. **Sicher bleibt** — Docker-Sandbox, Reviewer-Agent, Semantische Validierung und A/B-Testing verhindern unsichere Skills

5. **Empirisch evaluierbar** ist — Feature-Flags ermoeglichen Ablation, eigener Progressive-Complexity-Benchmark mit Cold/Warm-Vergleich und statistischen Tests

**Forschungsbeitrag:** Die Kombination von Skill-Generierung + Prompt-Evolution + dynamischer Topologie + Shared Memory mit voller Evolution-Observability in einem geschlossenen, autonomen Loop ist in der Literatur nicht etabliert. Jedes Teilsystem hat akademische Vorbilder (Voyager, PromptBreeder, GPTSwarm), aber die Integration und das Zusammenspiel sind neu.

---

*Stand: Mai 2026 | Basiert auf aktueller Codebase-Analyse*