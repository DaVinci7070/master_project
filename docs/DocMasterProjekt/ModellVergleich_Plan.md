# Modellvergleich-Evaluationsplan

## Ziel

Systematischer Vergleich verschiedener Gemini-Modellstärken auf dem Lumari Multi-Agent-System.
Beantwortet die Forschungsfrage: *"Wie stark beeinflusst die LLM-Capability die Task-Completion-Rate eines selbst-evolvierenden MAS, und kompensiert strukturelle Selbst-Evolution schwächere Modelle?"*

---

## 1. Modell-Auswahl

### Getestete Modelle (3 Tiers)

| Tier | LiteLLM Model-ID | Generation | Input $/1M | Output $/1M | Charakter |
|------|-------------------|-----------|-----------|------------|-----------|
| **T-Weak** | `gemini/gemini-2.0-flash` | 2.0 | $0.10 | $0.40 | Schnell, günstig, begrenztes Reasoning |
| **T-Medium** | `gemini/gemini-2.5-flash` | 2.5 | $0.30 | $2.50 | Thinking-Modell, deutlich stärker |
| **T-Strong** | `gemini/gemini-3.5-flash` | 3.5 | $1.50 | $9.00 | Neustes Modell (Mai 2026), bestes Agentic/Coding |

### Begründung der Auswahl

- **T-Weak (2.0-flash)**: Aktuelles Fast-Modell im System → direkter Baseline-Vergleich
- **T-Medium (2.5-flash)**: Generationssprung + Thinking-Fähigkeit → "Was bringt Thinking?"
- **T-Strong (3.5-flash)**: Google I/O 2026, schlägt 3.1 Pro auf Agentic-Benchmarks → "Bestes Agentic-Modell"

### Designentscheidung: Alle Flash-Tier

Alle drei Modelle sind Flash-Varianten derselben Modellfamilie. Das eliminiert zwei potentielle Confounds:
- **Kein Latenz-Confound**: Pro-Modelle haben ~27s TTFT vs ~1-2s bei Flash → Timeouts würden nicht Capability messen, sondern Infrastruktur-Limits
- **Gleiche Architektur-Klasse**: Unterschiede reflektieren rein die Modell-Capability, nicht Dense-vs-MoE oder Flash-vs-Pro Architekturunterschiede

### Bewusst ausgeschlossen

| Modell | Grund |
|--------|-------|
| `gemini-2.0-flash-lite` | Zu schwach für sinnvolle Ergebnisse ab L3, spart nur $0.025/M vs flash |
| `gemini-2.5-pro` | Zwischen 2.5-flash und 3.5-flash, kein klarer Differenzierungspunkt |
| `gemini-3-flash-preview` | Aktuelles Produktionsmodell — wird als Mixed-Config separat betrachtet (siehe Limitation) |
| `gemini-3.1-pro-preview` | Stärkstes Reasoning-Modell, aber ~27s TTFT verursacht Timeout-Confounds in MAS. Auf Agentic-Benchmarks (MCP Atlas: 69.2%) schwächer als 3.5-flash (83.6%). Kosten ($12/1M Output) übersteigen Budget |
| `gemini-3.1-flash-lite` | Ähnlich wie 2.5-flash im Preissegment, weniger Daten verfügbar |

### Hinweis zum Produktionsmodell

Das aktuelle System nutzt eine **Mixed-Config** (gemini-2.0-flash für Research/CodeFix/General, gemini-3-flash-preview für Architecture/Implementation/Review/Validation). Diese Studie testet bewusst **uniforme Configs** (gleiches Modell für alle Rollen), um die reine Modell-Capability zu isolieren. Die Mixed-Config-Performance ist aus bestehenden Benchmark-Runs bekannt und dient als informeller Referenzpunkt.

---

## 2. Experimentelles Design

### 2.1 Variablen

| Typ | Variable | Ausprägungen |
|-----|----------|-------------|
| **Unabhängig** | Modell-Tier | T-Weak, T-Medium, T-Strong |
| **Unabhängig** | Evolution-Flag | enabled / disabled (nur für Ablation) |
| **Abhängig** | Pass@1 | Anteil bestandener Tasks (0.0–1.0) |
| **Abhängig** | Token-Verbrauch | Gesamttokens pro Run (Input + Output + Thinking) |
| **Abhängig** | Latenz | p50 und p95 Dauer pro Task (ms) |
| **Abhängig** | Kosten | Tatsächliche API-Kosten pro Run ($) |
| **Abhängig** | Skill-Reuse-Rate | Anteil wiederverwendeter Skills |
| **Kontrolliert** | Task-Suite | progressive_complexity (identische 37 Tasks) |
| **Kontrolliert** | System-State | Cold-Reset zwischen Seeds |
| **Kontrolliert** | Routing | Uniform (alle Rollen → gleiches Modell) |
| **Kontrolliert** | Judge-Modell | Festes Modell für LLM-as-Judge (gemini-3.5-flash), unabhängig vom getesteten Modell |

### 2.2 Run-Konfigurationen

#### Phase 1: Modell-Capability-Studie (Hauptexperiment)

Alle 7 LLM-Rollen (research, architecture, implementation, review, code_fix, semantic_validation, general) verwenden dasselbe Modell:

| Config-ID | Modell | Task-Levels | Tasks | Seeds | Mode |
|-----------|--------|-------------|-------|-------|------|
| `U-WEAK-FULL` | gemini-2.0-flash | L1–L5 | 37 | 3 | cold |
| `U-MEDIUM-L3L5` | gemini-2.5-flash | L3–L5 | 21 | 3 | cold |
| `U-STRONG-L3L5` | gemini-3.5-flash | L3–L5 | 21 | 3 | cold |

**Begründung Task-Level-Auswahl**:
- T-Weak bekommt L1-L5 komplett → zeigt Baseline auf allen Schwierigkeitsgraden
- T-Medium/Strong nur L3-L5 → L1/L2 sind zu einfach für Differenzierung, spart ~40% Kosten

#### Phase 2: Evolution-Ablation (2×2 Factorial)

Testet Interaktion zwischen Modell-Capability und Selbst-Evolution:

| Config-ID | Modell | Evolution | Task-Levels | Tasks | Seeds |
|-----------|--------|-----------|-------------|-------|-------|
| `ABL-WEAK-EVO-ON` | gemini-2.0-flash | ✅ enabled | L3–L5 | 21 | 3 |
| `ABL-WEAK-EVO-OFF` | gemini-2.0-flash | ❌ disabled | L3–L5 | 21 | 3 |
| `ABL-STRONG-EVO-ON` | gemini-3.5-flash | ✅ enabled | L3–L5 | 21 | 3 |
| `ABL-STRONG-EVO-OFF` | gemini-3.5-flash | ❌ disabled | L3–L5 | 21 | 3 |

**Datenwiederverwendung**:
- `ABL-STRONG-EVO-ON` = `U-STRONG-L3L5` → kein zusätzlicher Run nötig (identisch: cold, L3-L5, Evolution ON).
- `ABL-WEAK-EVO-ON` ist ein **eigener Run** (L3-L5 cold). Daten aus `U-WEAK-FULL` (L1-L5) sind NICHT wiederverwendbar, weil dort L1/L2 vor L3 laufen und das System durch Evolution Skills aufbaut, die L3+ Ergebnisse beeinflussen.

**3 zusätzliche Runs**: `ABL-WEAK-EVO-ON`, `ABL-WEAK-EVO-OFF`, `ABL-STRONG-EVO-OFF`.

**Hinweis zu gebündelten Flags**: Die Ablation schaltet `autonomous_evolution`, `shared_memory` und `skill_reuse` gemeinsam. Das misst den **kombinierten Effekt** des Evolution-Pakets, nicht einzelne Komponenten. Separate Ablation der Einzelflags wäre wissenschaftlich sauberer, überschreitet aber den Rahmen dieser Studie. → Limitation explizit in Thesis benennen.

### 2.3 Zusammenfassung Runs

| Phase | Neue Runs | Seeds | Geschätzte Kosten |
|-------|-----------|-------|-------------------|
| Phase 1 | 3 Configs | 3+3+3 | ~$10 |
| Phase 2 | 3 Configs (ABL-WEAK-ON, ABL-WEAK-OFF, ABL-STRONG-OFF) | 3+3+3 | ~$12 |
| **Gesamt** | **6 Configs** | **18 Runs** | **~$22** |

**Kostenabschätzung** (konservativ):
- T-Weak Runs (×9 Seeds gesamt): ~$3 — günstiges Modell, niedrige Token-Kosten
- T-Medium (×3): ~$7 — Thinking-Tokens erhöhen Output-Kosten
- T-Strong (×6: U-STRONG-L3L5 + ABL-STRONG-EVO-OFF): ~$12 — teures Modell, aber nur 6 Seeds

**Hinweis zu T-Strong Seed-Zählung**: U-STRONG-L3L5 (3) + ABL-STRONG-EVO-OFF (3) = 6 Seeds. ABL-STRONG-EVO-ON ist identisch mit U-STRONG-L3L5 → kein Extra-Run.

---

## 3. Metriken und Auswertung

### 3.1 Primäre Metriken

| Metrik | Beschreibung | Erhebung |
|--------|-------------|----------|
| **Pass@1** | Anteil Tasks mit Score ≥ 0.85 | Claim-based LLM-as-Judge (festes Judge-Modell) |
| **Token-Kosten ($)** | Tatsächliche API-Kosten (tokens × pricing) | Token-Counter im Runner |
| **Latenz (ms)** | End-to-End Dauer pro Task | Benchmark Runner Timestamps |
| **Quality/Cost Ratio** | Pass@1 / Kosten pro Run | Berechnet |

### 3.2 Sekundäre Metriken

| Metrik | Beschreibung |
|--------|-------------|
| Skill-Reuse-Rate | % wiederverwendeter vs. neu gebauter Skills |
| Build-Success-Rate | % erfolgreicher Skill-Builds (developer_team) |
| Agents-per-Task | Durchschnittliche Agenten pro Task-Ausführung |
| Verification-Rounds | Anzahl Verify-Adapt-Zyklen pro Task |
| Thinking-Token-Anteil | % Thinking-Tokens an Gesamt-Output (relevant für T-Medium) |

### 3.3 Judge-Modell

Der LLM-as-Judge (`evaluate_claims` in `benchmark_runner.py`) muss auf ein **festes Modell gepinnt** werden, unabhängig vom getesteten System-Modell. Sonst variiert die Bewertungsqualität mit dem Treatment — ein schweres Confound.

**Gewähltes Judge-Modell**: `gemini/gemini-3.5-flash` — stark genug für zuverlässige semantische Evaluation, erschwinglich für ~500 Judge-Calls.

**Implementierung**: Separater `--judge-model` CLI-Parameter im Benchmark Runner (Sprint 2).

### 3.4 Statistische Tests

| Vergleich | Test | Voraussetzung |
|-----------|------|--------------|
| T-Weak vs T-Medium vs T-Strong (L3-L5) | Friedman-Test | ≥3 Gruppen, gepaart, gleiche Seeds |
| Paarweise Post-hoc | Wilcoxon signed-rank + Bonferroni | Nach signifikantem Friedman |
| Evolution ON vs OFF | Wilcoxon signed-rank | 2 Gruppen, gepaart |
| Effect Size | Rank-biserial Korrelation | Immer |

**Signifikanzniveau**: α = 0.05, Bonferroni-korrigiert bei multiplem Testen.

**Gepaarte Beobachtungen**: Jeder Task ist eine Beobachtung → 21 Paare (L3-L5). Bei 3 Seeds: aggregiert per Task (Mean-Score pro Task über Seeds).

**Datenquellen für den Friedman-Test (L3-L5)**:
- T-Weak: Daten aus `ABL-WEAK-EVO-ON` (Cold → L3-L5, Evolution ON). **Nicht** aus `U-WEAK-FULL`, weil dort L1/L2 vor L3 laufen und das System durch Evolution Skills aufbaut, die L3+ Ergebnisse beeinflussen.
- T-Medium: Daten aus `U-MEDIUM-L3L5`
- T-Strong: Daten aus `U-STRONG-L3L5`

Alle drei Datenquellen starten cold bei L3 mit identischen Tasks → sauberer gepaarter Vergleich.

### 3.5 Statistische Power und Limitationen

- **Stichprobengröße**: 21 Tasks (L3-L5) sind **kleine Stichproben**. Friedman mit n=21 und k=3 hat bei mittlerer Effektgröße (w=0.3) eine Power von ~0.55-0.65. Große Effekte (w>0.5) sind detektierbar, subtile Unterschiede möglicherweise nicht.
- **Gegenmaßnahme**: Effect Sizes (rank-biserial r) immer berichten, auch bei nicht-signifikanten p-Werten. Deskriptive Analyse und Visualisierungen ergänzen die Inferenzstatistik.
- **Gebündelte Ablation**: Evolution-Ablation misst den Gesamteffekt des Evolution-Pakets (3 Flags), nicht einzelne Komponenten. In der Thesis als Limitation benennen.

### 3.6 Erwartete Visualisierungen

1. **Box-Plot**: Pass@1 pro Tier (x-Achse: Tier, y-Achse: Pass@1)
2. **Pareto-Kurve**: Quality (Pass@1) vs. Cost ($) — zeigt optimalen Trade-off
3. **Heatmap**: Tasks × Configs (Zeilen: Task-IDs, Spalten: Configs, Farbe: Pass/Fail)
4. **Bar-Chart**: Evolution-Effekt (Δ Pass@1 mit vs. ohne Evolution, gruppiert nach Tier)
5. **Line-Plot**: Pass@1 nach Komplexitäts-Level (L3, L4, L5) pro Tier
6. **Scatter**: Token-Verbrauch vs. Pass@1 pro Task (Farbe = Tier)

---

## 4. Hypothesen

| # | Hypothese | Test |
|---|-----------|------|
| H1 | Pass@1 steigt monoton mit Modell-Tier (Weak < Medium < Strong) | Friedman + Post-hoc |
| H2 | Der Anstieg ist sublinear zu den Kosten (diminishing returns) | Pareto-Analyse |
| H3 | Evolution-Effekt ist größer bei schwachen Modellen (Interaktion) | 2×2 ANOVA-äquivalent |
| H4 | Thinking-Modelle (T-Medium) verbrauchen überproportional mehr Tokens als Non-Thinking-Modelle bei gleichen Tasks | Friedman auf Token-Counts |

**Zu H4**: Gemini 2.5 Flash generiert Thinking-Tokens, die den Output-Verbrauch erhöhen. Die Hypothese testet, ob dieser Mehrverbrauch durch bessere Task-Completion kompensiert wird (→ H2 Quality/Cost Ratio).

---

## 5. Implementierungsplan

### Sprint 1: Model-Config-System (Tag 1, ~3h)

**Ziel**: Benchmark Runner kann per YAML-Datei verschiedene Modell-Konfigurationen laden und zur Laufzeit anwenden.

#### Tasks

1. **Model-Config YAML-Schema definieren**
   - Datei: `backend/scripts/evaluation/model_configs/schema.py`
   - Pydantic-Modell für Config-Dateien
   - Felder: config_id, description, models (pro TaskType), ablation_flags, judge_model

2. **Config-Dateien erstellen**
   - Verzeichnis: `backend/scripts/evaluation/model_configs/`
   - 6 YAML-Dateien für alle Configs (u_weak_full, u_medium_l3l5, u_strong_l3l5, abl_weak_evo_on, abl_weak_evo_off, abl_strong_evo_off)

3. **Runtime-Model-Switch implementieren**
   - Datei: `backend/app/api/v1/endpoints/settings.py` (neuer Endpoint)
   - `PUT /api/v1/settings/models` → setzt LLMRouter-Modelle zur Laufzeit
   - `PUT /api/v1/settings/ablation` → setzt Feature-Flags (evolution, shared_memory, skill_reuse)
   - `GET /api/v1/settings/current` → gibt aktuelle Konfiguration zurück

4. **LLMRouter.bulk_update() Methode**
   - Datei: `backend/app/core/llm_router.py`
   - Neue Methode: nimmt dict[TaskType, str] und aktualisiert alle Modelle + invalidiert Client-Cache
   - Bestehende `update_model()` bleibt für Einzeländerungen

#### Deliverable
```bash
# Verifikation: Config laden und Modelle umschalten
curl -X PUT localhost:8000/api/v1/settings/models \
  -d '{"research":"gemini/gemini-2.5-flash","architecture":"gemini/gemini-2.5-flash",...}'
curl localhost:8000/api/v1/settings/current
# → zeigt aktualisierte Modelle
```

---

### Sprint 2: Benchmark Runner Integration (Tag 1-2, ~4h)

**Ziel**: `--model-config` und `--judge-model` Flags im Runner, automatisches Model-Switching vor jedem Run.

#### Tasks

1. **CLI-Parameter `--model-config` hinzufügen**
   - Datei: `backend/scripts/evaluation/benchmark_runner.py`
   - Lädt YAML aus `model_configs/`
   - Setzt Modelle per API-Call vor Run-Start
   - Setzt Ablation-Flags falls in Config definiert

2. **CLI-Parameter `--judge-model` hinzufügen**
   - Default: `gemini/gemini-3.5-flash`
   - Erzeugt separaten `LLMClient(model=judge_model)` für `evaluate_claims()`
   - **Kritisch**: Das Judge-Modell darf sich NICHT mit der System-Config ändern

3. **Task-Level-Filter implementieren**
   - Neuer CLI-Parameter: `--levels L3,L4,L5`
   - Filtert Tasks aus der Suite basierend auf Level
   - Ermöglicht: `--suite progressive_complexity --levels L3,L4,L5`

4. **Kosten-Tracking im Output**
   - Token-Counts (input/output/thinking getrennt) pro Task speichern
   - Model-ID pro Task im Result-JSON speichern
   - Kosten-Berechnung: tokens × pricing (aus Config)
   - Neues Feld im Output: `cost_usd` pro Task und aggregiert
   - **Thinking-Token-Handling**: LiteLLM response `usage` Feld prüfen — `completion_tokens_details.reasoning_tokens` für Gemini 2.5 Thinking-Tokens extrahieren. Fallback: `completion_tokens` als Gesamtheit verwenden, in Thesis als Limitation notieren falls nicht differenzierbar.

5. **Config-Metadaten in Output-JSON**
   - Felder: `model_config_id`, `models_used`, `ablation_flags`, `judge_model`
   - Ermöglicht spätere Zuordnung Run → Konfiguration

#### Deliverable
```bash
python -m scripts.evaluation.benchmark_runner \
  --suite progressive_complexity \
  --model-config u_medium_l3l5 \
  --levels L3,L4,L5 \
  --judge-model "gemini/gemini-3.5-flash" \
  --seeds 3 --mode cold \
  --output results/modellvergleich/u_medium_l3l5.json
```

---

### Sprint 3: Analyse-Pipeline (Tag 2-3, ~4h)

**Ziel**: Automatisierte statistische Auswertung und Plot-Generierung aus den Run-Ergebnissen.

#### Tasks

1. **Vergleichs-Aggregator**
   - Datei: `backend/scripts/evaluation/model_comparison.py`
   - Lädt mehrere Result-JSONs
   - Aligned Tasks (gleiche task_ids über Configs)
   - Berechnet: Pass@1 pro Config, pro Level, pro Task

2. **Statistische Tests**
   - Friedman-Test (scipy.stats.friedmanchisquare)
   - Wilcoxon signed-rank (scipy.stats.wilcoxon) mit Bonferroni
   - Effect Size (rank-biserial correlation)
   - Confidence Intervals (Bootstrap, 95%)
   - Output: Tabelle mit p-Werten, Effect Sizes, Signifikanz-Markern

3. **Visualisierungen (matplotlib/seaborn)**
   - Datei: `backend/scripts/evaluation/plot_comparison.py`
   - 6 Plot-Typen (siehe Abschnitt 3.6)
   - Export als PDF (Thesis-ready) und PNG (Präsentation)
   - Einheitliches Farbschema: T-Weak=blau, T-Medium=orange, T-Strong=grün

4. **Kosten-Analyse**
   - Quality/Cost Ratio berechnen
   - Pareto-Frontier identifizieren
   - Break-even-Analyse: "Ab welchem Task-Volumen lohnt sich Upgrade?"

#### Deliverable
```bash
python -m scripts.evaluation.model_comparison \
  --results results/modellvergleich/ \
  --output results/modellvergleich/analysis/ \
  --plots results/modellvergleich/plots/
# → analysis/statistics.json, plots/*.pdf
```

---

### Sprint 4: Durchführung (Tag 3-4, ~20h Rechenzeit)

**Ziel**: Alle 6 Konfigurationen durchlaufen lassen, Ergebnisse sammeln.

#### Ablauf

```
Tag 3 (Nachmittag):
├── 1. Smoke-Test: 3 Modelle × 1 Task × 1 Seed (~20min)
├── 2. U-WEAK-FULL starten (3 Seeds × 37 Tasks, ~3h)
└── 3. ABL-WEAK-EVO-OFF starten (3 Seeds × 21 Tasks, ~2h)

Tag 4 (ganzer Tag):
├── 4. ABL-WEAK-EVO-ON starten (3 Seeds × 21 Tasks, ~2h)
├── 5. U-MEDIUM-L3L5 (3 Seeds × 21 Tasks, ~4h)
└── 6. ABL-STRONG-EVO-OFF (3 Seeds × 21 Tasks, ~4h)

Tag 5 (halber Tag):
├── 7. U-STRONG-L3L5 (3 Seeds × 21 Tasks, ~4h)
└── 8. Analyse-Pipeline laufen lassen
```

#### Voraussetzungen
- Gemini API Key mit ausreichendem Quota für alle 3 Modelle
- Verfügbarkeit von gemini-3.5-flash verifiziert (neues Modell, Mai 2026)
- System stabil (Smoke-Test vorher)
- Cold-Reset-Script funktioniert zuverlässig
- Genug Disk-Space für Result-JSONs

#### Smoke-Test vor Durchführung (Pflicht)

Vor den teuren Runs **jeden** der 3 Modell-Tiers mit 1 Task × 1 Seed testen:

```bash
# Pro Modell: 1 einfacher L3-Task, prüft Verfügbarkeit + Output-Format
for config in u_weak_full u_medium_l3l5 u_strong_l3l5; do
  python -m scripts.evaluation.benchmark_runner \
    --suite progressive_complexity \
    --model-config $config \
    --levels L3 --seeds 1 --mode cold \
    --output results/smoke/$config.json
done
```

**Prüfen**:
1. Alle 3 Modelle antworten ohne Rate-Limit-Fehler
2. LiteLLM liefert `completion_tokens_details.reasoning_tokens` für gemini-2.5-flash (Thinking-Tokens)
3. Judge-Modell (`gemini-3.5-flash`) evaluiert korrekt, auch wenn das System-Modell identisch ist
4. Token-Counts und Kosten-Berechnung plausibel
5. Cold-Reset zwischen Configs funktioniert vollständig

#### Risiko-Mitigation
- Vor teuren Runs (T-Strong): 1 Seed Dry-Run prüfen
- Token-Budget-Alarm: Abbruch wenn ein einzelner Run >$10 verbraucht
- Checkpoint: Nach jedem Seed Result-JSON sichern
- Judge-Modell vor Durchführung auf Konsistenz testen (10 Tasks mit 2 Modellen evaluieren, Cohen's Kappa prüfen)

---

### Sprint 5: Auswertung und Thesis-Integration (Tag 5-6, ~4h)

**Ziel**: Ergebnisse aufbereiten, Interpretation, Thesis-Text vorbereiten.

#### Tasks

1. **Analyse-Pipeline ausführen**
   - Statistische Tests durchführen
   - Plots generieren
   - Ergebnis-Tabellen für Thesis formatieren (LaTeX)

2. **Interpretation**
   - Hypothesen H1-H4 bestätigen/widerlegen
   - Unerwartete Ergebnisse identifizieren
   - Limitations dokumentieren (Power, gebündelte Ablation, fehlende Mixed-Config)

3. **Thesis-Abschnitt vorbereiten**
   - "4.X Model Capability Study" Kapitel-Struktur
   - Tabellen und Figures einordnen
   - Diskussion: Implikationen für MAS-Design

---

## 6. Model-Config Dateien (Referenz)

### u_weak_full.yaml
```yaml
config_id: U-WEAK-FULL
description: "Schwächstes Modell (gemini-2.0-flash) auf allen Levels — Baseline"
levels: [L1, L2, L3, L4, L5]
seeds: 3
mode: cold
judge_model: "gemini/gemini-3.5-flash"
models:
  research: "gemini/gemini-2.0-flash"
  architecture: "gemini/gemini-2.0-flash"
  implementation: "gemini/gemini-2.0-flash"
  review: "gemini/gemini-2.0-flash"
  code_fix: "gemini/gemini-2.0-flash"
  semantic_validation: "gemini/gemini-2.0-flash"
  general: "gemini/gemini-2.0-flash"
ablation:
  autonomous_evolution_enabled: true
  shared_memory_enabled: true
  skill_reuse_enabled: true
```

### u_medium_l3l5.yaml
```yaml
config_id: U-MEDIUM-L3L5
description: "Thinking-Modell (gemini-2.5-flash) auf L3-L5 — Mittlere Capability"
levels: [L3, L4, L5]
seeds: 3
mode: cold
judge_model: "gemini/gemini-3.5-flash"
models:
  research: "gemini/gemini-2.5-flash"
  architecture: "gemini/gemini-2.5-flash"
  implementation: "gemini/gemini-2.5-flash"
  review: "gemini/gemini-2.5-flash"
  code_fix: "gemini/gemini-2.5-flash"
  semantic_validation: "gemini/gemini-2.5-flash"
  general: "gemini/gemini-2.5-flash"
ablation:
  autonomous_evolution_enabled: true
  shared_memory_enabled: true
  skill_reuse_enabled: true
```

### u_strong_l3l5.yaml
```yaml
config_id: U-STRONG-L3L5
description: "Neustes Agentic-Modell (gemini-3.5-flash) auf L3-L5 — Starke Capability"
levels: [L3, L4, L5]
seeds: 3
mode: cold
judge_model: "gemini/gemini-3.5-flash"
models:
  research: "gemini/gemini-3.5-flash"
  architecture: "gemini/gemini-3.5-flash"
  implementation: "gemini/gemini-3.5-flash"
  review: "gemini/gemini-3.5-flash"
  code_fix: "gemini/gemini-3.5-flash"
  semantic_validation: "gemini/gemini-3.5-flash"
  general: "gemini/gemini-3.5-flash"
ablation:
  autonomous_evolution_enabled: true
  shared_memory_enabled: true
  skill_reuse_enabled: true
```

### abl_weak_evo_on.yaml
```yaml
config_id: ABL-WEAK-EVO-ON
description: "Schwaches Modell MIT Evolution auf L3-L5 — Ablation Treatment"
levels: [L3, L4, L5]
seeds: 3
mode: cold
judge_model: "gemini/gemini-3.5-flash"
models:
  research: "gemini/gemini-2.0-flash"
  architecture: "gemini/gemini-2.0-flash"
  implementation: "gemini/gemini-2.0-flash"
  review: "gemini/gemini-2.0-flash"
  code_fix: "gemini/gemini-2.0-flash"
  semantic_validation: "gemini/gemini-2.0-flash"
  general: "gemini/gemini-2.0-flash"
ablation:
  autonomous_evolution_enabled: true
  shared_memory_enabled: true
  skill_reuse_enabled: true
```

### abl_weak_evo_off.yaml
```yaml
config_id: ABL-WEAK-EVO-OFF
description: "Schwaches Modell OHNE Evolution — Ablation Baseline"
levels: [L3, L4, L5]
seeds: 3
mode: cold
judge_model: "gemini/gemini-3.5-flash"
models:
  research: "gemini/gemini-2.0-flash"
  architecture: "gemini/gemini-2.0-flash"
  implementation: "gemini/gemini-2.0-flash"
  review: "gemini/gemini-2.0-flash"
  code_fix: "gemini/gemini-2.0-flash"
  semantic_validation: "gemini/gemini-2.0-flash"
  general: "gemini/gemini-2.0-flash"
ablation:
  autonomous_evolution_enabled: false
  shared_memory_enabled: false
  skill_reuse_enabled: false
```

### abl_strong_evo_off.yaml
```yaml
config_id: ABL-STRONG-EVO-OFF
description: "Starkes Modell OHNE Evolution — zeigt reinen Modell-Effekt"
levels: [L3, L4, L5]
seeds: 3
mode: cold
judge_model: "gemini/gemini-3.5-flash"
models:
  research: "gemini/gemini-3.5-flash"
  architecture: "gemini/gemini-3.5-flash"
  implementation: "gemini/gemini-3.5-flash"
  review: "gemini/gemini-3.5-flash"
  code_fix: "gemini/gemini-3.5-flash"
  semantic_validation: "gemini/gemini-3.5-flash"
  general: "gemini/gemini-3.5-flash"
ablation:
  autonomous_evolution_enabled: false
  shared_memory_enabled: false
  skill_reuse_enabled: false
```

---

## 7. Erwartete Ergebnisse (Thesis-Kapitel)

### Tabelle: Modellvergleich Hauptergebnis

| Config | Tier | Pass@1 L3 | Pass@1 L4 | Pass@1 L5 | Tokens/Run | Kosten/Run | Quality/$ |
|--------|------|-----------|-----------|-----------|-----------|-----------|-----------|
| U-WEAK | 2.0-flash | ? | ? | ? | ? | ? | ? |
| U-MEDIUM | 2.5-flash | ? | ? | ? | ? | ? | ? |
| U-STRONG | 3.5-flash | ? | ? | ? | ? | ? | ? |

### Tabelle: Evolution-Ablation

| Config | Evolution | Pass@1 (L3-L5) | Δ vs. OFF |
|--------|-----------|----------------|-----------|
| WEAK + EVO | ✅ | ? | — |
| WEAK - EVO | ❌ | ? | ? |
| STRONG + EVO | ✅ | ? | — |
| STRONG - EVO | ❌ | ? | ? |

### Erwartete Narrative (Hypothesen)

1. **"Diminishing Returns"**: T-Strong bringt nur marginale Verbesserung über T-Medium → Architektur wichtiger als Modell
2. **"Evolution als Equalizer"**: Schwaches Modell + Evolution ≈ Starkes Modell ohne Evolution
3. **"Cost Sweet-Spot"**: T-Medium (2.5-flash) bietet bestes Quality/$ Verhältnis

---

## 8. Risiken und Mitigation

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|--------|-------------------|--------|-----------|
| API-Rate-Limits bei 3.5-flash | Mittel | Run-Abbruch | Retry-Logic, ggf. über Nacht laufen |
| 3.5-flash noch instabil (neues Modell) | Niedrig | Inkonsistente Ergebnisse | Mehr Seeds, Outlier-Analyse |
| Kosten höher als geschätzt | Mittel | Budget überschritten | Token-Budget-Alarm ($10/Run), Dry-Run zuerst |
| Cold-Reset unvollständig | Niedrig | Kontamination zwischen Seeds | Reset-Verifikation im Script |
| Thinking-Tokens nicht separat getrackt | Mittel | Kostenunterschätzung T-Medium | LiteLLM `completion_tokens_details` Feld prüfen, Fallback: Gesamt-Completion-Tokens × Output-Preis |
| Judge-Modell-Varianz | Niedrig | Inkonsistente Bewertung | Festes Judge-Modell, vorab Inter-Rater-Test mit 10 Tasks |
| Geringe statistische Power | Mittel | Nicht-signifikante Ergebnisse bei echten Effekten | Effect Sizes immer berichten, deskriptive Analyse als Ergänzung |

---

## 9. Timeline

```
Tag 1:  Sprint 1 + 2 (Model-Config-System + Runner-Integration)
Tag 2:  Sprint 2 abschließen + Sprint 3 (Analyse-Pipeline)
Tag 3:  Smoke-Tests + Sprint 4 beginnt (günstige Runs: U-WEAK, ABL-WEAK-OFF, ABL-WEAK-ON)
Tag 4:  Sprint 4 fortsetzen (U-MEDIUM, ABL-STRONG-OFF, U-STRONG)
Tag 5:  Sprint 5 (Analyse-Pipeline laufen lassen, Auswertung)
Tag 6:  Thesis-Integration, Plots finalisieren
```

**Gesamtaufwand**: ~6 Tage (davon ~2 Tage Implementierung, ~2 Tage Rechenzeit, ~2 Tage Auswertung)

---

## 10. Änderungslog

| Datum | Änderung |
|-------|----------|
| 2026-05-23 | **Review & Überarbeitung**: L4-L5 Taskzahl korrigiert (14 statt 13), Judge-Modell fixiert, ABL-WEAK-EVO-ON als eigener Run, T-Frontier auf 3 Seeds, H5 reformuliert, Power-Limitationen dokumentiert, Thinking-Token-Tracking konkretisiert, Kosten realistischer geschätzt, Ablation-Flag-Bündelung als Limitation benannt |
| 2026-05-23 | **Konfundierungs-Fix**: Friedman-Datenquelle für T-Weak auf ABL-WEAK-EVO-ON korrigiert — U-WEAK-FULL ist durch L1/L2-Evolution kontaminiert. Pflicht-Smoke-Test vor Sprint 4 ergänzt. |
| 2026-05-23 | **Reduktion auf 3 Tiers**: T-Frontier (gemini-3.1-pro-preview) gestrichen — Latenz-Confound (~27s TTFT verursacht Timeouts), auf Agentic-Benchmarks schwächer als 3.5-flash (MCP Atlas: 69% vs 84%), Budget-Optimierung. Phase 3 (Flash vs Pro) entfällt, H4 gestrichen. Alle Flash-Tier = kein Architektur-Confound. 6 Configs, 18 Runs, ~$22. Timeline auf 6 Tage verkürzt. |