# Das Metrik-Problem — einfach erklärt (AP-1)

> **Stand: gegen Code (`model_comparison.py`, `benchmark_runner.py`), Ergebnisse (`statistics.json`), ALGORITHMUS.md und Thesis_Overview_V2.md abgeglichen.**

## Kurz gesagt
Unsere Erfolgs-Kennzahl heißt „Pass@1", ist aber **nicht einheitlich berechnet**. Die *Schwelle* (0,85) ist überall gleich und sogar sinnvoll gewählt — aber die **Art, wie über Seeds/Aufgaben zusammengerechnet wird, ist bei RQ1 anders als bei RQ2**. Dadurch liegen die Kopf-Zahlen auf verschiedenen Linealen. Zusätzlich zeigen die Roh-Läufe für eine Domäne eine ganz andere Zahl als die Auswertung.

## Zuerst die gute Nachricht: die Schwelle 0,85 ist begründet
0,85 ist **nicht willkürlich** — es ist die systemeigene „gut genug"-Schwelle (`verification_completeness_threshold = 0.85`), die das System auch im laufenden Betrieb nutzt, um „PASS" zu entscheiden (Verify-Adapt-Loop). „Erfolg = Score ≥ 0,85" ist also gut motiviert.

## Die zwei echten Probleme

### Problem A — gleiche Schwelle, andere Aggregation (RQ1 ≠ RQ2)
Beide zählen „Erfolg = Score ≥ 0,85", aber sie *fassen anders zusammen*:
- **RQ2 & Modellvergleich** (`compute_pass_at_1`): zählen **jeden einzelnen Lauf** (Seed × Aufgabe). → z. B. Weak-„an" = **77,8 %**.
- **RQ1-Ablation** (`evolution_ablation`): mittelt **erst pro Aufgabe über die 3 Seeds**, dann Schwelle. → dieselbe Konfiguration = **61,9 %**.

Beides ist für sich legitim — aber **RQ1 nutzt die eine, RQ2 die andere Rechnung.** Zwei verschiedene Lineale in einer Arbeit; die Zahlen sind nicht direkt vergleichbar.

### Problem B — Roh-Läufe vs. Auswertung (Faktor 10 bei einer Domäne)
Die Roh-Läufe speichern ein `pass`-Feld mit einer **anderen** Regel als die Auswertung:
- **Bau-Aufgaben** werden von einem **LLM-Judge** benotet (Regel: Score ≥ 0,85). → Roh-`pass` = Auswertung, passt zusammen.
- **Transfer-Aufgaben (IT/Meeting)** werden **deterministisch per Stichwort-Abgleich** benotet, und das Roh-`pass` verlangt *alle* Stichwörter (streng). → Roh = **2,8 %**, während die Auswertung (Score ≥ 0,85) **31,9 %** ergibt.

Wer die Roh-Dateien mit der Ergebnistabelle vergleicht, sieht also 2,8 % vs. 31,9 % für dieselbe Sache. Das muss aufgelöst/dokumentiert werden (welche Zahl gilt).

## Der ehrliche Haken bei RQ2-Transfer
Beim Transfer steigt die Erfolgsrate 25 % → 31,9 % (Score ≥ 0,85) — **aber der Durchschnitts-Score bleibt praktisch gleich** (0,642 kalt → 0,638 warm, minimal *niedriger*). Die „Verbesserung" ist also: *mehr Aufgaben überspringen knapp die 0,85-Hürde*, nicht *höhere Durchschnittsqualität*. Das heißt: bei einer strengeren Schwelle könnte der Effekt verschwinden. → **Schwellen-Sensitivität ist Pflicht**, sonst wirkt es fragil.

## Das Judge-Problem (nur bei Bau-Aufgaben)
Der LLM-Judge (`gemini-3.5-flash`) benotet nur die **Bau**-Aufgaben (Transfer ist deterministisch). Zwei Haken:
- Sein Prompt sagt, er soll **„toleranter Evaluator"** sein → Noten tendenziell zu gut.
- Im **Strong-Tier** ist das bewertete Modell dasselbe wie der Judge (beide `3.5-flash`) → **Selbst-Benotung**.

## Was wir fixen müssen
1. **Eine Definition + eine Aggregation** festlegen und *überall* verwenden. Empfehlung: „Erfolg = Score ≥ 0,85", **pro Lauf** (Seed × Aufgabe) — und RQ1 mit *derselben* Aggregation neu rechnen. Alles aus den vorhandenen Daten → **kein System-Neulauf**.
2. **Ehrlich umbenennen:** „Pass@1" → **„Erfolgsrate (Score ≥ 0,85)"** (Pass@1 ist der falsche Begriff, kommt aus der Code-Generierung).
3. **Schwellen-Sensitivität zeigen** (Zahlen bei 0,7 / 0,8 / 0,85) — besonders wichtig, weil der Transfer-Effekt schwellenabhängig ist.
4. **Notieren, dass 0,85 die systemeigene PASS-Schwelle ist** (begründet die Wahl).
5. **Roh vs. Auswertung auflösen:** dokumentieren, dass die Auswertung `Score ≥ 0,85` als maßgeblich nimmt (und warum das Roh-`pass` für Keyword-Aufgaben strenger ist).
6. **Judge prüfen:** ~20–30 Bau-Aufgaben selbst benoten, mit dem LLM-Judge vergleichen (Übereinstimmung berichten); „tolerant" streichen/begründen. **Selbst-Benotung (Strong-Tier)** und **Judge- vs. deterministische Bewertung über Domänen** ehrlich in Kap. 7.4 benennen.

## Die gute Nachricht
Alles außer der Judge-Handprüfung geht **aus den gespeicherten Daten** → **kein Neulauf**, nur neu rechnen (~2–3 Tage). Und es **schwächt die Arbeit nicht** — eine sauber definierte, einheitlich aggregierte Metrik mit Schwellen-Sensitivität ist genau das, was eine Top-Note ausmacht.

---

### Nebenbei: das verwandte Daten-Problem (AP-12)
Beim RQ2-Bau-Vergleich wurden zwei Messreihen **von verschiedenen Tagen** vermischt (26. + 28. Mai). Dadurch sind die berichteten „−1,8 % Ersparnis" ein **Artefakt** — sauber gerechnet (gleiche Messreihe, 28. Mai) ist der Warm-Start sogar **+12,9 % teurer**. Daten-Auswahl-Fehler, kein Metrik-Fehler — aus Bestandsdaten mitfixbar.

### Verifizierte Quellen
- `backend/scripts/evaluation/model_comparison.py` — `PASS_THRESHOLD = 0.85`; `compute_pass_at_1` (per Lauf, Z. 146/162); `evolution_ablation` (per Aufgabe gemittelt, Z. 377/398).
- `backend/scripts/evaluation/benchmark_runner.py` — `CLAIM_PASS_THRESHOLD = 0.85`, `evaluate_claims` (LLM-Judge, „toleranter Evaluator"), `evaluate_pass` (strikt, Keyword/Section).
- `backend/results/thesis/analysis/statistics.json` — DT-Cold 0.25 / DT-Warm 0.319 (= 18/72, 23/72 bei Score ≥ 0.85, verifiziert); mean_score DT 0.642 → 0.638.
- ALGORITHMUS.md / Thesis_Overview_V2.md — 0,85 als PASS-Schwelle konsistent, aber Pass@1 nirgends präzise definiert.
