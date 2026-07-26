# Forschungsplanung: Strukturelle Selbst-Evolution in Multi-Agenten-Systemen

**Expertenbewertung und Empfehlungen**
*Stand: März 2026*

---

## 1. Einordnung in den aktuellen Forschungsstand

### 1.1 Dein Projekt im Kontext aktueller Forschung

Dein Thesis-Konzept adressiert ein hochaktuelles Forschungsfeld. Die Analyse aktueller Literatur zeigt:

| Aspekt | Aktuelle Forschung | Dein Ansatz | Differenzierung |
|--------|-------------------|-------------|-----------------|
| **Self-Evolution** | EvolveR, SEMAF, CoMAS fokussieren auf Prompt/Tool-Evolution | Strukturelle Evolution (neue Agenten-Rollen + Team-Topologien) | **Neuartig**: Geht über Tool-Generation hinaus |
| **Orchestration** | DyLAN, AgentOrchestra mit statischen Agent-Pools | Dynamische Agent-Erstellung zur Laufzeit | **Neuartig**: Kombiniert Orchestration + Generation |
| **Memory/RAG** | Agentic RAG für Wissensabruf | Blueprint-Retrieval für Agenten-Konfigurationen | **Interessante Nische**: Meta-Learning für Agentenstruktur |
| **Security** | ASB Benchmark, BadAgent, Log-To-Leak | Mehrstufiger Gatekeeper mit Semantik-Check | **Relevant**: "Lying Tools" noch wenig erforscht |

**Wichtige Erkenntnis aus der Literatur:**
- [Multi-Agent Evolve (MAE)](https://openreview.net/forum?id=sknMpr8NWU) zeigt, dass Co-Evolution von Agenten (Proposer, Solver, Judge) durch RL optimiert werden kann
- [EvolveR](https://arxiv.org/abs/2510.16079) demonstriert "Offline Self-Distillation" - Extraktion abstrakter Prinzipien aus Trajektorien
- [Dynamic LLM-Agent Network (DyLAN)](https://openreview.net/forum?id=i43XCU54Br) konstruiert Task-spezifische Teams dynamisch

---

## 2. Kritische Analyse der aktuellen Forschungsfragen

### 2.1 Probleme mit den bestehenden RQs

| RQ | Problem | Empfehlung |
|----|---------|------------|
| **RQ1** (Effektivität) | Zu breit formuliert; "komplexe Aufgaben" ist vage; GAIA allein misst nicht strukturelle Anpassung | Präzisieren auf spezifische Fähigkeitslücken-Szenarien |
| **RQ2** (Effizienz) | Korrelation ≠ Kausalität; Blueprint Reuse könnte Artefakt des Aufgaben-Mixes sein | Kontrollierte Experimente mit definierten Wiederholungsmustern |
| **RQ3** (Sicherheit) | "Zuverlässig erkennen" ist binär; interessanter wäre Analyse der Erkennungsgrenzen | Trade-off zwischen False Positives/Negatives quantifizieren |

### 2.2 Fehlende Forschungsaspekte

1. **Emergente Spezialisierung**: Entwickeln Agenten natürliche Arbeitsteilung über Zeit?
2. **Transferlernen**: Können Blueprints domänenübergreifend wiederverwendet werden?
3. **Robustheit unter Drift**: Wie verhält sich das System bei veränderten Aufgabenverteilungen?
4. **Human-in-the-Loop**: Wann und wie sollte der Mensch einbezogen werden?

---

## 3. Verbesserte Forschungsfragen

### RQ1: Strukturelle Adaptivität (Primär)

> **Führt die Fähigkeit zur dynamischen Agenten-Generierung (Structural Self-Evolution) zu höheren Lösungsraten bei Aufgaben, die explizit neuartige Fähigkeiten erfordern, im Vergleich zu statischen MAS mit fixem Agenten-Pool?**

**Sub-Fragen:**
- **RQ1a**: Bei welchen Aufgabentypen (Reasoning, Tool-Use, Domain-Expertise) ist der Vorteil am größten?
- **RQ1b**: Wie viele Generationszyklen sind typischerweise nötig, bis ein effektiver Agent entsteht?
- **RQ1c**: Konvergiert die generierte Agenten-Population zu stabilen Spezialisierungen?

**Operationalisierung:**
- Metriken: Task Completion Rate stratifiziert nach "Capability Gap Severity"
- Kontrollvariablen: Modellgröße, Aufgabenkomplexität, verfügbare Tools

### RQ2: Blueprint-Evolution und Wissenstransfer

> **Wie entwickelt sich die semantische Diversität und Wiederverwendbarkeit von Agenten-Blueprints über kumulative Systemnutzung, und welche Faktoren beeinflussen erfolgreichen Blueprint-Transfer zwischen Domänen?**

**Sub-Fragen:**
- **RQ2a**: Welche Blueprint-Eigenschaften (Prompt-Struktur, Tool-Kombination) korrelieren mit hoher Wiederverwendung?
- **RQ2b**: Gibt es ein "Sättigungsniveau" ab dem neue Blueprints kaum noch entstehen?
- **RQ2c**: Wie ähnlich müssen Aufgaben sein, damit Blueprint-Retrieval effektiver ist als Neugenerierung?

**Operationalisierung:**
- Metriken: Embedding-Cluster-Analyse der Blueprint-Datenbank, Reuse-Rate over Time, Cross-Domain Transfer Success

### RQ3: Sicherheits-Effizienz-Trade-off

> **Wie beeinflusst die Stringenz des Gatekeeper-Mechanismus (AST + Semantik + Sandbox) das Verhältnis zwischen blockierten unsicheren Agenten und fälschlich abgewiesenen legitimen Innovationen?**

**Sub-Fragen:**
- **RQ3a**: Welche Gatekeeper-Stufe (AST, Semantik, Sandbox) hat das beste Precision/Recall-Verhältnis?
- **RQ3b**: Können adversariale Beispiele den Gatekeeper systematisch umgehen? (Red-Team-Analyse)
- **RQ3c**: Wie verändert sich das Innovationstempo bei unterschiedlichen Gatekeeper-Konfigurationen?

**Operationalisierung:**
- Metriken: Precision, Recall, F1 für Sicherheitserkennung; Innovation Rate (neue erfolgreiche Agenten pro Zeiteinheit)

### RQ4: Emergente Organisation (Optional/Explorativ)

> **Entwickeln sich in einem strukturell selbst-evolvierenden MAS emergente Organisations-patterns (Hierarchien, Spezialisierungen, Kooperationsstrukturen), und sind diese ähnlich zu menschlichen Organisationsformen?**

**Operationalisierung:**
- Qualitative Analyse der Agent-Interaktionsgraphen über Zeit
- Vergleich mit Organisationstheorien (z.B. Mintzberg-Strukturen)

---

## 4. Experimentelle Designs

### 4.1 Experiment 1: Capability Gap Challenge

**Ziel:** RQ1 validieren - Nachweis des Vorteils struktureller Evolution

**Design:**
```
┌─────────────────────────────────────────────────────────────────┐
│                    CAPABILITY GAP CHALLENGE                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Phase 1: Baseline Training                                      │
│  ─────────────────────────                                       │
│  • 100 Tasks aus bekannten Domänen (Bauberichte, Standard-RAG)   │
│  • Beide Systeme (Static vs. Dynamic) lernen auf gleichem Set    │
│                                                                  │
│  Phase 2: Capability Gap Injection                               │
│  ──────────────────────────────────                              │
│  • 50 Tasks mit NEUEN Anforderungen:                             │
│    - Neue Dokumentformate (z.B. BIM-Daten statt Transkripte)     │
│    - Neue Regelwerke (z.B. EU-Bauproduktenverordnung)            │
│    - Neue Analyseanforderungen (z.B. Risikopriorisierung)        │
│                                                                  │
│  Phase 3: Adaptation Window                                       │
│  ──────────────────────────                                       │
│  • Systeme erhalten 10 Beispiele der neuen Anforderungen         │
│  • Messung: Lernkurve über nachfolgende 40 Tasks                 │
│                                                                  │
│  Kontrollbedingungen:                                            │
│  ┌─────────────┬─────────────┬──────────────────────────┐       │
│  │ Condition   │ Agent-Gen.  │ Blueprint Memory         │       │
│  ├─────────────┼─────────────┼──────────────────────────┤       │
│  │ Baseline    │ ✗           │ ✗                        │       │
│  │ Memory Only │ ✗           │ ✓                        │       │
│  │ Gen Only    │ ✓           │ ✗                        │       │
│  │ Full System │ ✓           │ ✓                        │       │
│  └─────────────┴─────────────┴──────────────────────────┘       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Metriken:**
- Task Success Rate (TSR) pro Phase
- First-Attempt Success Rate (FSR)
- Time-to-Competence (Anzahl Tasks bis 80% TSR erreicht)
- Token-Verbrauch pro Task

**Stichprobengröße:**
- Mindestens 5 Durchläufe pro Condition (für statistische Power)
- Effect Size d > 0.5 angestrebt für praktische Relevanz

### 4.2 Experiment 2: Blueprint Evolution Longitudinal Study

**Ziel:** RQ2 validieren - Langzeitdynamik der Blueprint-Datenbank

**Design:**
```
┌─────────────────────────────────────────────────────────────────┐
│              BLUEPRINT EVOLUTION LONGITUDINAL STUDY              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Timeline: 500 Tasks über simulierte Zeitspanne                  │
│                                                                  │
│  Task-Verteilung (kontrolliert):                                 │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Tasks 1-100:   Domain A (Bauwesen) - 100%              │     │
│  │ Tasks 101-200: Domain A (70%) + Domain B (Energie) 30% │     │
│  │ Tasks 201-300: Domain A (40%) + B (40%) + C (Logistik) │     │
│  │ Tasks 301-400: Gleichverteilung A, B, C                │     │
│  │ Tasks 401-500: Domain D (komplett neu - Medizin)       │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  Messungen alle 50 Tasks:                                        │
│  • Blueprint-Datenbank Snapshot (Embeddings, Metriken)           │
│  • Cluster-Analyse (UMAP/t-SNE Visualisierung)                   │
│  • Reuse-Statistics pro Domain                                   │
│  • Semantic Diversity Index (mittlere paarweise Distanz)         │
│                                                                  │
│  Cross-Domain Transfer Test:                                     │
│  • Nach Task 400: 20 Domain-D-Tasks                              │
│  • Messe: Werden Domain-A/B/C Blueprints adaptiert?              │
│  • Vergleich: Transfer vs. De-novo Generation                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Analysen:**
- Blueprint Accumulation Curve (ähnlich Species Accumulation in Ökologie)
- Reuse-Rate vs. Semantic Similarity Regression
- Blueprint "Fitness Landscape" Visualisierung

### 4.3 Experiment 3: Gatekeeper Red-Team Evaluation

**Ziel:** RQ3 validieren - Sicherheitsgrenzen systematisch testen

**Design:**
```
┌─────────────────────────────────────────────────────────────────┐
│                GATEKEEPER RED-TEAM EVALUATION                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Test-Kategorien (inspiriert von Agent Security Bench):          │
│                                                                  │
│  Category 1: Direct Malicious Code                               │
│  ─────────────────────────────────                               │
│  • Offensichtlich schädlich (os.system, subprocess, eval)        │
│  • Erwartung: 100% Detection durch AST-Analyse                   │
│                                                                  │
│  Category 2: Obfuscated Malicious Code                           │
│  ──────────────────────────────────────                          │
│  • Encoded payloads (base64, rot13)                              │
│  • Dynamic code construction (chr() + exec())                    │
│  • Import aliasing (import os as mathematics)                    │
│                                                                  │
│  Category 3: Lying Tools (Semantic Mismatch)                     │
│  ─────────────────────────────────────────────                   │
│  • Harmlose Beschreibung + schädlicher Code                      │
│  • Korrekte Teilfunktion + versteckter Side-Effect               │
│  • Graduell abweichendes Verhalten (Edge-Case Exploitation)      │
│                                                                  │
│  Category 4: Capability Boundary Testing                         │
│  ─────────────────────────────────────────                       │
│  • Legitime aber ressourcenintensive Operationen                 │
│  • Grenzwertige Datenzugriffe                                    │
│  • Kaskadierung harmloser Operationen zu schädlichem Effekt      │
│                                                                  │
│  Category 5: Benign Code (False Positive Test)                   │
│  ────────────────────────────────────────────                    │
│  • Komplexer aber sicherer Code                                  │
│  • Ungewöhnliche aber legitime Patterns                          │
│  • Domain-spezifischer Code mit "verdächtigen" Keywords          │
│                                                                  │
│  Metriken pro Kategorie:                                         │
│  • True Positive Rate (Sensitivity)                              │
│  • True Negative Rate (Specificity)                              │
│  • Detection Latency (welche Stufe erkennt zuerst?)              │
│  • Bypass Rate (% erfolgreicher Umgehungen)                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Testset-Erstellung:**
- 50 Samples pro Kategorie = 250 Test-Cases
- Manuell kuratiert + LLM-generiert (Adversarial Generation)
- Ground Truth durch menschliche Experten annotiert

### 4.4 Experiment 4: GAIA Benchmark Ablation

**Ziel:** Vergleichbarkeit mit State-of-the-Art herstellen

**Design:**
```
┌─────────────────────────────────────────────────────────────────┐
│                   GAIA BENCHMARK ABLATION                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Benchmark: GAIA Level 1-3 (466 Tasks)                           │
│                                                                  │
│  Ablation Conditions:                                            │
│  ┌────────────────────┬───────────┬────────────┬──────────────┐ │
│  │ Condition          │ Evolution │ Memory     │ Gatekeeper   │ │
│  ├────────────────────┼───────────┼────────────┼──────────────┤ │
│  │ A: Vanilla LLM     │ ✗         │ ✗          │ ✗            │ │
│  │ B: Static MAS      │ ✗         │ ✗          │ ✗            │ │
│  │ C: +Memory         │ ✗         │ ✓          │ ✗            │ │
│  │ D: +Evolution      │ ✓         │ ✗          │ ✗            │ │
│  │ E: +Evolution+Mem  │ ✓         │ ✓          │ ✗            │ │
│  │ F: Full System     │ ✓         │ ✓          │ ✓            │ │
│  └────────────────────┴───────────┴────────────┴──────────────┘ │
│                                                                  │
│  Metriken:                                                       │
│  • Pass@1 pro Level (primary metric)                             │
│  • Token-Effizienz (Tokens/erfolgreicher Task)                   │
│  • Agenten-Diversität (unique Agenten pro Run)                   │
│  • Sicherheits-Overhead (Zeit durch Gatekeeper)                  │
│                                                                  │
│  Vergleich mit Leaderboard:                                      │
│  • h2oGPTe: 75% (current SOTA)                                   │
│  • GPT-5 high: 42% auf GAIA2                                     │
│  • Ziel: Kompetitive Performance + einzigartige Insights         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Wichtig:** GAIA allein reicht nicht für deine spezifischen Claims. Kombiniere mit domänenspezifischen Experiments (Bauberichte).

---

## 5. Methodische Empfehlungen

### 5.1 Statistische Analyse

| Test | Anwendung |
|------|-----------|
| **Welch's t-test** | Paarweiser Vergleich zweier Conditions (z.B. Static vs. Dynamic) |
| **ANOVA + Tukey HSD** | Vergleich mehrerer Ablation-Conditions |
| **Mixed-Effects Models** | Kontrolle für Task-Heterogenität und wiederholte Messungen |
| **Bootstrap CI** | Konfidenzintervalle bei kleinen Stichproben |
| **Effect Size (Cohen's d)** | Praktische Relevanz neben statistischer Signifikanz |

### 5.2 Reproduzierbarkeit

```yaml
# Empfohlene Dokumentation
experiment_config:
  random_seeds: [42, 123, 456, 789, 1011]  # 5 Seeds minimum
  llm_settings:
    model: "gemini-2.0-flash"  # oder vLLM local
    temperature: 0.7
    max_tokens: 4096
  blueprint_db:
    embedding_model: "text-embedding-3-large"
    similarity_threshold: 0.85
  gatekeeper:
    ast_strictness: "high"
    semantic_model: "claude-3-haiku"
    sandbox_timeout_ms: 5000
```

### 5.3 Limitations bereits jetzt dokumentieren

1. **Domain-Spezifität**: Bauberichte-Use-Case limitiert Generalisierbarkeit
2. **Compute-Kosten**: Vollständige Evolution kann teuer werden
3. **Evaluator Bias**: LLM-as-a-judge hat eigene Biases
4. **Temporal Validity**: Rapid LLM-Verbesserungen können Ergebnisse schnell überholen

---

## 6. Vorgeschlagene Thesis-Struktur

```
1. Introduction
   1.1 Motivation: Static MAS limitations
   1.2 Research Gap: Structural vs. behavioral evolution
   1.3 Research Questions & Contributions

2. Background & Related Work
   2.1 Multi-Agent Systems for LLMs
   2.2 Self-Improving AI Systems (EvolveR, MAE, CoMAS)
   2.3 Agent Security (ASB, Lying Tools, Prompt Injection)
   2.4 Retrieval-Augmented Generation for Agents

3. System Architecture
   3.1 The Architect: Dynamic Team Composition
   3.2 Evolutionary Memory: Blueprint Storage & Retrieval
   3.3 The Gatekeeper: Multi-Stage Validation
   3.4 Implementation Details

4. Experimental Design
   4.1 Research Questions & Hypotheses
   4.2 Experiment 1: Capability Gap Challenge
   4.3 Experiment 2: Blueprint Evolution Study
   4.4 Experiment 3: Gatekeeper Red-Team
   4.5 Experiment 4: GAIA Benchmark Ablation

5. Results
   5.1 Structural Evolution Effectiveness (RQ1)
   5.2 Blueprint Dynamics (RQ2)
   5.3 Security-Innovation Trade-off (RQ3)
   5.4 Ablation Analysis

6. Discussion
   6.1 Key Findings
   6.2 Emergent Behaviors
   6.3 Limitations
   6.4 Implications for MAS Design

7. Conclusion & Future Work
```

---

## 7. Potenzielle wissenschaftliche Beiträge

### 7.1 Neuartige Contributions

1. **Erste systematische Untersuchung** von struktureller (vs. nur verhaltensbasierter) Selbst-Evolution in MAS
2. **Blueprint-Retrieval-Mechanismus** als Alternative zu kompletter Neugenerierung
3. **"Lying Tools" Taxonomy** und Erkennungsstrategien
4. **Quantitative Trade-off-Analyse** zwischen Sicherheit und Innovationsgeschwindigkeit

### 7.2 Publikationspotenzial

| Venue | Fokus | Timeline |
|-------|-------|----------|
| **ACL/EMNLP Workshop** | Agenten-Sicherheit | Früh in der Arbeit |
| **AAMAS** | Multi-Agent Systems Architektur | Hauptarbeit |
| **NeurIPS Workshop** | Self-Improving AI | Erweiterung |

---

## 8. Kritische Fragen zur Selbstreflexion

Bevor du weiter planst, überlege:

1. **Scope**: Ist strukturelle Evolution + Sicherheit + RAG-Blueprint zu viel für eine Master-Arbeit?
   - Empfehlung: Fokussiere auf RQ1 + RQ3, RQ2 als "explorativ"

2. **Baseline-Fairness**: Ist dein "statisches" Baseline wirklich repräsentativ für SOTA?
   - Empfehlung: Implementiere AgentOrchestra oder ähnliches als echte Baseline

3. **Use-Case-Abhängigkeit**: Wie viel hängt von Bauberichte-Domäne ab?
   - Empfehlung: Mindestens ein zweiter Use-Case (z.B. Code-Review) für Generalisierung

4. **Evaluator-Objektivität**: Wer bewertet "Task Success"?
   - Empfehlung: Klare Rubrik + Inter-Rater-Reliability für menschliche Evaluation

---

## 9. Nächste Schritte

### Woche 1-2: Foundation
- [ ] Literatur-Review vertiefen (EvolveR, DyLAN, ASB Paper lesen)
- [ ] Forschungsfragen mit Betreuer finalisieren
- [ ] Use-Case #2 definieren

### Woche 3-4: Prototyp
- [ ] Minimal Viable Architect implementieren
- [ ] Blueprint-Schema in Qdrant aufsetzen
- [ ] Erste Gatekeeper-Stufe (AST) implementieren

### Woche 5-6: Experimente Design
- [ ] Test-Datasets erstellen (Capability Gap, Red-Team)
- [ ] Metriken-Pipeline aufsetzen
- [ ] Baseline-System implementieren

### Woche 7+: Durchführung
- [ ] Experiment 1 durchführen
- [ ] Iterieren basierend auf ersten Ergebnissen

---

## 10. Quellen und weiterführende Literatur

### Self-Evolving Agents
- [Awesome Self-Evolving Agents Survey](https://github.com/EvoAgentX/Awesome-Self-Evolving-Agents)
- [EvolveR: Self-Evolving LLM Agents](https://arxiv.org/abs/2510.16079)
- [Multi-Agent Evolve via Co-evolution](https://openreview.net/forum?id=sknMpr8NWU)
- [SEMAF: Self-Evolving Multi-Agent Framework](https://sciety.org/articles/activity/10.21203/rs.3.rs-8139402/v2)
- [Trajectory-Informed Memory Generation](https://arxiv.org/html/2603.10600)

### Agent Security
- [Agent Security Bench (ICLR 2025)](https://proceedings.iclr.cc/paper_files/paper/2025/file/5750f91d8fb9d5c02bd8ad2c3b44456b-Paper-Conference.pdf)
- [Prompt Injection Attacks Survey](https://www.mdpi.com/2078-2489/17/1/54)
- [Log-To-Leak: MCP Vulnerabilities](https://openreview.net/forum?id=UVgbFuXPaO)
- [LLM-based Agent Security Survey](https://www.sciencedirect.com/science/article/abs/pii/S1566253525010036)

### Orchestration & Team Composition
- [Multi-Agent Collaboration via Evolving Orchestration](https://arxiv.org/abs/2505.19591)
- [Dynamic LLM-Agent Network (DyLAN)](https://openreview.net/forum?id=i43XCU54Br)
- [AgentOrchestra](https://arxiv.org/html/2506.12508v1)
- [OSC: Cognitive Orchestration](https://aclanthology.org/2025.findings-emnlp.335/)

### Benchmarks & Evaluation
- [GAIA Benchmark](https://arxiv.org/abs/2311.12983)
- [GAIA2: Dynamic Environments](https://openreview.net/forum?id=9gw03JpKK4)
- [MASEval: System-Level Evaluation](https://arxiv.org/html/2603.08835)
- [Evaluation Survey (KDD 2025)](https://dl.acm.org/doi/10.1145/3711896.3736570)

### Agentic RAG
- [Agentic RAG Survey](https://arxiv.org/abs/2501.09136)
- [RAGOps](https://arxiv.org/html/2506.03401v1)

---

*Erstellt: März 2026*
*Basierend auf Analyse aktueller Forschungsliteratur und Web-Recherche*

Titel Ideen
"Strukturelle Selbst-Evolution in LLM-basierten Multi-Agenten-Systemen"
"Dynamische Selbst-Verbesserung in Multi-Agenten-Systemen durch autonome Agenten-Generierung"
