# Gliederungsentwurf — Masterarbeit

**Titel:** Selbstverbessernde Multi-Agenten-Systeme: Strukturelle Selbst-Evolution durch Retrieval-augmentierte Blueprint-Generierung
*Englisch: Self-Improving Multi-Agent Systems: Structural Self-Evolution via Retrieval-Augmented Blueprint Generation*

**Kurz:** Ein strukturell selbst-evolvierendes Multi-Agenten-System (Lumari), das zur Laufzeit fehlende Fähigkeiten erkennt und autonom neue Skills/Agenten baut, Blueprints wiederverwendet und generierten Code vor Aktivierung sicherheitsprüft. Anwendungsfall: Baustellenberichte aus Audio-Transkripten. Die Experimente sind durchgeführt; RQ2 wurde dabei nur bedingt bestätigt (ehrlich so berichtet).

**Forschungsfragen (vorab definiert):**
- **RQ1 (Effektivität):** Führt strukturelle Selbst-Evolution zu höherer Lösungsrate als ein statisches MAS?
- **RQ2 (Effizienz):** Reduziert die Wiederverwendung generierter Blueprints den Ressourcenverbrauch bei Folgeaufgaben gleichen Typs?
- **RQ3 (Sicherheit):** Erkennt ein semantischer Gatekeeper gefährliche Diskrepanzen zwischen Code und Beschreibung zuverlässig?

---

## 1. Einleitung *(≈ 5 S.)*
- 1.1 Motivation & Forschungslücke
- 1.2 Forschungsfragen & Beiträge
- 1.3 Abgrenzung & Anwendungskontext
- 1.4 Aufbau der Arbeit

## 2. Grundlagen *(≈ 9 S.)*
- 2.1 Große Sprachmodelle & LLM-basierte Agenten *(relevante Eigenschaften: Nichtdeterminismus, Kontextfenster, strukturierte Ausgaben, Halluzination; ReAct, Reasoning, Werkzeug-Nutzung)*
- 2.2 Multi-Agenten-Systeme (Topologien, Koordination)
- 2.3 Retrieval-Augmented Generation (Embeddings, Vektor-Suche)
- 2.4 Agenten-Gedächtnissysteme (Memory)
- 2.5 Skill-Formalismus (SoK: S = (C, π, T, R))
- 2.6 Sicherheit in KI-Systemen (Prompt Injection, Sandboxing, statische Code-Analyse)

## 3. Verwandte Arbeiten *(≈ 10 S.)*
- 3.1 Selbst-evolvierende KI-Systeme
- 3.2 Skill- & Werkzeug-Generierung (Voyager, ToolMaker)
- 3.3 Dynamische Agenten-Orchestrierung & Topologie (GPTSwarm, ADAS)
- 3.4 Prompt-Evolution & Blueprint-/Memory-Wiederverwendung
- 3.5 Agenten-Sicherheit (ASB, „Lying Tools")
- 3.6 Statische MAS-Frameworks & Baseline-Auswahl (Strands Agents SDK vs. AutoGen / CrewAI / LangGraph)
- 3.7 Vergleichende Analyse & Einordnung

## 4. Systementwurf *(≈ 20 S.)*
- 4.1 Anforderungen & Entwurfsziele
- 4.2 Architektur-Überblick (Fünf-Phasen-Pipeline & Zwei-Team-Architektur)
- 4.3 Aufgabenanalyse & Fähigkeitsabgleich *(Pre-Execution)*
- 4.4 Autonomer Aufbau fehlender Fähigkeiten *(Gap Building)*
- 4.5 Dynamische Teambildung & parallele Ausführung *(Wave-Execution)*
- 4.6 Wissensspeicher & Wiederverwendung von Blueprints *(Evolutionäres Gedächtnis)*
- 4.7 Sicherheits-Gatekeeper für generierten Code *(AST-Analyse, semantische Prüfung, Sandbox)*
- 4.8 Iterative Ergebnisprüfung & -verbesserung *(Verify-Adapt)*
- 4.9 Selbstverbesserung aus Erfahrung *(Evolution Loop, A/B-Test)*
- 4.10 Entwurfsentscheidungen & Abwägungen

## 5. Implementierung *(≈ 10 S.)*
- 5.1 Technologie-Stack
- 5.2 Datenmodell
- 5.3 Main-Team-Agenten
- 5.4 Developer-Team-Agenten (6-Rollen-Skill-Team)
- 5.5 Blueprint-Generierung & Selbstheilung
- 5.6 Gatekeeper-Implementierung
- 5.7 Anwendungsfall-Konfiguration: Baustellenberichte

## 6. Evaluation *(≈ 22 S.)*
*(Methodik vorn, dann pro Experiment Design + Ergebnisse zusammen.)*
- 6.1 Forschungsfragen & Hypothesen
- 6.2 Versuchsaufbau (Modelle, Seeds, Reproduzierbarkeit)
- 6.3 Datensätze, Metriken & statistische Verfahren
- 6.4 Experiment 1 — Evolutions-Ablation & externer Vergleich gegen Strands SDK (RQ1)
- 6.5 Experiment 2 — Blueprint-Wiederverwendung: Cold/Warm & Domänen-Transfer (RQ2)
- 6.6 Experiment 3 — Modellvergleich (Tiers)
- 6.7 Experiment 4 — Gatekeeper-Red-Team (RQ3)
- 6.8 Zusammenfassung der Befunde

## 7. Diskussion *(≈ 9 S.)*
- 7.1 RQ1 — Strukturelle Selbst-Evolution vs. statisches MAS
- 7.2 RQ2 — Blueprint-Wiederverwendung & Effizienz
- 7.3 RQ3 — Semantischer Gatekeeper
- 7.4 Einschränkungen & Bedrohungen der Validität (interne / externe / Konstrukt- / statistische)

## 8. Kritische Reflexion & Ausblick *(≈ 4 S.)*
- 8.1 Methodische Reflexion
- 8.2 Nachträglich erkannte Entwurfsgrenzen
- 8.3 Weiterentwicklungen seit Redaktionsschluss
- 8.4 Entwicklungen im Forschungsfeld
- 8.5 Zukünftige Arbeiten

## 9. Fazit *(≈ 2 S.)*
- 9.1 Zusammenfassung (inkl. ehrlicher Bilanz der Beiträge)
- 9.2 Schlusswort & Ausblick

## Anhänge
- A. Blueprint-/Skill-Schema · B. Prompt-Templates · C. Gatekeeper-Regeln · D. Zusätzliche Ergebnisse · E. Gatekeeper-Korpus · F. Requirements-Traceability · G. Reproduzierbarkeit (Seeds, Konfigurationen)

---

*Gesamtumfang ohne Anhänge ≈ 85–100 Seiten.*

**Konkrete Fragen, zu denen ich gern Ihre Meinung hätte:**
1. **Externe Baseline für RQ1:** Ist ein Vergleich gegen ein etabliertes statisches MAS-Framework (z. B. Strands Agents SDK) erwartet, oder genügt die interne Ablation (Evolution AN vs. AUS)?
2. **Evaluation:** Als **ein** Kapitel mit Methodik + Ergebnissen (wie hier) — oder Methodik und Ergebnisse in zwei getrennten Kapiteln?
3. **Kapitel 8 (Kritische Reflexion):** als eigenes Kapitel sinnvoll — oder in Diskussion/Ausblick integriert?
