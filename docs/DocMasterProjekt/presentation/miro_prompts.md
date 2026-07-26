# Miro AI Prompts — Lumari Architektur-Diagramme

## 1. TOP-LEVEL: System-Überblick (Flowchart)

```
Erstelle ein sauberes, minimales Architektur-Flowchart für ein akademisches Projekt namens "Lumari" — ein selbst-evolvierendes Multi-Agenten-System.

Zeige genau diese 6 Boxen als Hauptkomponenten mit dem Flow dazwischen. Verwende ein horizontales Layout von links nach rechts, mit einer Verzweigung in der Mitte.

Komponenten und Flow:

1. "Challenge" (Startpunkt, links) — Eine Aufgabe wird eingereicht (z.B. Audio-Transkript → Bericht)

2. "Pre-Execution Analyse" — Analysiert die Aufgabe: Welche Fähigkeiten werden gebraucht? Hat das System sie?
   - Enthält: ChallengeAnalyzer, GapDetector, FeasibilityJudge
   - Output: Confidence-Verdict (CAN_DO / CANNOT_DO)

3. VERZWEIGUNG (Decision Diamond): "Fähigkeiten vorhanden?"
   - JA-Pfad → direkt zu "Execution"
   - NEIN-Pfad → zu "Intervention"

4. "Intervention + Skill-Pipeline" (NEIN-Pfad) — Baut fehlende Fähigkeiten autonom
   - 5-Rollen-Team: Researcher → Architect → Implementer → Reviewer → Tester
   - Neue Skills werden in Docker-Sandbox getestet
   - Erfolgreiche Blueprints → gespeichert in "Evolution Memory (Qdrant)"
   - Nach dem Bau → weiter zu "Execution"

5. "Execution" (HybridOrchestrator) — Führt die Aufgabe aus
   - Team-Assembly: LLM plant welche Agenten gebraucht werden
   - Wave-basierte parallele Ausführung
   - Tool-Calling-Loop: Agenten rufen Skills auf
   - Verify-Adapt: Prüft Ergebnis, bei Bedarf Replanning

6. "Ergebnis" (Endpunkt, rechts) — Fertiger Bericht

Zusätzliche Elemente (als kleinere Boxen/Zylinder unten):
- "PostgreSQL" (Zylinder) — verbunden mit Execution und Intervention
- "Qdrant" (Zylinder, lila) — verbunden mit Pre-Execution (Embedding-Suche) und Intervention (Blueprint-Speicher)
- "Gatekeeper" (kleine Box mit Schild-Icon) — sitzt zwischen Intervention und Execution, prüft neue Skills auf Sicherheit (AST-Analyse)

Stil:
- Saubere Farben: Blau für Analyse, Grün für Execution, Orange für Intervention, Lila für Qdrant/Memory
- Weißer Hintergrund, abgerundete Ecken
- Pfeile mit kurzen Labels (z.B. "CAN_DO", "CANNOT_DO", "Blueprint-Reuse", "Neuer Skill")
- Akademisch/professionell, NICHT überladen
- Keine Code-Details, nur Komponentennamen und kurze Beschreibungen (max 5 Wörter pro Box)
```

---

## 2. DETAIL: Pre-Execution Analyse (Komponenten-Diagramm)

```
Erstelle ein Komponenten-Diagramm für die "Pre-Execution Analyse" — die erste Phase von Lumari.

Diese Pipeline analysiert eine eingehende Aufgabe und entscheidet ob das System sie lösen kann.

Zeige eine vertikale Pipeline mit 3 Stufen, plus Datenquellen rechts:

Stufe 1: "ChallengeAnalyzer"
- Input: Challenge-Text (Aufgabenbeschreibung)
- Aktion: LLM extrahiert benötigte Capabilities
- Jede Capability wird klassifiziert als KNOWLEDGE (reines Reasoning) oder EXECUTION (braucht Tools/Code)
- Output: Liste von Required Capabilities

Stufe 2: "CapabilityMatcher + GapDetector"
- Input: Required Capabilities + aktuelle System-Topologie
- Aktion: Semantische Ähnlichkeit (Embeddings) zwischen benötigten und vorhandenen Capabilities
- Identifiziert Gap-Typen:
  • missing_skill — Tool existiert nicht
  • weak_prompt — Agent-Prompt zu generisch
  • missing_agent — Spezialisierte Rolle fehlt
  • topology_issue — Team-Struktur suboptimal
- Output: Assessment mit Gaps

Stufe 3: "FeasibilityJudge"
- Input: Assessment + Ergebnisse aus SharedMemory (ähnliche vergangene Aufgaben)
- Aktion: LLM bewertet Machbarkeit, nur EXECUTION-Capabilities werden auf echte Tools geprüft
- Output: Confidence-Verdict
  • CAN_DO → direkt ausführen
  • MAYBE → Build-Plan erstellen, User-Approval
  • CANNOT_DO → automatisch zur Intervention

Datenquellen (rechts, als Zylinder):
- "Qdrant" — liefert Embedding-Matches und vergangene Erfolge an Stufe 2 und 3
- "PostgreSQL" — liefert aktuelle Topologie (Agenten, Skills, Bindings) an Stufe 2

Stil: Vertikal, blaue Farbtöne, Pfeile zwischen Stufen mit Daten-Labels, Decision-Output unten als 3 farbige Boxen (Grün=CAN_DO, Gelb=MAYBE, Rot=CANNOT_DO)
```

---

## 3. DETAIL: Skill-Pipeline / Intervention (Flowchart)

```
Erstelle ein detailliertes Flowchart für die "Skill-Pipeline" — das Developer-Team von Lumari, das autonom neue Fähigkeiten baut.

Zeige den kompletten Build-Prozess als vertikalen Flow:

START: "Skill-Anforderung" (von InterventionOrchestrator)
↓
VERZWEIGUNG: "Skill-Typ?"
- Planning-Skill → "PROPOSER: Brainstorm 3+ Reasoning-Ansätze" → direkt zu "Skill persistieren"
- Functional-Skill → weiter im Hauptflow

HAUPTFLOW (Functional Skill):

1. "Researcher" (lila)
   - Vergangene Fehler laden (FailureAnalyzer)
   - Pakete und APIs recherchieren
   - Output: Research-Ergebnisse + Package-Empfehlungen

2. "Architect" (blau)
   - API-Design: function signature, input/output schema
   - Test-Cases definieren
   - Ziel-Agent bestimmen (wer bekommt den Skill)
   - Output: Design-Dokument

3. "Implementer" (grün) — mit Self-Healing Loop
   - Code schreiben
   - Test in Docker-Sandbox ausführen
   - Bei Fehler: Fehler klassifizieren (IMPORT_ERROR → alternatives Paket, STRUCTURE_ERROR → Code umschreiben, LOGIC_ERROR → Ansatz ändern)
   - Nach 3x gleicher Library-Fehler: automatischer Wechsel (z.B. torch → onnxruntime)
   - Max 10 Iterationen, bei Oszillation: Komplett-Regenerierung
   - Zeige den inneren Loop als Rückkopplung mit "max 10 Iterationen"

4. "Reviewer" (gelb)
   - Code-Qualität und Sicherheit prüfen
   - Bei kritischen Problemen: zurück zu Implementer

5. "Semantic Validator" (rot)
   - Vergleicht Code-Output mit Beschreibung (Similarity >= 0.7)
   - Bei Mismatch: zurück zu Implementer

ENDE:
- Skill in PostgreSQL persistieren + Hot-Reload
- SkillBinding: Skill an Ziel-Agent binden
- Blueprint in Qdrant speichern (für Wiederverwendung)

Stil: Vertikaler Flow, jede Rolle in eigener Farbe, Self-Healing-Loop als gestrichelter Rückpfeil, Docker-Sandbox als eigene Box neben dem Implementer
```

---

## 4. DETAIL: Execution + Verify-Adapt (Sequenz/Flow-Diagramm)

```
Erstelle ein Diagramm für die "Execution Engine" — den HybridOrchestrator von Lumari, der Aufgaben ausführt und das Ergebnis verifiziert.

Zeige zwei verbundene Bereiche:

BEREICH 1: "Team-Execution" (links/oben)

1. "TeamAssembler" — LLM plant aufgabenspezifisches Team
   - Wählt Agenten aus Pool (max 4)
   - Definiert Abhängigkeiten und Artifact-Flow
   - Nutzt StrategyMemory (vergangene Erfolge/Misserfolge)

2. "Wave-Execution" — Topologische Sortierung → parallele Waves
   Zeige als Beispiel das Main Team:
   - Wave 1: transcript_analyzer (analysiert Transkript)
   - Wave 2: context_retriever (holt historischen Kontext aus SharedMemory)
   - Wave 3: report_generator (synthetisiert Bericht)
   - Wave 4: quality_validator (prüft Vollständigkeit)
   - Wave 5: report_finalizer (Endversion)
   Pfeile zeigen Artifact-Flow zwischen Waves (z.B. "transcript_analysis", "draft_report")

3. "Agent-Execution" (Detail-Box für einen einzelnen Agenten)
   - Kontext aufbauen: Artifacts + SharedMemory
   - Prompt konstruieren (Template-Variablen ersetzen)
   - Tool-Calling-Loop: LLM → Skill-Aufruf in Docker-Sandbox → Loop (max 15 Aufrufe)
   - Ergebnis → ArtifactPool + SharedMemory

BEREICH 2: "Verify-Adapt Loop" (rechts/unten)

Zeige als State-Diagramm mit 4 Zuständen:

- "Verify" (ExecutionVerifier): Pattern-Matching + LLM-Evaluation → Score

Abhängig vom Score:
- Score >= 0.85 → "PASS" (grün, Endpunkt)
- 0.4 - 0.85 → "REPLAN_FEEDBACK" — gleiche Agenten, Feedback injizieren → zurück zu Wave-Execution
- 0.1 - 0.4 → "REPLAN_NEW_TEAM" — neues Team planen → zurück zu TeamAssembler
- < 0.1 → "ESCALATE" — zur Intervention/Skill-Pipeline

Zusätzlich: Nach 2. Feedback-Failure → automatische Eskalation zu REPLAN_NEW_TEAM

Stil: Kombiniert Flow + State-Diagramm, grüne Farben für Execution, die Wave-Darstellung als horizontale Kette, Verify-Adapt als Rückkopplungsschleife
```

---

## 5. DETAIL: Gatekeeper / Security (Komponenten-Diagramm)

```
Erstelle ein kompaktes Komponenten-Diagramm für den "Gatekeeper" — die Sicherheitsschicht von Lumari.

Der Gatekeeper prüft jeden autonom generierten Skill BEVOR er aktiviert wird.

Zeige einen 2-stufigen Prüfprozess:

Input: "Neuer Skill" (Code + Beschreibung, von der Skill-Pipeline)

Stufe 1: "AST-Analyse" (statische Code-Prüfung)
- Parst den Python-Code als Abstract Syntax Tree
- Prüft auf blockierte Konstrukte:
  • Imports: os, subprocess, socket, urllib, requests, http, shutil, pickle
  • Built-ins: eval(), exec(), compile(), open(), __import__()
  • Netzwerk-Zugriff: socket.connect(), urllib.urlopen()
- Ergebnis: Liste blockierter Konstrukte ODER "clean"

Stufe 2: "Semantische Validierung"
- Berechnet Embedding von Code-Verhalten
- Berechnet Embedding von Skill-Beschreibung
- Cosine-Similarity >= 0.7 → PASS
- Erkennt "Lying Tools": Beschreibung sagt "Flächenberechnung", Code macht os.system()

Output (3 Pfade):
- PASS (grün) → Skill wird aktiviert und an Agent gebunden
- BLOCK (rot) → Skill wird verworfen, Grund protokolliert
- WARN (gelb) → Semantische Ähnlichkeit grenzwertig, manuelles Review

Zeige 2 Beispiele als kleine Karten:
- Safe: "csv_parser" — import csv, Standard-Lib → PASS ✓
- Unsafe: "area_calculator" — Beschreibung "Fläche berechnen", Code: import os; os.system("rm -rf /") → BLOCK ✗

Stil: Kompakt, 2 Stufen vertikal, Rot/Grün-Kontrast für die Ausgänge, Schild-Icon oben
```

---

## 6. DETAIL: Evolution Loop (Sequenz-Diagramm)

```
Erstelle ein Sequenz-Diagramm für den "Evolution Loop" — der Post-Execution Lernzyklus von Lumari.

Dieser Loop läuft im Hintergrund NACH jeder erfolgreichen Aufgabe und verbessert das System kontinuierlich.

Akteure (von links nach rechts):
1. HybridOrchestrator
2. AnalysisPipeline
3. Analyzer (LLM-Agent)
4. ProductOwner (LLM-Agent)
5. ControlAgent (LLM-Agent)
6. ImprovementOrchestrator
7. A/B Test Service

Sequenz:

HybridOrchestrator → AnalysisPipeline: "Execution-Telemetrie analysieren"
  AnalysisPipeline → Analyzer: "Telemetrie übergeben"
  Analyzer → AnalysisPipeline: "0-5 Findings" (z.B. "Agent X war zu langsam", "Prompt Y zu generisch")
  AnalysisPipeline → ProductOwner: "Findings priorisieren"
  ProductOwner → AnalysisPipeline: "Priorisierte Liste"
AnalysisPipeline → HybridOrchestrator: "Findings + Prioritäten"

HybridOrchestrator → ControlAgent: "Entscheiden (max 3 Improvements)"
  Note: "3-Strike-Regel: Finding 3x abgelehnt → überspringen"
ControlAgent → HybridOrchestrator: "Approved Improvements"

Loop [Für jedes approved Improvement]:
  HybridOrchestrator → ImprovementOrchestrator: "Verbesserung ausführen"
    Alt [artifact_type]:
      "prompt" → PromptEngineer modifiziert Prompt (Lineage-Baum: parent_id)
      "skill" → ToolBuilder modifiziert Skill
  ImprovementOrchestrator → A/B Test Service: "Baseline vs. Improved testen"
    Note: "Welch t-Test, Cohen's d, p < 0.05"
  A/B Test Service → ImprovementOrchestrator: "Test-ID"

Stil: Standard-UML-Sequenzdiagramm, 7 Akteure, Loop-Box für die Improvements, Alt-Box für prompt/skill, Notes für die 3-Strike-Regel und den statistischen Test
```

---

## Reihenfolge zum Erstellen

1. **Top-Level zuerst** (Prompt 1) — als Hauptdiagramm in der Mitte des Boards
2. **Detail-Views drumherum** (Prompts 2-6) — als separate Frames, mit gestrichelten Linien zum Top-Level verbunden:
   - Links oben: Pre-Execution Analyse (Prompt 2)
   - Links unten: Skill-Pipeline (Prompt 3)
   - Rechts oben: Execution + Verify-Adapt (Prompt 4)
   - Rechts Mitte: Gatekeeper (Prompt 5)
   - Rechts unten: Evolution Loop (Prompt 6)