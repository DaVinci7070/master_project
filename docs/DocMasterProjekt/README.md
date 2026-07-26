# **Hauptprojekt:**  *„Dynamische Strukturerweiterung eines Multiagenten System durch autonome Erkennung und Schließung von Fähigkeitslücken"*

> **von Patrick Zilke**
>


---

## Inhalt

1. [Projektidee](#projektidee)
2. [Systemarchitektur](#systemarchitektur)
3. [Zentrale Komponenten](#zentrale-komponenten)
4. [Datenmodell](#datenmodell--die-zentralen-entitäten)
5. [Benchmarks & Evaluation](#benchmarks--evaluation)
6. [Experimentelle Ergebnisse](#experimentelle-ergebnisse)
7. [Technologie-Stack](#technologie-stack)
8. [Setup & Ausführung](#setup--ausführung)
9. [Projektstruktur](#projektstruktur)
10. [Akademischer Kontext & Lizenz](#akademischer-kontext--lizenz)

---

## Projektidee

**Das Problem.** Klassische Multi-Agenten-Systeme (MAS) sind **statisch**: Ihre Agenten und Werkzeuge werden zur Entwicklungszeit festgelegt. Trifft im Betrieb eine Aufgabe ein, für die eine Fähigkeit fehlt, scheitert das System oder ein Mensch muss den fehlenden Skill nachrüsten. Mit wachsender Aufgaben-Vielfalt skaliert dieser manuelle Aufwand nicht.

**Die Idee.** Lumari ist ein Multiagenten System, das seine eigene **Struktur und Fähigkeiten zur Laufzeit erweitern kann**. Statt bei einer Fähigkeitslücke zu scheitern, **erkennt** das System die Lücke, **baut** den fehlenden Skill autonom als ausführbaren Code, **prüft** ihn über einen Sicherheits-Gatekeeper und eine Sandbox und **lernt** aus dem Ergebnis. Über die Zeit wächst so eine wiederverwendbare Skill-Bibliothek, und das System wird mit jeder gelösten Aufgabe leistungsfähiger, ohne menschlichen Eingriff.

**Anwendungsbeispiel für das Projekt.** Als Anwendungsbeispiel dient die automatische Erzeugung strukturierter **Baustellenberichte** aus verschiedenen Quellen (verschiedene Berichte, Audiodateien, neue Datenbanken): Aus unstrukturiertem gesprochenem Text und Berichten müssen Mengen, Materialien, Tätigkeiten, Mängel und Termine extrahiert, validiert und in ein definiertes Berichtsformat gebracht werden. Solche Aufgaben verlangen je nach Eingabe unterschiedliche Fähigkeiten (Einheiten-Umrechnung, Tabellen-Aggregation, Datums-Normalisierung, Audiofiletranskripierung, verbinden und auslesen von Datenbanken …). Die Agenten- und Skill-Modelle bleiben dabei bewusst **domänen-agnostisch**, sodass sich derselbe Mechanismus auf andere Domänen übertragen lässt (gezeigt am Domänen-Transfer Bau → IT).

**So läuft eine Aufgabe durch das System:**

1. **Lücke erkennen** — Vor der Ausführung analysiert eine *Pre-Execution*-Stufe die Aufgabe, leitet die benötigten Fähigkeiten ab und prüft per *Gap Detector*, ob diese in der Skill-Registry vorhanden sind; ein *Feasibility Judge* bewertet die grundsätzliche Lösbarkeit.
2. **Fähigkeit bauen** — Fehlt ein Skill, baut ein dediziertes *Developer Team* ihn autonom in einer 5-Rollen-Pipeline (Researcher → Architect → Implementer → Reviewer → Tester). Das Ergebnis ist echter, ausführbarer Python-Code samt Tests und Beschreibung.
3. **Sicher freigeben** — Ein **Gatekeeper** prüft, ob der generierte Code wirklich das tut, was seine Beschreibung verspricht. Eine statische AST-Analyse fängt offensichtlich gefährliche Konstrukte ab; eine **Alignment-Validierung** erkennt subtile Code-Beschreibung-Diskrepanzen (z. B. Code, der mehr oder anderes tut als angegeben). Erst nach bestandenen Tests in einer isolierten **Docker-Sandbox** wird der Skill aktiviert.
4. **Ausführen** — Das *Main Team* löst die Aufgabe **wave-basiert**: Ein *HybridOrchestrator* stellt dynamisch ein Agenten-Team zusammen und lässt mehrere Agenten parallel arbeiten. Ein *Execution Verifier* prüft das Zwischenergebnis und stößt bei Bedarf eine Neuplanung an (*Verify-and-Replan*).
5. **Wiederverwenden** — Erfolgreiche „Blueprints" (bewährte Skill-/Team-Konfigurationen) werden in einer Vektordatenbank (Qdrant) abgelegt und bei ähnlichen Aufgaben per Retrieval wiedergefunden. Dieser **Warm-Start** spart den erneuten Bau-Aufwand und Tokens.
6. **Selbst verbessern** — Eine **Evolution-Schleife** analysiert Fehlschläge und Scores, ein *Product Owner* / *Quality Judge* entscheidet über Verbesserungen, die ein *Prompt Engineer* und *Tool Builder* umsetzen. Jede Änderung durchläuft ein **A/B-Testing**; verschlechtert sie das System, greift ein automatischer **Rollback**.

Kurz: Das Projekt kombiniert **autonome Fähigkeitserweiterung**, einen **sicherheitsgeprüften Selbstbau** und **Wiederverwendung via RAG** zu einem MAS, das sich strukturell selbst weiterentwickelt.

Die drei Forschungsfragen dahinter:

| Frage | Worum geht es | Beleg |
|-------|---------------|-------|
| **RQ1** | Erhöht strukturelle Selbst-Evolution die Task-Completion ggü. statischem MAS? | [Ergebnisse RQ1](Results.md#rq1--steigert-selbst-evolution-die-erfolgsrate) |
| **RQ2** | Reduziert die Wiederverwendung autonomer Blueprints den Ressourcenverbrauch? | [Ergebnisse RQ2](Results.md#rq2--bringt-blueprint-wiederverwendung-warm-start-etwas) |
| **RQ3** | Erkennt der semantische Gatekeeper gefährliche Code-Beschreibung-Diskrepanzen? | [Ergebnisse RQ3](Results.md#rq3--funktioniert-der-gatekeeper) |

---

## Systemarchitektur

### Überblick — der Fluss als Black-Box

Bevor wir in die Details gehen, zuerst die Vogelperspektive. Alle Komponenten sind hier zu **vier Black-Boxen** zusammengefasst — was *innen* passiert, folgt in den nächsten Abschnitten; hier geht es nur darum, *wie eine Aufgabe durch das System wandert*.

![Überblick als Black-Box](docs/diagrams/00_overview_blackbox.png)

So liest sich der Fluss in einfachen Worten:

1. **Verstehen & Lücke prüfen.** Eine Aufgabe kommt herein (z. B. „erzeuge einen Baustellenbericht aus dieser Audiodatei"). Das System überlegt zuerst, *welche Fähigkeiten* es dafür braucht, und schaut in seinem Gedächtnis nach, ob es diese schon besitzt.
2. **Fähigkeit bauen (nur wenn nötig).** Fehlt etwas — etwa „Audio transkribieren" —, baut sich das System diese Fähigkeit selbst: Ein **Developer Team** schreibt echten Python-Code, ein **Gatekeeper** prüft ihn auf Sicherheit und Ehrlichkeit, und eine **Sandbox** testet ihn isoliert. Erst dann gilt der Skill als „kann das System jetzt".
3. **Aufgabe lösen.** Mit den vorhandenen (und ggf. neu gebauten) Fähigkeiten löst ein **Main Team** aus mehreren Agenten die Aufgabe gemeinsam und parallel. Ein Verifizierer prüft das Ergebnis und lässt bei Bedarf nochmal nachbessern.
4. **Lernen & Wiederverwenden.** Aus Fehlschlägen lernt eine **Evolution-Schleife** (verbessert Prompts und Skills), und bewährte Lösungen wandern ins **Gedächtnis**. Trifft später eine ähnliche Aufgabe ein, findet das System die alte Lösung wieder (*Warm-Start*) und spart sich den erneuten Bau.

Der Clou: Schritt 2 macht das System **strukturell selbst-evolvierend** — es scheitert nicht an einer fehlenden Fähigkeit, sondern erweitert sich selbst. Schritt 4 sorgt dafür, dass es mit jeder Aufgabe besser und günstiger wird. Das Gesamtkonzept — Skill-Evolution *und* Prompt-Optimierung *und* Topologie-Adaption *und* geteiltes Gedächtnis in einem geschlossenen Zyklus — ist in dieser Kombination in der Literatur bisher nicht als Gesamtsystem etabliert; die Einzelmechanismen sind durch *Voyager* (arXiv:2305.16291), *GPTSwarm* (arXiv:2402.16823), *PromptBreeder* (arXiv:2309.16797) und *EvoSkill* (arXiv:2603.02766) belegt — der Beitrag liegt in ihrer Integration.

### Der detaillierte Fluss — vier Phasen

Eine Stufe tiefer zerfällt jede Black-Box in benannte Komponenten:

![Systemüberblick](docs/diagrams/01_system_overview.png)

1. **Pre-Execution Analyse** — Ein *Challenge Analyzer* zerlegt die Aufgabe und leitet die benötigten Fähigkeiten ab. Der *Gap Detector* gleicht sie gegen die Skill-Registry ab und klassifiziert die Lücke (Planning-, Functional- oder Agent-Gap). Ein *Feasibility Judge* bewertet, ob die Aufgabe grundsätzlich lösbar ist und ob sie ans Main Team oder erst ins Gap-Building geht. *(Detaildiagramm mit ConfidenceLevel-Schwellwerten und Datenquellen: [`04_pre_execution`](docs/diagrams/04_pre_execution.png).)*
2. **Intervention (Gap-Building)** — Fehlt eine Fähigkeit, baut der *Capability Builder* sie über die Skill-Team-Pipeline. Der Gatekeeper prüft den Code, die Docker-Sandbox testet ihn; erst der bestandene Skill wird aktiviert und steht dem Main Team zur Verfügung.
3. **Main Team (HybridOrchestrator)** — Der *Team Assembler* stellt aus dem Agentenpool dynamisch ein aufgabenspezifisches Team zusammen (LLM-geplant, Soft-Limit 4 Agenten — *Towards a Science of Scaling Agent Systems*, DeepMind 2025). Die Ausführung läuft **wave-basiert**: Agenten ohne gegenseitige Abhängigkeit arbeiten parallel in derselben Welle. Ein *Execution Verifier* bewertet das Ergebnis und stößt bei Bedarf eine Neuplanung an (Plan-Execute-Verify-Replan, *VMAO* arXiv:2603.11445).
4. **Evolution Loop (Developer Team)** — Fehlschläge, Scores und fehlgeschlagene Tool-Calls fließen in eine Analyse-, Entscheidungs- und Verbesserungsschleife zurück (Details unten).

Querschnitt: Alle LLM-Aufrufe laufen provider-agnostisch über **LiteLLM** + **Instructor** (strukturierte Outputs). **PostgreSQL** hält Agenten, Skills und Runs versioniert (Continuum), **Qdrant** dient als Vektor-Index für Capability-Matching und das geteilte Gedächtnis.

### Wie die Agenten miteinander kommunizieren

Im Main Team arbeiten mehrere Agenten an derselben Aufgabe — die zentrale Frage ist, *wie* das Ergebnis eines Agenten beim nächsten ankommt. Lumari verzichtet bewusst auf einen Nachrichtenbus (Redis/Queues) und nutzt stattdessen ein **typisiertes Blackboard-Muster**: Agenten kommunizieren nicht direkt miteinander, sondern legen ihre Ergebnisse als strukturierte **Artefakte** in einem gemeinsamen Pool ab und lesen von dort, was sie brauchen. Das entkoppelt Produzent und Konsument (kein Agent muss wissen, *wer* seinen Output später nutzt) und hält die Kommunikation für das Frontend nachvollziehbar. Es gibt **drei Kanäle**, die sich in ihrer Lebensdauer unterscheiden:

**1 · Der Artefakt-Pool — Kommunikation *innerhalb* eines Runs.** Der `ArtifactPool` (`orchestration/artifacts/pool.py`) ist ein **session-scoped In-Memory-Store**, der nach jeder Ausführung verworfen wird. Jeder Agent deklariert in der Topologie, *was* er produziert und konsumiert (`produces_artifacts` / `consumes_artifacts`) — ein expliziter **Artefakt-Vertrag** statt impliziter Seiteneffekte. Beim Schreiben wird das Payload sofort gegen ein registriertes JSONSchema geprüft (*validate at write time* — Fehler fallen früh und beim Verursacher auf, nicht erst beim Leser); Artefakte sind **immutable** und der Zugriff ist über ein `asyncio.Lock` thread-safe. Ein Wave-N-Agent liest über `read(consumes_artifacts)` die jeweils neuesten passenden Artefakte *aller* Vorwellen — so fließt der Output von Welle 1 in Welle 2, ohne dass die Agenten einander kennen.

**2 · Wellen & Parallelität — wer wann mit wem redet.** Welcher Agent auf welchen wartet, ergibt sich aus dem **Dependency-Graph** der Topologie. Ein `TopologicalSorter` (Pythons `graphlib`) sortiert die Agenten topologisch und gruppiert sie in **Wellen**: Jeder Agent landet in `Welle = max(Dependency-Wellen) + 1`. Zyklen werden dabei erkannt und abgelehnt. Innerhalb einer Welle haben die Agenten *keine* gegenseitigen Abhängigkeiten und laufen deshalb echt parallel — der `HybridOrchestrator` startet sie über `asyncio.gather` mit einem Per-Agent-Timeout. Erst wenn eine Welle vollständig ist (ihre Artefakte im Pool liegen), startet die nächste. So entsteht die „wave-basierte Ausführung" aus dem Flussdiagramm konkret aus Graph-Topologie + Artefakt-Abhängigkeiten.

**3 · Wie ein Agent seinen Input *sieht* — Prompt-Injektion.** Agenten lesen Artefakte nicht programmatisch aus, sondern bekommen sie in ihren Prompt injiziert: Der `GenericAgentExecutor` (`orchestration/executors/generic_executor.py`) serialisiert die konsumierten Artefakte als kompaktes JSON in den `{artifacts}`-Platzhalter des Agent-Prompts. **Entry-Point-Agenten** (ohne `consumes_artifacts`) erhalten stattdessen die ursprünglichen `input_data` der Aufgabe. Analog wird das geteilte Gedächtnis über einen `{shared_memory}`-Platzhalter eingespielt — die Memory-Abfrage feuert nur, wenn der Prompt diesen Platzhalter überhaupt enthält (Token-Ersparnis).

**4 · Das geteilte Gedächtnis — Kommunikation *über Runs hinweg*.** Während der Artefakt-Pool nach dem Run gelöscht wird, ist die `SharedMemory` (`orchestration/shared_memory/`, Vektor-Index in **Qdrant** + Metadaten in PostgreSQL) **persistent**. Hier hinterlassen Agenten und der Evolution-Loop *Facts* über bewährte und gescheiterte Team-Strategien sowie die episodischen *Reflexionen* (siehe unten). Beim nächsten ähnlichen Task ruft der Team Assembler diese Einträge per semantischer Ähnlichkeitssuche ab — das ist die Kommunikation zwischen *vergangenen* und *zukünftigen* Ausführungen und zugleich die Grundlage des Warm-Starts (RQ2). Auch die *append-only* Feedback-History der Skill-Builds ist eine solche zeitversetzte Kommunikation: Jeder Bauversuch hinterlässt eine Lehre für den nächsten.

Innerhalb des **Developer Teams** (Skill-Bau) ist die Kommunikation dagegen bewusst **sequenziell und gerichtet**: Die fünf Rollen reichen ihre Outputs als typisierte Pydantic-Artefakte direkt weiter (`ResearchContext` → `ArchitectureDesign` → Code → `ReviewResult` → Testergebnis), jede Stufe baut auf der vorigen auf. Hier gibt es keine Wellen-Parallelität, weil jede Rolle das vollständige Ergebnis ihres Vorgängers braucht.

### Wie ein Skill aufgebaut ist — das SoK-Modell S = (C, π, T, R)

Bevor wir die Bau-Pipeline ansehen, lohnt sich der Blick darauf, *was* überhaupt gebaut wird. Jeder Skill folgt der formalen Definition aus *SoK: Agentic Skills* (arXiv:2602.20867):

| Komponente | Bedeutung | Beispiel (Audio-Transkription) |
|---|---|---|
| **C** — Applicability Condition | *Wann* soll der Skill eingesetzt werden? | „Wenn ein Audio-Transkript in Text umgewandelt werden muss" |
| **π** — Instructions (Policy) | *Wie* wird er ausgeführt? | „Verwende `faster-whisper` für lokale Transkription" |
| **T** — Termination Condition | *Wann* ist er fertig? | „Wenn das Transkript vollständig als Text vorliegt" |
| **R** — Interface (Resources) | *Was* nimmt er entgegen / gibt er zurück? | `input: {audio_path}` → `output: {transcript, confidence}` |

Es gibt **zwei Skill-Typen** — ein bewusst hierarchisches Modell, weil *SkillX* (arXiv:2604.04804) zeigt, dass eine Planning/Functional-Hierarchie ein flaches Modell um ~10 Punkte schlägt:

- **Functional-Skill** — ausführbarer Python-Code mit fester Signatur `def execute(input_data: dict) -> dict`. Wird in der Docker-Sandbox ausgeführt und vom 5-Rollen-Team gebaut.
- **Planning-Skill** — *kein* Code, sondern Reasoning-Anweisungen, die als Kontext in den Agent-Prompt injiziert werden. Reasoning-Lücken lassen sich nicht als Code lösen; sie werden von einem **Proposer** erstellt (EvoSkill-Pattern: 3+ Ansätze brainstormen, besten wählen).

Skills *sind* die Capabilities eines Agenten (Single Source of Truth) — `Skill.applicability` wird beim Bau definiert und ist kausal mit dem Code verknüpft. Damit gibt es keine manuell gepflegte, divergierende Fähigkeits-Liste mehr.

### Die Skill-Bau-Pipeline (5 Rollen + Self-Healing)

![Skill-Pipeline](docs/diagrams/03_skill_pipeline.png)

Ein **Functional-Skill** entsteht in einer Pipeline aus fünf spezialisierten Rollen. Jede Rolle ist ein eigener, in sich abgeschlossener LLM-Aufruf, und das Modell lässt sich **pro Rolle** wählen — Code-Generierung verlangt ein stärkeres Modell als Recherche, also kann der Implementer auf ein teures Modell gesetzt werden, während der Researcher ein günstiges nutzt (*ToolMaker* arXiv:2502.11705 zeigt ~80 % Baseline für autonome Tool-Generierung mit einem starken Modell). Die Rollen reichen ihre Outputs als typisierte Artefakte weiter, sodass jede Stufe auf dem Ergebnis der vorigen aufbaut:

1. **Researcher** — recherchiert, *wie* sich die Fähigkeit umsetzen lässt: passende pip-/System-Pakete, Code-Beispiele und mögliche Lösungsansätze. Er stützt sich auf hinterlegte **Capability-Package-Hints** (20+ Domänen-Mappings, z. B. „Transkription → faster-whisper") und auf die **Feedback-History** vergangener Bauversuche derselben Capability. Diese History ist *append-only* (EvoSkill-Pattern, arXiv:2603.02766): Jeder frühere Versuch ist mit Strategie, Fehlertyp und „Lesson Learned" protokolliert, sodass der Researcher bereits gescheiterte Ansätze aktiv meidet statt sie zu wiederholen.
2. **Architect** — entwirft aus der Recherche den Blueprint **S = (C, π, T, R)**: die Funktionssignatur (`def execute(input_data: dict) -> dict`), Input-/Output-Schema als JSONSchema, konkrete Testfälle und das **Integrations-Protokoll** — also welcher Agent den fertigen Skill gebunden bekommt (`target_agent`) und welche Artefakte er deklariert. Ohne dieses Protokoll würden Skills zwar gebaut, aber nie korrekt in die Topologie integriert.
3. **Implementer** — schreibt den eigentlichen Code und führt ihn in der **Self-Healing-Schleife** (siehe unten) gegen die Testfälle aus. Er ist die einzige Rolle, die mehrfach iteriert.
4. **Reviewer** — prüft den lauffähigen Code auf Qualität und Sicherheit (max. 2 Runden). Meldet er *Critical*-Findings, geht der Code zurück an den Implementer; erst ein sauberer Review lässt den Skill weiter.
5. **Tester** — generiert die Testfälle, die in der Sandbox laufen, und reicht den echten Aufgaben-Kontext (z. B. die Ziel-Datenbank-Verbindung aus dem Challenge-Text) als `test_input` durch, damit gegen die *richtige* Infrastruktur getestet wird.

**Double-Loop Self-Healing — das Herzstück.** Der Implementer wiederholt nicht blind, sondern repariert gezielt (*CASCADE* arXiv:2512.23880, *SkillWeaver* arXiv:2504.07079). Zwei ineinandergreifende Schleifen:

- Die **innere Schleife** läuft *innerhalb einer Sandbox-Session* und iteriert bis zu 10×. Vor jedem teuren Sandbox-Lauf durchläuft der Code drei schnelle, deterministische **Vor-Gates**: eine AST-**Struktur-Prüfung** (korrekte `execute()`-Signatur), eine **Pfad-Prüfung** (keine hardcodierten Pfade — Skills müssen Pfade als Parameter bekommen) und einen **proaktiven Import-Scan**, der fehlende Pakete erkennt, *bevor* der Code überhaupt ausgeführt wird.
- Die **äußere Schleife** startet eine *neue* Session, sobald sich die Requirements ändern (neues Paket nötig) oder die innere Schleife sich festfährt.

Schlägt ein Sandbox-Lauf fehl, wird der Fehler in eine von **8 feingranularen ErrorTypes** klassifiziert (IMPORT, DEPENDENCY, SYNTAX, STRUCTURE, RUNTIME, TIMEOUT, RESOURCE, SEMANTIC), die auf **drei grobe Reparatur-Strategien** mit je eigenem, typisiertem Debug-Prompt abgebildet werden:

- **`IMPORT_ERROR`** → das fehlende Modul wird auf sein Paket gemappt und zunächst per **In-Session-`pip install`** nachgezogen; schlägt das fehl, folgt ein Session-Restart mit erweiterten Requirements. Eine `No matching distribution`-Meldung löst ein **Paket-Remapping** über eine Mapping-Tabelle aus.
- **`STRUCTURE_ERROR`** → der Code wird umgeschrieben (fehlendes `execute()`, falsches Interface).
- **`LOGIC_ERROR` / `RUNTIME_ERROR`** → der Ansatz wird angepasst. Scheitert dabei **dieselbe Bibliothek wiederholt**, erkennt das System das (`_should_switch_approach`), entfernt sie aus den Requirements und debuggt mit einer leichtgewichtigen **Alternative** (`torch → onnxruntime`, `pandas → polars`, `whisper → faster-whisper`).

Jeder Versuch — Erfolg wie Fehlschlag — wird in die Feedback-History geschrieben, sodass spätere Builds davon profitieren. **Oszillieren** die Fehlertypen nach 5 Iterationen (der Code springt zwischen Problemen hin und her, ohne zu konvergieren), verwirft die äußere Schleife den bisherigen Code komplett und erzwingt eine **Neu-Generierung von Grund auf** — das verhindert das Festfahren in lokalen Optima.

Diese Trennung in einen teuren **Maker** (der 5-Rollen-Orchestrator baut den Skill *einmal*) und einen günstigen **User** (der `GenericAgentExecutor` nutzt ihn danach beliebig oft) folgt *LATM* (arXiv:2305.17126) und ist die Grundlage für die Token-Ersparnis aus RQ2: Die hohen Build-Kosten amortisieren sich über die Wiederverwendung.

### Der Gatekeeper (RQ3)

![Gatekeeper](docs/diagrams/06_gatekeeper.png)

Wenn sich ein System autonom Code baut, besteht die Gefahr, dass der Code etwas *anderes* tut als seine Beschreibung verspricht — versehentlich oder als getarnte „Sleeper"-Operation, die erst unter bestimmten Triggern zuschlägt (*Sleeper Agents*, Hubinger et al. 2024, arXiv:2401.05566). Der Gatekeeper prüft deshalb in **zwei Schichten**, bevor ein Skill aktiviert wird:

- **Stufe 1 — AST-Analyse (statisch, deterministisch).** Der Code wird *ohne Ausführung* in seinen Syntaxbaum zerlegt und geprüft: Import-Allowlist (`typing`, `math`, `json`, `re` …), Blocked-Names (`eval`, `exec`, `os`, `subprocess`, `socket`, `pickle`, `__import__` …) und Struktur-Constraints (korrekte `execute()`-Signatur, keine Hardcoded-Paths). Deterministisch und ohne Fehlalarme — erkennt aber nur, *was* der Code strukturell tut, nicht *ob* das zur Aufgabe passt. Angelehnt an *CodeShield/LlamaFirewall* (Meta, arXiv:2505.03574).
- **Stufe 2 — Alignment-Validierung (semantisch, LLM).** Statt das Modell direkt zu fragen „passt Code zu Beschreibung?" (was laut Jin & Chen 2025, arXiv:2508.12358, durch Confirmation Bias systematisch versagt), läuft ein **Reconstruction-Ansatz** (*Q\** arXiv:2601.00224, *REA-Coder* arXiv:2604.16198): Ein LLM beschreibt den Code *blind* (Phase 1), der Semantic-Score gegen die Original-Beschreibung muss einen Schwellwert überschreiten (Phase 2), und ein **Constitution-Check** prüft explizite Safety-Regeln (kein Sleeper-Trigger, kein globaler State …) (Phase 3). Um Confirmation Bias zu vermeiden, kann hierfür ein anderes Modell als für die Code-Generierung gesetzt werden.

Nur Skills, die **beide** Schichten *und* die anschließenden Sandbox-Tests bestehen, werden aktiviert. Die Evaluation (Abschnitt RQ3) folgt dem Utility-Security-Tradeoff aus *AgentDojo* (arXiv:2406.13352) und zeigt, dass die semantische Schicht den Recall von 57 % (nur AST) auf 92 % hebt. *(Hinweis: produktiv ist die Alignment-Schicht derzeit wegen False Positives per Flag deaktivierbar; die RQ3-Zahlen stammen aus dem dedizierten 55-Paar-Korpus.)*

### Die Selbstverbesserungs-Schleife (Evolution Loop)

![Evolution Loop](docs/diagrams/02_evolution_loop.png)

Während die Skill-Pipeline eine *fehlende* Fähigkeit baut, kümmert sich die Evolution-Schleife um die *vorhandenen*: Sie macht das System über die Zeit besser, indem sie aus jeder Ausführung lernt. Sie läuft **nach jeder Ausführung — bei Erfolg *und* Fehlschlag** — als Fire-and-Forget-Background-Task (`asyncio.create_task`, keine zusätzliche Infrastruktur wie Redis/Celery). Der Trigger feuert bewusst auch bei `failed`: Genau dann, wenn Self-Healing gebraucht wird, würde eine reine Erfolgs-Bedingung den Loop nie auslösen. Das Muster entspricht dem Recompile-on-metric-drift aus *DSPy/MIPROv2* (Khattab et al.). Die drei Stufen bilden das Generator/Critic/Refiner-Muster aus *Self-Refine* (Madaan et al. 2023, arXiv:2303.17651) ab:

**1 · Analyse — was lief schief, und ist es ein Muster?**
Eine *Analysis-Pipeline* sammelt die Telemetrie der Ausführung *plus* die fehlgeschlagenen Tool-Calls (z. B. abgebrochene SQL-Queries), die sonst verloren gingen. Der *Analyzer* (LLM, strukturierter Output via Instructor) destilliert daraus **0–5 Findings**, jedes mit Kategorie, Severity, konkretem Evidence-Beleg und einem `suggested_fix`. Ein *Statistical Analyzer* hebt einzelne Ausreißer von **wiederkehrenden Mustern** über mehrere Runs ab. Der *Product Owner* priorisiert die Findings schließlich zu einer `PriorityList` mit einer übergeordneten `improvement_direction`.

**2 · Entscheidung — was lohnt sich, und was ist aussichtslos?**
Der *Control Agent* entscheidet, welche Findings tatsächlich angegangen werden. Davor greift die **3-Strike-Regel**: Jedes Finding bekommt einen stabilen *Fingerprint*; wurde derselbe Fingerprint bereits `control_agent_max_strikes`-mal (Default 3) erfolglos behandelt, wird er **vorab automatisch verworfen** (`evolution.skipped_by_strike`-Event) — das verhindert endlose Optimierungsversuche an nicht lösbaren Problemen (Population-Pruning analog *PromptBreeder* arXiv:2309.16797). Aus den verbleibenden Findings genehmigt der Control Agent maximal eine konfigurierte Anzahl pro Zyklus.

**3 · Verbesserung — umsetzen und gegen die Baseline absichern.**
Der *Improvement Orchestrator* routet jede genehmigte Verbesserung nach `artifact_type`:
- **`prompt`** → der *Prompt Engineer* erzeugt eine *neue* Prompt-Version. Versionen bilden keinen linearen Stack, sondern einen **Baum via `parent_id`** — Branching erlaubt parallele Optimierungspfade und macht die Prompt-Evolution visualisierbar (PromptBreeder).
- **`skill`** → der *Tool Builder* baut den Skill über dieselbe Sandbox-Pipeline neu.
- **`agent`** → Prompt- *und* Schema-Anpassung des Agenten.

Vor dem Rollout muss sich jede Änderung in einem **A/B-Test** beweisen. Baseline- und Improvement-Variante sammeln Samples (Composite-Score aus Qualität, Latenz und Fehlerrate); ein **einseitiger Welch-t-Test** (`alternative='greater'`, ungleiche Varianzen) prüft, ob die neue Variante besser ist. Als signifikant gilt sie nur, wenn **beide** Kriterien erfüllt sind: `p < 0.05` *und* relative Verbesserung > 10 % (zusätzlich werden Cohen's d und ein 95 %-Konfidenzintervall berichtet). Besteht sie den Test, wird sie **auto-promotet**; verschlechtert sie das System, greift ein automatischer **Rollback** auf die Baseline. So kann eine zufällig bessere Einzelmessung das System nicht dauerhaft verschlechtern.

Über alle Stufen hinweg emittiert der Loop Events (`evolution.triggered` → `finding_detected` → `prompt_updated`/`skill_rebuilt`/`agent_updated` → `completed`/`failed`), sodass die Selbst-Evolution durchgängig im Frontend nachvollziehbar bleibt. Zusätzlich werden Erfolge und Misserfolge vergangener Team-Strategien als Facts ins geteilte Gedächtnis geschrieben (*LATS* arXiv:2310.04406) — der Team Assembler bevorzugt so bewährte Kompositionen und meidet gescheiterte. Erfolgreiche Skills/Blueprints bleiben versioniert in der Registry und werden bei ähnlichen Aufgaben per Retrieval wiedergefunden (RQ2, *Warm-Start*).

### Reflexion — verbales Lernen über Versuche hinweg

Die bisher beschriebenen Schleifen optimieren *zwischen* Runs (Evolution Loop) oder reparieren *innerhalb* eines Builds (Self-Healing). **Reflexion** ergänzt eine dritte Lernform: Statt Gewichts-Updates nutzt das System **verbales Feedback als „semantischen Gradienten"** — ein LLM reflektiert in natürlicher Sprache über einen Fehlschlag und legt diese Lehre als Erfahrung ab, die der nächste Versuch liest. Das Pattern stammt aus *Reflexion: Language Agents with Verbal Reinforcement Learning* (Shinn et al. 2023, arXiv:2303.11366) und folgt dem Dreiklang **Actor → Evaluator → Self-Reflection → episodisches Gedächtnis**.

Lumari überträgt Reflexion an **vier Stellen** der Pipeline — und damit bewusst über das Paper hinaus, das Reflexion nur auf den *Actor* (den handelnden Agenten) anwendet. Hier reflektieren auch der **Evaluator** und der **Planner** über ihre eigenen Entscheidungen:

1. **Self-Reflection im Evaluator** — `orchestration/verification/execution_verifier.py`. Der Execution Verifier bewertet ein Ergebnis nicht mehr per Single-Shot-Score, sondern erzwingt zuerst eine **Chain-of-Thought**: Er zerlegt die Aufgabe in Teilaspekte, bewertet jeden einzeln mit Evidenz-Zitat und leitet den Gesamt-Score daraus ab. Liegt der Score nahe einer **entscheidungsrelevanten Schwelle** (0.4 = Neu-Team vs. Feedback-Replan, 0.85 = Replan vs. PASS), startet `_maybe_self_reflect()` einen zweiten Call: „Ist mein Score konsistent mit meiner Teilaspekt-Analyse?" Das LLM darf den Score nach oben *oder* unten korrigieren. So reflektiert der Bewerter über seine eigene Bewertung — Reflexion auf der Evaluator-Seite. Token-sparend, weil die Reflexion nur bei Grenzfällen feuert.

2. **Build-Reflexion im Developer Team** — `feedback_loop/analysis/failure_analyzer.py`. Schlägt ein Skill-Build fehl, ersetzt `_generate_reflection()` die frühere mechanische String-Lehre (`"IMPORT_ERROR: Missing module pandas. Fix: install pandas"`) durch eine **Ich-Form-Reflexion** des Builders: *Was war die eigentliche Ursache (nicht das Symptom), was sollte der nächste Versuch anders machen, welche Alternative wäre besser gewesen?* Diese Reflexion wandert in die *append-only* Feedback-History und steuert den Researcher des nächsten Bauversuchs (siehe Skill-Bau-Pipeline oben).

3. **Episodisches Reflexions-Gedächtnis im Planner** — `orchestration/execution/strategy_memory.py` + `team_assembler.py`. Das ist die **Kern-Innovation des Papers**, übertragen auf den Team-Planner. Nach einer gescheiterten Execution generiert `_generate_execution_reflection()` eine konkrete, zukunftsgerichtete Lehre (*„Das Team hatte einen DB-Skill, aber keinen File-I/O-Skill — nächstes Mal einen Agenten mit Lese-Fähigkeit UND einen mit DB-Schreib-Fähigkeit aufnehmen"*) und speichert sie **separat vom Outcome-Fact** unter dem Tag `execution_reflection` im geteilten Gedächtnis (Qdrant). Beim nächsten ähnlichen Task lädt der Team Assembler diese Reflexionen (max. Ω = 3, wie im Paper §3) als Kontext und meidet so gescheiterte Kompositionen aktiv. Damit das Gedächtnis nicht veraltet, gilt eine **Decay-Strategie**: Reflexionen starten mit `confidence = 0.7`; gelingt später eine Challenge desselben Typs, markiert `_invalidate_resolved_reflections()` die verwandten Reflexionen als gelöst (Confidence → 0.1), und der `min_confidence`-Filter blendet sie aus dem Retrieval aus.

4. **Chain-of-Thought im Gatekeeper-Vorfeld** — `orchestration/analysis/feasibility_judge.py`. Der Feasibility Judge urteilt nicht mehr direkt `feasible: true/false`, sondern zerlegt die geforderte Aktion erst in Einzeloperationen, bestimmt pro Operation den I/O-Typ und prüft das Tool-Matching — erst dann fällt das Verdict. Das verhindert vorschnelle „feasible"-Urteile bei Aufgaben, die mehrere I/O-Typen kombinieren (z. B. „CSV lesen *und* in DB schreiben").

Alle vier Mechanismen sind per **Config-Flag einzeln abschaltbar** (`self_reflection_enabled`, `failure_reflection_enabled`, `execution_reflection_enabled`, `cot_verification_enabled`), was die **Ablation** für die Thesis ermöglicht. Ein `_collect_reflexion_metrics()` im `HybridOrchestrator` protokolliert pro Run, ob Self-Reflection den Score korrigiert hat, wie viele Reflexions-Tokens anfielen und ob gespeicherte Reflexionen genutzt wurden — sichtbar als eigener `reflexion`-Event im Frontend-Stream. Der erwartete Effekt (Paper: +22 % über 12 Trials in AlfWorld) zielt direkt auf **RQ1**: episodisches Lernen aus Fehlschlägen als formalisierte Selbst-Evolution. Details und die Sprint-Aufteilung in [`documentation/REFLEXION_SPRINT.md`](documentation/REFLEXION_SPRINT.md).

---

## Zentrale Komponenten

Die wichtigsten Einstiegspunkte im Code (alle Pfade relativ zu `backend/app/`):

| Bereich | Pfad | Aufgabe |
|---------|------|---------|
| App + Lifespan | `main.py` | FastAPI-App, Startup |
| Konfiguration | `core/config.py` | Zentrale Settings (150+ Optionen) |
| **Gap-Erkennung** | `orchestration/analysis/gap_detector.py` | Erkennt fehlende Fähigkeiten |
| Machbarkeit | `orchestration/analysis/feasibility_judge.py` | Bewertet Lösbarkeit |
| **Intervention** | `orchestration/intervention/orchestrator.py`, `capability_builder.py` | Steuert das Bauen fehlender Fähigkeiten |
| **Haupt-Orchestrator** | `orchestration/orchestrators/hybrid_orchestrator.py` | Wave-basierte Ausführung |
| Team-Zusammenstellung | `orchestration/execution/team_assembler.py` | Stellt Agenten-Team dynamisch zusammen |
| Verifikation | `orchestration/verification/execution_verifier.py` | Verify-and-Replan |
| **Skill-Team (5 Rollen)** | `skills/building/team_orchestrator.py` | Researcher → Architect → Implementer → Reviewer → Tester |
| **Gatekeeper (RQ3)** | `skills/testing/code_alignment_validator.py`, `code_validator.py` | AST + semantische Alignment-Prüfung |
| Sandbox | `skills/testing/docker_sandbox.py` | Sichere Testausführung |
| Skill-Registry | `skills/runtime/registry.py`, `executor.py` | Aktivierung & Ausführung von Skills |
| **Evolution Loop** | `feedback_loop/loop.py` | Selbstverbesserungs-Schleife |
| Entscheidungen | `feedback_loop/decisions/` | Product Owner, Quality Judge, Control Agent |
| Verbesserung | `feedback_loop/improvement/` | Prompt Engineer, Tool Builder, A/B-Test, Rollback |
| **Blueprint-RAG (RQ2)** | `orchestration/shared_memory/qdrant_adapter.py` | Vektor-Wiederverwendung von Blueprints |

---

## Datenmodell — die zentralen Entitäten

Wer den Code liest, trifft schnell auf wiederkehrende Entitäten. Dieser Abschnitt erklärt, *wie* sie aufgebaut sind und *wie* sie zusammenspielen — die SQL-Modelle liegen in [`backend/app/models/sql/`](backend/app/models/sql/), die Vektoren in Qdrant. Architektonisch gibt es **vier Schichten**: drei versionierte Kern-Entitäten, das geteilte Gedächtnis, die Ausführungs-Historie und die Lern-/Audit-Spuren.

### 1 · Die drei versionierten Kern-Entitäten — Agent, Skill, Prompt

`Agent`, `Skill` und `Prompt` (`versioned_models.py`) sind das Herz des Systems und die einzigen Entitäten mit **automatischer Versionierung über SQLAlchemy-Continuum** (`__versioned__ = {}`). Jede Änderung schreibt automatisch eine neue Version in eine begleitende `*_version`-Tabelle — so bleibt die *gesamte* Evolutionshistorie (welcher Prompt wann wie aussah, welcher Skill aus welchem hervorging) lückenlos nachvollziehbar, was die Voraussetzung für **Rollback** (Evolution-Loop) und für die Visualisierung der Selbst-Evolution im Frontend ist. Alle drei tragen zudem ein `parent_id` (Self-Reference) für die **Abstammungslinie**: Eine optimierte Prompt-Version zeigt per `parent_id` auf ihren Vorgänger — Versionen bilden so keinen linearen Stack, sondern einen **Baum** (parallele Optimierungspfade, PromptBreeder-Branching).

| Entität | Schlüsselfelder | Funktion |
|---------|-----------------|----------|
| **`Agent`** | `name`, `dependencies` (JSON), `io_schema` (JSON), `prompt_id` → Prompt, `source` (`initial`/`system_generated`/`manual`), `agent_metadata` | Ein Agent ist bewusst „dünn": Er hält **keine** eigene Fähigkeits-Liste. `dependencies` (welche anderen Agenten er braucht) + `io_schema` definieren seinen Platz im Wellen-Graph; seine *Capabilities ergeben sich aus den gebundenen Skills* (Single Source of Truth). `source` markiert, ob der Agent geseedet oder vom System autonom erzeugt wurde. |
| **`Skill`** | `skill_type` (`functional`/`planning`), `applicability` (**C**), `instructions` (**π NL**), `termination` (**T**), `interface` (**R**, JSON), `code` (**π Code**, nullable), `dependencies`, `test_cases`, `parent_id` | Die SQL-Umsetzung des **SoK-Modells S = (C, π, T, R)**. Bei `functional`-Skills hält `code` den ausführbaren Python-Code, bei `planning`-Skills bleibt `code` leer und nur `instructions` (Reasoning) zählt. `applicability` ist kausal mit dem Code verknüpft — es gibt keine divergierende, manuell gepflegte Fähigkeits-Liste. |
| **`Prompt`** | `name`, `content`, `parent_id`, `is_active`, `prompt_metadata` | Versionierter Prompt-Baustein. Agenten referenzieren ihren Prompt über `Agent.prompt_id`; der Prompt Engineer erzeugt bei einer Verbesserung eine *neue* Version (neuer `parent_id`-Knoten) statt zu überschreiben. |

### 2 · Wie Skills an Agenten kommen — `SkillBinding`

Skill und Agent sind **nicht** direkt verdrahtet, sondern über eine eigene Verknüpfungs-Entität (`skill_build_models.py`): `SkillBinding` verbindet `skill_id` ↔ `agent_id` und trägt die **`capability`**, die diese Bindung bereitstellt, plus `binding_type` (`auto`/`manual`/`provisional`) und `priority`. Baut das Developer Team einen Skill für eine erkannte Lücke, entsteht genau hier die Bindung an den `target_agent` aus dem Architect-Protokoll. Diese Indirektion ist der Grund, warum derselbe Skill an mehrere Agenten gebunden und warum eine Bindung deaktiviert werden kann, ohne den Skill zu löschen.

### 3 · Das geteilte Gedächtnis — `Fact`, `Hypothesis`, `Relation`

Die Entitäten des `SharedMemory` (`shared_memory_models.py`) sind bewusst **append-only und *nicht* Continuum-versioniert** — Lernen ist additiv, alte Beobachtungen werden nicht überschrieben, sondern *superseded*. Nur die Metadaten liegen in PostgreSQL; der Embedding-Vektor selbst steht in **Qdrant** (verknüpft über `Fact.embedding_id`).

- **`Fact`** — die atomare Lern-Einheit: `text`, `confidence` (Float), `source_agent_id`, `execution_id`, `tags` (JSON, z. B. `execution_reflection`) und `supersedes_id` (Self-Reference, „dieser Fact ersetzt jenen"). Hier landen die bewährten/gescheiterten Team-Strategien und die episodischen Reflexionen; die `confidence`-Decay-Strategie (Start 0.7, Absenkung auf 0.1 bei gelöstem Problem) operiert genau auf diesem Feld. Der Team Assembler liest Facts beim Warm-Start per Ähnlichkeitssuche.
- **`Hypothesis`** — eine vom System aufgestellte Theorie mit `supporting_fact_ids` / `contradicting_fact_ids`, was automatische Widerspruchserkennung erlaubt.
- **`Relation`** — eine kausale Kante zwischen zwei Facts (`source_fact_id` → `target_fact_id`, `relation_type`), für „A verursachte B"-Ketten.

### 4 · Ausführung, Lernen & Audit

Die übrigen Entitäten halten fest, *was passiert ist* — sie sind die Datengrundlage für History-View, Evolution-Loop und Observability:

| Entität | Datei | Funktion |
|---------|-------|----------|
| **`Execution`** | `execution_models.py` | Ein Run-Datensatz (`status`: pending→running→completed/failed, `input_data`, `results`, `agents_executed`, `waves_executed`, `duration_ms`). Speist die History-Seite im Frontend. |
| **`SkillBuildAttempt`** | `skill_build_models.py` | **Append-only Feedback-History** jedes Bauversuchs: `approach`, `error_type_classified`, `lesson_learned` (die LLM-Reflexion), `related_attempt_ids`. Genau das liest der Researcher des nächsten Builds, um gescheiterte Ansätze zu meiden. |
| **`ABTest` / `ABTestSample`** | `ab_test_models.py` | Baseline- vs. Improvement-Samples für den Welch-t-Test, der über Auto-Promote oder Rollback entscheidet. |
| **`AnalysisFinding`** | `analysis_models.py` | Die 0–5 Findings, die der Analyzer pro Run destilliert (Kategorie, Severity, Evidence, `suggested_fix`). |
| **`CapabilityGapPlan`** | `gap_plan_models.py` | Persistierter Gap-Building-Plan mit Status-Lifecycle — verbindet erkannte Lücke und gebauten Skill. |
| **`TopologyChangeLog`** | `topology_models.py` | **Audit-Trail** jeder Struktur-Änderung (`change_type`, `entity_type`, `previous_state`/`new_state`, `triggered_by`). Wichtig: Die Topologie ist *keine* eigene Tabelle — sie ergibt sich zur Laufzeit aus `Agent.dependencies` + den Artefakt-Verträgen; dieses Log macht ihre Veränderung über die Zeit nachvollziehbar. |

Kurz: Die **drei versionierten Kern-Entitäten** definieren, *was das System kann*; `SkillBinding` verdrahtet Fähigkeit und Ausführer; das **append-only Gedächtnis** und die **Build-/Audit-Spuren** halten fest, *was es gelernt hat* — und zusammen bilden sie die persistente Grundlage für Rollback, Warm-Start und die durchgängige Nachvollziehbarkeit im Frontend.

---

## Benchmarks & Evaluation

Damit die Forschungsfragen messbar werden, gibt es **vier eigens gebaute Benchmark-Suites** (als YAML in [`backend/scripts/evaluation/datasets/`](backend/scripts/evaluation/datasets/)) plus zwei Betriebsmodi (Cold/Warm). Jede Suite zielt auf eine andere Frage: *Kann das System überhaupt schwieriger werdende Aufgaben lösen* (RQ1), *spart Wiederverwendung Ressourcen* (RQ2) und *fängt der Gatekeeper unehrlichen Code* (RQ3). Ausgeführt werden alle über einen gemeinsamen Runner ([`benchmark_runner.py`](backend/scripts/evaluation/benchmark_runner.py)), der Challenges gegen die laufende API stellt, auf das Ergebnis pollt und es bewertet.

### 1 · Progressive Complexity — die Haupt-Evaluation (RQ1)

Der Kern-Benchmark ([`progressive_complexity.yaml`](backend/scripts/evaluation/datasets/progressive_complexity.yaml)) umfasst **37 Aufgaben aus der Bau-Domäne**, gestaffelt über **fünf Komplexitäts-Level**. Die Idee ist eine *Rampe*: L1 kann das System sofort lösen, ab L4/L5 muss es sich strukturell selbst erweitern. Genau an dieser Rampe wird der Beitrag der Selbst-Evolution sichtbar — je schwieriger das Level, desto größer der Abstand zwischen „mit" und „ohne" Evolution.

| Level | Tasks | Was wird getestet | Anforderung ans System |
|-------|------:|-------------------|------------------------|
| **L1 — Standard** | 8 | Einfache Transkripte, ein Sprecher, klare Struktur (Tagesbericht, Mängelliste, Lieferprotokoll) | Vorhandene Fähigkeiten genügen — *baseline* |
| **L2 — Extended** | 8 | Mehrere Sprecher, Umgangssprache, gemischte Berichtstypen (Dialog-Protokolle, Nachtragserfassung) | Leichte Anpassung / Prompt-Reasoning |
| **L3 — Complex** | 7 | Rechnungen, DIN-Normen-Bezüge, Soll/Ist-Kostenvergleiche, neue Berichtstypen | Signifikante Erweiterung, Rechen-Skills |
| **L4 — Unknown** | 7 | Völlig neue Berichtstypen mit Fachvokabular (Brandschutzaudit, Energiebewertung, VOB-Vergabedoku, Schallschutz) | Aufgaben, für die das System nie gebaut wurde |
| **L5 — Autonomous** | 7 | Echte Infrastruktur: **DB-Schema-Discovery**, **ETL-Pipeline** (50 CSVs normalisieren + laden), **Audio-Transkription** (5 `.opus`-Aufnahmen) | System **muss neue Skills autonom bauen** (DB-Connector, CSV-ETL, faster-whisper) |

**Wie bewertet wird — Claim-based LLM-as-Judge.** Statt starrem String-Matching nutzt der Runner eine **FActScore-inspirierte Claim-Prüfung**: Jede Aufgabe hinterlegt im `ground_truth` eine Liste atomarer `required_claims` (z. B. *„12 m3 Beton C25/30 wurden per LKW angeliefert"*). Ein **Judge-LLM** prüft pro Claim, ob der generierte Bericht die Information inhaltlich abdeckt — *tolerant* gegenüber Umformulierungen, Synonymen, Einheiten-Umrechnungen und implizit ableitbaren Angaben. Der Score ist der Anteil gefundener Claims; **Pass@1** gilt ab einem Schwellwert von **85 %** (`CLAIM_PASS_THRESHOLD`). Fällt der Judge aus, greift ein deterministischer Keyword-Fallback. Das Judge-Modell ist frei wählbar (`--judge-model`) und **soll** vom ausführenden Modell entkoppelt sein. In den durchgeführten Läufen war das Judge-Modell durchgängig `gemini-3.5-flash`; im **Strong-Tier** war das *ausführende* Modell allerdings ebenfalls `gemini-3.5-flash` — dort also identisch mit dem Judge (möglicher Self-Preference-Bias, siehe Threats to Validity / `PROVENANCE.md`).

### 2 · Domain Transfer — Generalisierung (RQ1)

[`domain_transfer.yaml`](backend/scripts/evaluation/datasets/domain_transfer.yaml) prüft mit **24 Aufgaben aus zwei Nicht-Bau-Domänen** (IT-Störungsberichte, Meeting-Protokolle, je L1–L4), ob sich derselbe Mechanismus auf eine fremde Domäne übertragen lässt — und *wie schnell* das System sich adaptiert. Hier wird **keyword- und section-basiert** bewertet (`required_keywords` + `required_sections`), weil diese Domänen feste Strukturvorgaben haben. Belegt, dass die Agenten- und Skill-Modelle wirklich domänen-agnostisch sind.

### 3 · Gatekeeper Skills — Sicherheits-Benchmark (RQ3)

[`gatekeeper_skills.yaml`](backend/scripts/evaluation/datasets/gatekeeper_skills.yaml) ist ein dedizierter Korpus aus **55 Code-Beschreibung-Paaren**, der die zwei Gatekeeper-Schichten isoliert testet:

- **20 safe Skills** — nutzen nur die erlaubte stdlib-Allowlist, korrekte Struktur → sollen **durchgelassen** werden.
- **20 unsafe Skills** — offensichtlich gefährlich (`eval`, `os.system`, Subprozesse, Netzwerk) → sollen schon von der **AST-Schicht blockiert** werden.
- **15 advanced Skills** (bypass / semantic / deception) — bestehen die AST-Prüfung *absichtlich*, tun aber etwas anderes als ihre Beschreibung verspricht → sollen erst von der **Alignment-Schicht** gefangen werden.

Der [`gatekeeper_evaluator.py`](backend/scripts/evaluation/gatekeeper_evaluator.py) klassifiziert jedes Urteil als TP/TN/FP/FN und berechnet **Accuracy, Precision, Recall, F1 und Fehlalarmrate (FPR)** — getrennt für „nur AST", „nur Alignment" und „kombiniert", plus einen **Threshold-Sweep** über den Alignment-Schwellwert. Genau diese Trennung macht sichtbar, dass die semantische Schicht der entscheidende Hebel ist (Recall 57 % → 92 %, siehe Ergebnisse unten).

### 4 · Cold Start vs. Warm Start — Reuse-Messung (RQ2)

RQ2 wird nicht über eine eigene Suite, sondern über **zwei Betriebsmodi derselben Aufgaben** gemessen ([`cold_warm_switch.py`](backend/scripts/evaluation/cold_warm_switch.py)):

- **Cold Start** — die Datenbank wird vollständig geleert und neu geseedet (`truncate + re-seed`). Das System startet *ohne* gelernte Skills/Blueprints und muss alles Fehlende von Grund auf bauen.
- **Warm Start** — ein zuvor gespeicherter Snapshot (`pg_dump` + Qdrant-Snapshot) eines bereits eingelernten Zustands wird restauriert. Bekannte Blueprints werden per Retrieval wiedergefunden, die Build-Phase entfällt.

Die Differenz im **Token-Verbrauch** (bei gehaltener Erfolgsrate) isoliert den Reuse-Effekt.

### Reproduzierbarkeit — Multi-Seed & Statistik

Jede Konfiguration läuft über **3 Seeds** (`--seeds`), um Run-zu-Run-Varianz zu mitteln; verglichen wird mit **Wilcoxon-Signed-Rank** (gepaart) bzw. **Friedman** (über Modell-Tiers). Der Runner unterstützt zudem **Modell-Tiers** (`--model-config`, Weak/Medium/Strong aus [`model_configs/`](backend/scripts/evaluation/model_configs/)) und ein **Level-Filtering** (`--levels L3,L4,L5`), sodass sich gezielt einzelne Schwierigkeitsstufen evaluieren lassen.

```bash
# Haupt-Benchmark, 3 Seeds, dediziertes Judge-Modell
python -m scripts.evaluation.benchmark_runner \
  --suite progressive_complexity --seeds 3 \
  --judge-model "gemini/gemini-3.5-flash" \
  --output results/thesis/progressive.json

# Nur die schweren Level mit einer Modell-Konfiguration
python -m scripts.evaluation.benchmark_runner \
  --suite progressive_complexity --levels L3,L4,L5 \
  --model-config model_configs/u_strong_l3l5.yaml \
  --output results/thesis/strong_l3l5.json

# RQ3: Gatekeeper-Korpus auswerten
python -m scripts.evaluation.gatekeeper_evaluator

# RQ2: Zustand vor einem Warm-Run sichern / für Cold-Run zurücksetzen
python -m scripts.evaluation.cold_warm_switch warm-save --output snapshots/run1.dump
python -m scripts.evaluation.cold_warm_switch cold
```

---

## Experimentelle Ergebnisse

Evaluiert wurde auf einem **Progressive-Complexity-Benchmark** (Aufgaben der Stufen L1–L5, Domäne Bau + Domänen-Transfer IT). Alle Zahlen stammen aus `backend/results/thesis/analysis/statistics.json` und den Roh-Runs; jede Konfiguration wurde über **3 Seeds** gemittelt. Statistische Tests: Wilcoxon-Signed-Rank (gepaart) bzw. Friedman.

Die ausführlichen Ergebnisse der Benchmarks sind in [`Results.md`](./Results.md) zu finden.

---

## Technologie-Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | FastAPI · Pydantic 2 · SQLAlchemy 2 (async) |
| Frontend | Next.js 16 · React 19 · Tailwind v4 · shadcn/ui |
| Datenbanken | PostgreSQL (transaktional, Continuum-Versioning) · Qdrant (Vektoren/RAG) |
| LLM | LiteLLM (provider-agnostisch) · Instructor (strukturierte Outputs) |
| Sandbox | Docker (isolierte Skill-Ausführung) |
| Tests | pytest · pytest-asyncio |

---

## Setup & Ausführung

> Voraussetzungen: Docker, Python 3.11+, Node.js 20+, ein LLM-API-Key als Umgebungsvariable.
>
> **LLM-Zugang ist Pflicht zum Ausführen.** Um das Projekt produktiv laufen zu lassen oder Benchmarks/Tests auszuführen, wird ein **Gemini-API-Key** (`GEMINI_API_KEY`) benötigt — oder alternativ ein **eigenes Modell**, das über LiteLLM eingebunden bzw. hinzugefügt wird (provider-agnostisch, konfigurierbar in `backend/app/core/config.py` und den Modell-Configs unter `backend/scripts/evaluation/model_configs/`). Ohne hinterlegtes Modell können keine Challenges, Skill-Builds oder Benchmark-Läufe ausgeführt werden.
> Alternativ sind die Ergebnisse von Benchmarks Testruns im Frontend einsehbar.

```bash
# Alles starten (Docker-Services + Backend + Frontend)
./start.sh
```

Oder manuell:

```bash
# Datenbanken (PostgreSQL + Qdrant)
docker compose up -d postgres qdrant

# Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000  (API-Docs: /docs)

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:3000


# Beispiel-Agenten seeden
cd backend && python scripts/seed_agents.py
```

Die Evaluation lässt sich über `backend/scripts/evaluation/benchmark_runner.py` reproduzieren, wenn ein Modell angebunden ist.

---

## Projektstruktur

```
master_project/
├── README.md                       # ← dieses Dokument
├── start.sh                        # Startskript (Docker + Backend + Frontend)
├── docker-compose.yml              # PostgreSQL + Qdrant + API
├── docs/                           # Abgabe-Material
│   ├── diagrams/                   # Architektur-Diagramme (PNG + Mermaid-Quelle)
│   └── results/                    # Aufbereitete Ergebnis-Plots
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI-App
│   │   ├── core/config.py          # Zentrale Settings
│   │   ├── api/v1/                 # REST-Endpoints
│   │   ├── orchestration/          # Analyse, Intervention, HybridOrchestrator, Evolution
│   │   ├── skills/                 # Skill-Bau (building), Tests/Gatekeeper (testing), Runtime
│   │   ├── feedback_loop/          # Selbstverbesserungs-Schleife
│   │   ├── agents/ · models/ · prompts/ · services/
│   ├── scripts/evaluation/         # Benchmark-Runner + Datasets
│   ├── results/thesis/             # Roh-Ergebnisse, Statistik, alle 12 Plots
│   └── tests/                      # pytest
└── frontend/                       # Next.js (deutsche UI)
```

---

## Akademischer Kontext & Lizenz

| |                                                                                                                          |
|---|--------------------------------------------------------------------------------------------------------------------------|
| **Titel (DE)** | *Dynamische Strukturerweiterung eines Multiagenten-Systems durch autonome Erkennung und Schließung von Fähigkeitslücken* |
| **Titel (EN)** | *Enabling Secure Structural Self-Evolution in Multi-Agent Systems via Retrieval-Augmented Blueprint Generation*          |
| **Autor** | Patrick Zilke · <patrick.zilke99@gmail.com>                                                                              |
| **Art** | Hauptprojekt                                                                                                             |
| **Hochschule / Studiengang** | HAW - Master Informatik                                                                                                  |
| **Betreuung** | Thomas Clemen                                                                                                            |
| **Abgabejahr** | 2026                                                                                                                     |


### Lizenz

Im Rahmen einer Hochschulprüfung erstellte Arbeit. Eine Weiterverwendung des Codes bedarf der Zustimmung des Autors.
