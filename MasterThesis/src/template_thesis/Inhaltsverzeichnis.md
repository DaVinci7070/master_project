# Inhaltsverzeichnis (Arbeitsversion V3)

**Titel:** Selbstverbessernde Multi-Agenten-Systeme: Strukturelle Selbst-Evolution durch Retrieval-augmentierte Blueprint-Generierung
*Englisch: Self-Improving Multi-Agent Systems: Structural Self-Evolution via Retrieval-Augmented Blueprint Generation*

> **Stand:** 9-Kapitel-Struktur, an `Thesis_Overview_V2.md` und die real durchgeführten Experimente (`statistics.json`, Provenance-verifiziert) angeglichen. Änderungslog am Dateiende.

**Forschungsfragen (vorab definiert; als drei Dimensionen *einer* Sache framen — der Selbstverbesserung):**
- **RQ1 (Funktioniert es? / Effektivität):** Höhere Lösungsrate durch strukturelle Selbst-Evolution vs. statisches MAS?
- **RQ2 (Zu welchem Preis? / Effizienz):** Senkt Blueprint-Wiederverwendung den Ressourcenverbrauch bei Folgeaufgaben gleichen Typs? *(bedingt bestätigt — ehrlich so berichtet)*
- **RQ3 (Vertrauenswürdig? / Sicherheit):** Erkennt ein semantischer Gatekeeper gefährliche Code-Beschreibung-Diskrepanzen? *(Enabler, nicht im Titel — bewusst)*

---

## 1. Einleitung *(≈ 5 S.)*

| Sektion | Inhalt | Seiten |
|---------|--------|--------|
| **1.1 Motivation & Forschungslücke** | LLM-Agenten/MAS, Grenzen statischer MAS, Lücke Tool-Generierung vs. Struktur-Generierung | 2 |
| **1.2 Forschungsfragen & Beiträge** | RQ1–RQ3 (als 3 Dimensionen der Selbstverbesserung), 3–4 konkrete Beiträge (je 1:1 auf ein Experiment) | 1-2 |
| **1.3 Abgrenzung & Anwendungskontext** | Was wird NICHT behandelt; Use Case Baustellenberichte, domänen-agnostisches Design | 1 |
| **1.4 Aufbau der Arbeit** | Kapitelübersicht | 0.5 |

---

## 2. Grundlagen *(≈ 9 S.)*

**Regel:** Nur Konzepte (von anderen entwickelt), die der Leser für spätere Entwurfsentscheidungen braucht — kein Lehrbuch. Konkrete Werkzeuge → Kapitel 5.

| Sektion | Inhalt | Seiten |
|---------|--------|--------|
| **2.1 Große Sprachmodelle & LLM-basierte Agenten** | Relevante Eigenschaften (Nichtdeterminismus→Seeds, Kontextfenster→Memory, strukturierte Ausgaben→Tool-Calling, Halluzination→Gatekeeper); ReAct, Reasoning, Werkzeug-Nutzung | 2 |
| **2.2 Multi-Agenten-Systeme** | Architekturen, Koordination, Topologien | 1-2 |
| **2.3 Retrieval-Augmented Generation** | Embeddings, Vektor-Suche, Chunking | 1-2 |
| **2.4 Agenten-Gedächtnissysteme** | Short/Long-term, episodisch/semantisch, External Memory | 1-2 |
| **2.5 Skill-Formalismus (SoK: S = (C, π, T, R))** | Formale Skill-Definition als Grundlage | 1 |
| **2.6 Sicherheit in KI-Systemen** | Prompt Injection, Adversarial Attacks, Sandboxing, statische Code-Analyse | 1-2 |

---

## 3. Verwandte Arbeiten *(≤ 10 S.)*

| Sektion | Inhalt | Seiten |
|---------|--------|--------|
| **3.1 Selbst-evolvierende KI-Systeme** | EvolveR, Multi-Agent Evolve, CoMAS, SEMAF — *Fazit: nur Verhaltens-, keine Struktur-Evolution* | 2 |
| **3.2 Skill- & Werkzeug-Generierung** | Voyager, LATM, ToolMaker — *Fazit: Skills/Tools, keine Topologie* | 1-2 |
| **3.3 Dynamische Orchestrierung & Topologie** | DyLAN, AgentOrchestra, GPTSwarm, ADAS — *Fazit: Auswahl/Topologie aus fixem Pool, keine Generierung* | 2 |
| **3.4 Prompt-Evolution & Blueprint-/Memory-Reuse** | PromptBreeder, Agentic RAG, G-Memory, ACON, IMA — *Fazit: Wissens-Retrieval, kein Architektur-Retrieval* | 1-2 |
| **3.5 Agenten-Sicherheit** | ASB, BadAgent/Prompt Infection, „Lying Tools" — *Fazit: Fokus externe Angriffe, nicht selbst-generierter Code* | 1-2 |
| **3.6 Statische MAS-Frameworks & Baseline-Auswahl** | Strands Agents SDK (AWS 2025) vs. AutoGen/CrewAI/LangGraph; **Strands = externe RQ1-Baseline** (Begründung: modell-agnostisch, SOTA, Feature-Parität außer Evolution) | 1 |
| **3.7 Vergleichende Analyse & Einordnung** | Feature-Matrix + Positionierung | 1 |

**Feature-Matrix** (Kriterien so, dass auch diese Arbeit Lücken zeigt):

| System | Struktur-Evolution | Blueprint-Memory | Security-Gate | Dyn. Generierung | Externer SOTA-Vergleich | Adversarial-robust |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|
| Voyager | teilw. | ✓ | ✗ | ✗ | — | ✗ |
| GPTSwarm / ADAS | teilw. | ✗ | ✗ | teilw. | — | ✗ |
| Strands SDK | ✗ | ✗ | ✗ | ✗ | — | ✗ |
| ASB | ✗ | ✗ | ✓ (Angriffe) | ✗ | — | ✓ |
| **Diese Arbeit** | **✓** | **✓** | **✓** | **✓** | **✓ (Strands)** | **✗ (offen)** |

---

## 4. Systementwurf *(≈ 20 S.)* — *(Anforderungen + Design gemerged; WAS & WARUM)*

| Sektion | Inhalt | Seiten |
|---------|--------|--------|
| **4.1 Anforderungen & Entwurfsziele** | Funktionale Anforderungen (Agent-/Skill-Generierung, Blueprint-Mgmt, Security-Validation, Task-Execution, Self-Improvement); Qualitätsziele (qualitativ, *keine* unbelegten NFR-Grenzwerte); Randbedingungen (Domänen-Agnostik, Async-first) | 3 |
| **4.2 Architektur-Überblick** | Fünf-Phasen-Pipeline (Pre-Execution → Gap Building → Ausführung → Verify-Adapt → Post-Execution), Zwei-Team-Design | 2-3 |
| **4.3 Aufgabenanalyse & Fähigkeitsabgleich** *(Pre-Execution)* | ChallengeAnalyzer, CapabilityMatcher, FeasibilityJudge; Routing CAN_DO / MAYBE / CANNOT_DO | 2 |
| **4.4 Autonomer Aufbau fehlender Fähigkeiten** *(Gap Building)* | InterventionOrchestrator, GapPlanExecutor, CapabilityBuilder, CapabilityInjector; fixe Gap-Plans | 2 |
| **4.5 Dynamische Teambildung & parallele Ausführung** *(Wave-Execution)* | LLM-Planner, DAG-Validierung, TopologyLoader, Waves, ArtifactPool | 2 |
| **4.6 Wissensspeicher & Wiederverwendung von Blueprints** *(Evolutionäres Gedächtnis)* | Blueprint-/Skill-Schema (SoK), Qdrant-Retrieval, StrategyMemory, Drei-Schichten-Memory (Working/Episodic/Semantic) | 3 |
| **4.7 Sicherheits-Gatekeeper für generierten Code** | AST-Analyse (statisch) · semantische Alignment-Prüfung (Code vs. Beschreibung, Threshold 0.7) · Docker-Sandbox · A/B-Test | 3-4 |
| **4.8 Iterative Ergebnisprüfung & -verbesserung** *(Verify-Adapt)* | ExecutionVerifier, Score-Schwellen (PASS ≥0.85 / REPLAN_FEEDBACK / REPLAN_NEW_TEAM / ESCALATE), Auto-Eskalation | 2 |
| **4.9 Selbstverbesserung aus Erfahrung** *(Evolution Loop)* | Telemetrie → Analyzer → Product Owner → Control Agent (3-Strike) → Improvement → A/B-Test; Agent-Promotion | 2 |
| **4.10 Entwurfsentscheidungen & Abwägungen** | Begründung (fixe Gap-Plans, Entry-Point-Only-Memory, Score-Threshold-Metrik) | 1-2 |

---

## 5. Implementierung *(≈ 10 S.)* — *(WIE konkret gebaut)*

| Sektion | Inhalt | Seiten |
|---------|--------|--------|
| **5.1 Technologie-Stack** | FastAPI/Python 3.12/asyncio · PostgreSQL (Continuum) + Qdrant · LiteLLM/Instructor · Docker | 2 |
| **5.2 Datenmodell** | 27 Tabellen: versionierte Artefakte (Prompt/Agent/Skill), Telemetrie, Shared Memory, Evolution | 1-2 |
| **5.3 Main-Team-Agenten** | Orchestrator; Domain-Agenten (transcript_analyzer … report_finalizer) | 2 |
| **5.4 Developer-Team-Agenten** | 6-Rollen-Skill-Team (Researcher→Architect→Implementer→Reviewer + Proposer/Tester); Product Owner, Control Agent, Tool Builder | 2 |
| **5.5 Blueprint-Generierung & Selbstheilung** | Code→Sandbox→Fehlerklassifikation→Retry; Double-Loop, Oszillations-Abbruch | 2 |
| **5.6 Gatekeeper-Implementierung** | AST-Blocklist + Alignment-Prompt + Sandbox-Gates (Code-Walkthrough) | 1-2 |
| **5.7 Anwendungsfall-Konfiguration: Baustellenberichte** | Domänenspezifische Konfiguration ohne Schema-Änderung | 1 |

---

## 6. Evaluation *(≈ 22 S.)* — *(Methodik + Ergebnisse gemerged; Methodik vorn, dann pro Experiment Design + Ergebnis)*

| Sektion | Inhalt | Seiten |
|---------|--------|--------|
| **6.1 Forschungsfragen & Hypothesen** | RQ1–RQ3 operationalisiert, falsifizierbar (inkl. Vorhersage RQ2 build-anteilsabhängig) | 1-2 |
| **6.2 Versuchsaufbau** | Modelle/Tiers (Gemini 2.0=Weak, 2.5=Strong, Medium); Seeds (3, Bau 6); Reproduzierbarkeit (Config-IDs, Feature-Flags, Versionierung) | 1-2 |
| **6.3 Datensätze, Metriken & statistische Verfahren** | Progressive-Complexity-Benchmark (37 Tasks, L1–L5); Gatekeeper-Korpus (55 Paare, 35 gefährlich + 20 sicher); **Metrik-Definition: „Pass@1" = `P(score ≥ 0.85)`, einheitlich** (s. AP-1); Effizienz (Tokens/Task, Build-Skip-Rate, Kosten); Security (Precision/Recall/F1/FPR); **Wilcoxon/Friedman/Rank-Biserial** (Welch nur A/B-Loop); **Baselines**: interne Ablation (Evolution AUS) + externes **Strands SDK** (Auswahl-Begründung) | 4-5 |
| **6.4 Experiment 1 — Evolutions-Ablation & externer Vergleich gegen Strands (RQ1)** | Design + Ergebnisse (einheitliche per-Lauf-Metrik): Weak 77,8/57,1 % (Δ+20,6 pp, p=0.023, r=0.71), Strong 82,5/69,8 % (Δ+12,7 pp, p=0.026, r=0.85); Effekt wächst zu L5 (Weak +19→+33 pp); **Lumari vs. externes Strands-MAS** (gleiches Modell) → Mehrwert ggü. Stand der Technik | 4 |
| **6.5 Experiment 2 — Blueprint-Wiederverwendung (RQ2)** | Cold/Warm Bau: **kampagnen-sauber Warm +12,9 % teurer** (nicht −1,8 %, s. AP-12) bei +5,4 pp Qualität; Transfer (IT/Meeting): −16,2 % Tokens (robust), Erfolgs-„Gewinn" 25→31,9 % aber **schwellenabhängig** (kehrt bei τ=0.70, mean_score flach); *warum* Ersparnis in eingespielter Domäne verpufft (fixe Orchestrierung) | 4 |
| **6.6 Experiment 3 — Modellvergleich (Tiers)** | Token-Verbrauch über Tiers signifikant (Friedman p=0.025); Pareto Qualität/Kosten; Weak+Evolution stark pro Dollar | 2-3 |
| **6.7 Experiment 4 — Gatekeeper-Red-Team (RQ3)** | AST 57,1 % Recall / Alignment 87,6 % / **Kombiniert 92,4 % Recall, F1 0.915**; FPR 16,7 %; Schwellwert-Analyse & Bypass | 3 |
| **6.8 Zusammenfassung der Befunde** | Übersichtstabelle: RQ1 bestätigt, RQ2 **bedingt/teils widerlegt**, RQ3 bestätigt (mit Caveats) | 1-2 |

---

## 7. Diskussion *(≈ 9 S.)* — *(nach RQ strukturiert)*

| Sektion | Inhalt | Seiten |
|---------|--------|--------|
| **7.1 RQ1 — Strukturelle Selbst-Evolution vs. statisches MAS** | **bestätigt** — signifikant ggü. interner Ablation *und* externem Strands-Baseline; Effekt wächst mit Komplexität | 2 |
| **7.2 RQ2 — Blueprint-Wiederverwendung & Effizienz** | **bedingt** — Null/negativ in eingespielter Domäne, −16,2 % im Transfer; warum die Ersparnis verpufft + Plan-Cache als (noch nicht umgesetzter) Hebel | 2-3 |
| **7.3 RQ3 — Semantischer Gatekeeper** | **bestätigt** — semantische Schicht ist der Hebel (Recall 57→92 %); Judge-Zirkularität + FN-Kosten | 2 |
| **7.4 Einschränkungen & Bedrohungen der Validität** | In Prosa (vier Kategorien als Absatz-Struktur): interne (Confounds; Tokens+Qualität im Transfer gekoppelt) · externe (self-authored Benchmark, **ein** Anbieter; externe Referenz nur Strands) · Konstrukt (Pass@1-Definition, self-labeled Korpus, **Judge=System-Modell im Strong-Tier**) · statistische (Seeds, ungleiche n, kein Test für Cold/Warm-Δ); adversarielle Robustheit ungetestet | 3-4 |

---

## 8. Kritische Reflexion & Ausblick *(≈ 4 S.)*

> „Asche-aufs-Haupt"-Kapitel — nüchtern-selbstkritisch. Getrennt von 7.4/7.5 (die die *Studie* limitieren): hier Reflexion über das *Projekt* + Entwicklungen *nach* Redaktionsschluss.

| Sektion | Inhalt | Seiten |
|---------|--------|--------|
| **8.1 Methodische Reflexion** | Was ich heute anders machen würde: Pass@1 von Anfang an eindeutig definieren, mehr Seeds/Tasks, externe Baseline von Beginn an, Multi-Provider | 1 |
| **8.2 Nachträglich erkannte Entwurfsgrenzen** | Fixe Orchestrierung frisst Reuse-Ersparnis (→ Plan-Cache); Gatekeeper-Judge teilt evtl. den blinden Fleck des Builders | 0.5-1 |
| **8.3 Weiterentwicklungen seit Redaktionsschluss** | Dokumentierte, aber nach dem Stichtag liegende Hebel: Plan-Cache (`optimierung.md`), ReflexionMemory, MCP+A2A-Umbau, Gatekeeper-Upgrade | 1 |
| **8.4 Entwicklungen im Forschungsfeld** | ⚠️ **Vom Autor zu füllen:** relevante Arbeiten nach ~Anfang 2026 — keine erfundenen Quellen | 0.5-1 |
| **8.5 Zukünftige Arbeiten** | Externer SOTA-Vergleich, größerer/fremd-gelabelter Security-Korpus, Plan-Cache-Evaluation zur RQ2-Absicherung | 0.5-1 |

---

## 9. Fazit *(≈ 2 S.)*

| Sektion | Inhalt | Seiten |
|---------|--------|--------|
| **9.1 Zusammenfassung** | 1 Absatz pro Kapitel + ehrliche Bilanz der Beiträge (was eingelöst; RQ2 bedingt), eingewoben — Rückbezug zu 1.2 | 1-1.5 |
| **9.2 Schlusswort & Ausblick** | Einordnung; Future Work steht in 8.5 (keine Dopplung) | 0.5 |

---

## Anhänge

A. Blueprint-/Skill-Schema · B. Prompt-Templates · C. Gatekeeper-Regeln · D. Zusätzliche Ergebnisse (per-Level, alle Plots) · E. Gatekeeper-Korpus (55 Paare) · F. Requirements-Traceability & Config-IDs · G. Reproduzierbarkeit (Feature-Flags, Seeds, Modell-Settings)

---

## Seitenübersicht

| Kapitel | Seiten |
|---------|--------|
| 1. Einleitung | 5 |
| 2. Grundlagen | 9 |
| 3. Verwandte Arbeiten | ≤10 |
| 4. Systementwurf | 20 |
| 5. Implementierung | 10 |
| 6. Evaluation | 22 |
| 7. Diskussion | 9 |
| 8. Kritische Reflexion & Ausblick | 4 |
| 9. Fazit | 2 |
| **Gesamt (ohne Anhänge)** | **≈ 85–100** |

---

## Strukturübersicht

```
EINFÜHRUNG
├── 1. Einleitung            → Problem, RQs, Beiträge
GRUNDLAGEN
├── 2. Grundlagen            → Konzepte (LLM/Agenten, MAS, RAG, Memory, SoK, Security)
├── 3. Verwandte Arbeiten    → Stand der Forschung + Gap + Baseline-Auswahl
KERN
├── 4. Systementwurf         → WAS & WARUM (inkl. Anforderungen)
├── 5. Implementierung       → WIE gebaut
EVALUATION
├── 6. Evaluation            → Methodik + Ergebnisse (pro Experiment)
├── 7. Diskussion            → RQ1/RQ2/RQ3 + Threats to Validity
ABSCHLUSS
├── 8. Kritische Reflexion   → Was besser? Was kam seitdem?
└── 9. Fazit                 → Zusammenfassung
```

---

## Notizen & Entscheidungen

**Entschieden:**
- [x] Titel: *Selbstverbessernde Multi-Agenten-Systeme: Strukturelle Selbst-Evolution durch Retrieval-augmentierte Blueprint-Generierung* („Sichere" raus; RQ3 bleibt im Text).
- [x] Kapitelüberschriften **Deutsch**.
- [x] Kapitel **4 (Anforderungen) + 5 (Design) gemerged** → „Systementwurf".
- [x] Kapitel **7 (Methodik) + 8 (Ergebnisse) gemerged** → „Evaluation" (Methodik vorn, dann pro Experiment). *(kehrt die frühere „Split"-Entscheidung um)*
- [x] Einleitung auf 4 Unterkapitel gekürzt; Grundlagen auf 6 (2.1 = LLMs+Agenten gefaltet).
- [x] Systementwurf-Überschriften lesbar gemacht (Fachbegriff kursiv in Klammern).
- [x] Discussion nach RQ strukturiert.
- [x] Related Work auf ≤10 S. gedeckelt.
- [x] Strands als externe RQ1-Baseline (3.6 + 6.3 + 6.4).
- [x] Kapitel 8 (Kritische Reflexion) behalten.

**Noch offen (u. a. Prof-Fragen):**
- [ ] Externe Baseline für RQ1: Strands erwartet, oder genügt interne Ablation? *(Prof)*
- [ ] Evaluation als **ein** Kapitel (so) oder Methodik/Ergebnisse getrennt? *(Prof)*
- [ ] Kapitel 8 eigenes Kapitel oder in Diskussion/Ausblick? *(Prof)*
- [ ] Titel schon beim Prüfungsamt angemeldet? Falls ja: Änderung formal klären.
- [ ] Ethik-/Responsible-Disclosure-Absatz (autonom generierter + ausgeführter Code) — z. B. in 4.1 oder 7.5.

---

## Offene Arbeitspakete (vor Abgabe)

Priorisiert nach Notenwirkung (Ziel 14–15 Punkte). P0 = kritisch, P1 = wichtig, P2 = Feinschliff.

### P0 — kritisch
- [ ] **AP-1 „Pass@1" vereinheitlichen & Messinstrument validieren.** Provenance-Check: `statistics.json` rechnet **Pass@1 = Anteil Task-Läufe mit `score ≥ 0.85`** (verifiziert: DT-Cold 18/72=0.25). ABER drei Rechnungen existieren nebeneinander: Run-File-`pass` (strikt, DT=2,8 %), `statistics.json` (`P(score≥0.85)` → Results RQ2), `evolution_ablation`-Block (per-Task → Results RQ1, 61,9 % statt 77,8 %) → **RQ1 ≠ RQ2-Definition**. → EINE Definition (`P(score≥τ)`, τ=0.85 explizit) in **6.3**, alle Zahlen einheitlich neu rechnen (aus Bestandsdaten, **kein Re-Run**), τ-Sensitivität; LLM-Judge (`gemini-3.5-flash`, „toleranter Evaluator") auf 20–30 Tasks gegen Human-Label (Cohen's κ). *~2–3 Tage.*
- [ ] **AP-12 RQ2-Bau Pooling-Fix.** `U-WEAK-FULL` (RQ2-Cold) = 6 Seeds aus **zwei Kampagnen** (26.+28. Mai). „−1,8 %" ist Artefakt; kampagnen-sauber (28. Mai, je 3 Seeds) ist Warm **+12,9 % teurer**. → RQ2-Bau mit `cold_warm/cold` vs `cold_warm/warm` neu rechnen; 6-Seed-Pool nur für Tier-Vergleich; **6.5** korrigieren. Aus Bestandsdaten, **kein Re-Run**. *~0,5 Tag.*
- [ ] **AP-2 Externe Baseline für RQ1 (Strands SDK).** Strands als statisches MAS auf derselben 37-Task-Suite, gleiches Modell + gleiche Scoring-Pipeline. Scoped: 1 Tier, L1–L4, 3 Seeds. Alternativ Single-Agent-LLM als leichte Referenz. *~1 Woche, scoped ~5 Tage.*

### P1 — wichtig
- [ ] **AP-3 RQ2 sauber nachziehen (kein Goalpost-Moving).** Null/Negativ-Ergebnis Bau **behalten**; Plan-Cache implementieren → kontrollierter Follow-up, **mit** Signifikanztest. Bogen: Hypothese → widerlegt → Root-Cause → Intervention → bestätigt. *Plan-Cache ~3–5 Tage + Re-Run.*
- [ ] **AP-4 Statistische Power.** 5+ Seeds; per-Level nur als Trend+CI (~7 Tasks/Level); ≥1 Experiment auf **zweitem Anbieter**; Signifikanztest für RQ2-Token-Δ. *v. a. Rechenzeit.*
- [ ] **AP-5 RQ3 Construct-Validity.** Teil der 55 Fälle aus publiziertem Angriffsset (ASB) oder Zweit-Labeling (Inter-Rater); 1 adversarialer Test (Angreifer kennt Alignment-Prompt) → wird in **6.7** berichtet. *~2–3 Tage.*
- [ ] **AP-6 Related Work / Quellen auffüllen.** Lücken: (1) automatisiertes Agenten-Design (ADAS/AFlow/AgentSquare/DSPy), (2) Self-Evolving Agents 2024–25, (3) **LLM-as-Judge-Reliabilität** (Pflicht für AP-1), (4) Agent/Tool-Security (ASB/ToolMaker), (5) Agenten-Eval-Benchmarks. *`literatur-scout` kann BibTeX liefern.*

### P2 — Feinschliff
- [x] **AP-7** Anforderungen in Systementwurf (4.1) integriert (Kap. 4+5 gemerged). ✅
- [x] **AP-8** Discussion nach RQ strukturiert (7.1–7.5). ✅
- [ ] **AP-9** Front-Matter (HAW): Kurzzusammenfassung (DE) + Abstract (EN), Stichwörter/Keywords, Declaration of Authorship.
- [ ] **AP-10** Ethik-/Responsible-Disclosure-Absatz.
- [x] **AP-11** Kap. 8 (Kritische Reflexion) behalten. ✅

---

## Provenance-Check (durchgeführt Juli 2026)

Jede `statistics.json`-Config auf Run-Dateien gemappt, Zahlen nachgerechnet, Datum + Archiv geprüft.
- ✅ **Kein Archiv-Leck:** vollständig aus `results/thesis/` reproduzierbar; kanonische Runs 26.–29. Mai 2026 (Archiv April–22. Mai). 7/9 Configs exakt.
- 🔴 Pass@1 dreifach definiert (RQ1 ≠ RQ2) → **AP-1**.
- 🔴 RQ2-Bau-Cold poolt 2 Kampagnen; −1,8 % Artefakt (sauber: +12,9 % teurer) → **AP-12**.
- 🟡 **Judge = System-Modell im Strong-Tier** (`U-STRONG-L3L5`/`ABL-STRONG-EVO-OFF` = `3.5-flash`, Judge = `3.5-flash`) → Self-Preference-Bias; in **7.4** benennen. Weak-Tier sauber.
- 📌 Rohdaten inkl. Logs (`remaining_phases.log` etc. — 654 rekonstruierbare Berichte) einfrieren/committen.

---

### Änderungslog
- **V2:** Geister-Experimente (GAIA/SOTA/250) raus; reale Experimente + Statistik korrigiert; RQ2 differenziert verankert; NFR-Grenzwerte entfernt; Threats ausgebaut; Kritische-Reflexion-Kapitel + Strands.
- **V2.2:** Provenance-Check → kein Archiv-Leck; AP-1 verschärft; AP-12 (Pooling-Fix); Judge=System (Strong) dokumentiert.
- **V3 (dieser Durchgang):** Auf **9-Kapitel-Struktur** umgestellt — neuer Titel; Kap. 4+5 gemerged (Systementwurf), 7+8 gemerged (Evaluation); Einleitung → 4 Unterkap.; Grundlagen → 6 (2.1 gefaltet); Systementwurf-Überschriften lesbar; Discussion nach RQ; Related Work ≤10; Strands explizit. Alle AP-/Provenance-Referenzen auf neue Nummerierung remappt (Metriken 6.3, RQ2 6.5, Gatekeeper 6.7, Threats 7.4.3).

*Arbeitsversion V3 — Juli 2026, abgeglichen mit Thesis_Overview_V2.md, statistics.json (Provenance-verifiziert), Gliederungsentwurf für Prüfer und 14-Punkte-Referenz (Bardtke 2026).*
