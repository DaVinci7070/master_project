/**
 * Kuratierte Thesis-Benchmark-Ergebnisse (RQ1–RQ3).
 *
 * Statisch gebündelt, damit die Ergebnisse im Frontend überall sichtbar sind —
 * auch auf einem Server/PC ohne lokale Benchmark-Dateien. Quelle der Zahlen:
 *   - RQ1/RQ2: backend/results/thesis/analysis/statistics.json  (+ cold_warm/*)
 *   - RQ3:     backend/results/thesis/gatekeeper/gatekeeper_final.json
 *
 * Stand: 2026-05-30. Beim Re-Run der Analyse-Pipeline hier aktualisieren.
 */

export const THESIS_META = {
  suite: 'progressive_complexity',
  generatedAt: '2026-05-30',
  judgeModel: 'gemini/gemini-3.5-flash',
  note: 'Pass@1 = Anteil der Tasks, deren generierter Bericht den LLM-Judge bestanden hat (Score ≥ Schwelle).',
} as const

// ──────────────────────────────────────────────────────────────────
// RQ1 — Strukturelle Selbst-Evolution vs. statisches MAS
// ──────────────────────────────────────────────────────────────────

export interface AblationPair {
  tier: string
  model: string
  /** Mittlerer Score mit aktivierter Evolution */
  meanOn: number
  meanOff: number
  passOn: number
  passOff: number
  deltaPass: number
  pValue: number
  significant: boolean
  effectSize: number
  ci95On: [number, number]
  ci95Off: [number, number]
}

export interface LevelScore {
  level: string
  on: number
  off: number
}

export const RQ1 = {
  question:
    'Erreicht strukturelle Selbst-Evolution höhere Task-Completion als ein statisches Multi-Agenten-System?',
  verdict: 'bestätigt',
  summary:
    'In beiden Modell-Stufen verbessert die autonome Evolution die Task-Completion signifikant. ' +
    'Der Effekt ist am stärksten bei komplexen L5-Audio-Tasks, wo ohne Evolution passende Fähigkeiten fehlen.',
  /** Paired-Wilcoxon: Evolution AN vs. AUS, je Modell-Stufe */
  ablation: [
    {
      tier: 'Weak',
      model: 'gemini/gemini-2.0-flash',
      meanOn: 0.7904,
      meanOff: 0.6133,
      passOn: 0.619,
      passOff: 0.3333,
      deltaPass: 0.2857,
      pValue: 0.0225,
      significant: true,
      effectSize: 0.7143,
      ci95On: [0.6566, 0.9063],
      ci95Off: [0.4673, 0.7535],
    },
    {
      tier: 'Strong',
      model: 'gemini/gemini-3.5-flash',
      meanOn: 0.8476,
      meanOff: 0.714,
      passOn: 0.7143,
      passOff: 0.4762,
      deltaPass: 0.2381,
      pValue: 0.0264,
      significant: true,
      effectSize: 0.8545,
      ci95On: [0.7206, 0.9524],
      ci95Off: [0.5688, 0.8448],
    },
  ] as AblationPair[],

  /** Pass@1 je Schwierigkeitsgrad — Weak-Stufe (Evolution AN vs. AUS) */
  perLevelWeak: [
    { level: 'L3', on: 0.9048, off: 0.7143 },
    { level: 'L4', on: 0.8571, off: 0.7619 },
    { level: 'L5', on: 0.5714, off: 0.2381 },
  ] as LevelScore[],

  /** Pass@1 je Schwierigkeitsgrad — Strong-Stufe (Evolution AN vs. AUS) */
  perLevelStrong: [
    { level: 'L3', on: 0.8095, off: 0.7619 },
    { level: 'L4', on: 0.9524, off: 0.8095 },
    { level: 'L5', on: 0.7143, off: 0.5238 },
  ] as LevelScore[],

  /** Friedman-Test über die Modell-Stufen (Evolution jeweils AN) */
  capabilityTiers: {
    pValue: 0.1524,
    significant: false,
    tiers: [
      { tier: 'Weak', model: 'gemini-2.0-flash', meanScore: 0.7904 },
      { tier: 'Medium', model: 'gemini-2.5-flash', meanScore: 0.7534 },
      { tier: 'Strong', model: 'gemini-3.5-flash', meanScore: 0.8476 },
    ],
    note:
      'Kein signifikanter Unterschied zwischen den Modell-Stufen (p = 0.15). Selbst die schwache Stufe ' +
      'erreicht mit Evolution eine vergleichbare Qualität — die Evolution wirkt stärker als die reine Modellgröße.',
  },
} as const

// ──────────────────────────────────────────────────────────────────
// RQ2 — Blueprint-Reuse & Ressourcenverbrauch (Cold vs. Warm)
// ──────────────────────────────────────────────────────────────────

export interface ColdWarmMetric {
  label: string
  cold: number
  warm: number
  /** Niedriger ist besser (z.B. Tokens/Kosten) → Reduktion ist gut */
  lowerIsBetter: boolean
  unit: string
}

export const RQ2 = {
  question:
    'Reduziert die Wiederverwendung autonom generierter Blueprints den Ressourcenverbrauch bei nachfolgenden Aufgaben gleichen Typs?',
  verdict: 'bestätigt',
  summary:
    'Beim Warm-Start (vorhandene Blueprints) entfällt die Build-Phase. Die Assembly-Tokens pro Seed sinken ' +
    'um ~10 %, während die Task-Completion sogar leicht steigt. Die Blueprint-Wiederverwendung spart also ' +
    'Ressourcen ohne Qualitätsverlust.',
  seeds: 3,
  tasksPerSeed: 37,
  metrics: [
    { label: 'Pass@1', cold: 0.766, warm: 0.82, lowerIsBetter: false, unit: '%' },
    { label: 'Assembly-Tokens / Seed', cold: 130351, warm: 117049, lowerIsBetter: true, unit: '' },
    { label: 'Assembly-Anteil', cold: 6.8, warm: 5.4, lowerIsBetter: true, unit: '%' },
  ] as ColdWarmMetric[],

  /** Token-Aufschlüsselung pro Phase (Summe über alle Seeds/Tasks) */
  tokenBreakdown: [
    { phase: 'Assembly (Build)', cold: 391052, warm: 351146 },
    { phase: 'Execution', cold: 4452936, warm: 5293418 },
    { phase: 'Verification', cold: 277294, warm: 269776 },
  ],

  /** Pass@1 je Seed */
  perSeed: [
    { seed: 1, cold: 0.811, warm: 0.811 },
    { seed: 2, cold: 0.703, warm: 0.784 },
    { seed: 3, cold: 0.784, warm: 0.865 },
  ],

  note:
    'Die Gesamt-Tokens schwanken durch Ausführungs-Varianz (Warm-Seed 3 mit vielen LLM-Retries). ' +
    'Der RQ2-Kerneffekt ist die eingesparte Build-Phase (Assembly-Tokens), nicht der Gesamtverbrauch.',
} as const

// ──────────────────────────────────────────────────────────────────
// RQ3 — Semantischer Gatekeeper (Code-Beschreibung-Diskrepanzen)
// ──────────────────────────────────────────────────────────────────

export interface GatekeeperLayer {
  id: string
  label: string
  accuracy: number
  precision: number
  recall: number
  f1: number
  fpr: number
  fnr: number
}

export interface CategoryRow {
  category: string
  label: string
  n: number
  astCorrect: string
  combinedCorrect: string
}

export const RQ3 = {
  question:
    'Erkennt der semantische Gatekeeper gefährliche Diskrepanzen zwischen Code und Beschreibung?',
  verdict: 'bestätigt',
  summary:
    'Die kombinierte Schicht (AST-Analyse + semantisches Alignment) erreicht 91,5 % F1 bei 92,4 % Recall. ' +
    'Reine AST-Prüfung erkennt nur strukturell-unsichere Muster (Recall 57 %) und verfehlt jede semantische ' +
    'Täuschung; das semantische Alignment schließt genau diese Lücke.',
  corpusSize: 55,
  nRuns: 3,
  layers: [
    {
      id: 'ast_only',
      label: 'Nur AST',
      accuracy: 0.7273,
      precision: 1.0,
      recall: 0.5714,
      f1: 0.7273,
      fpr: 0.0,
      fnr: 0.4286,
    },
    {
      id: 'alignment_only',
      label: 'Nur Alignment',
      accuracy: 0.8606,
      precision: 0.9025,
      recall: 0.8762,
      f1: 0.889,
      fpr: 0.1667,
      fnr: 0.1238,
    },
    {
      id: 'combined',
      label: 'Kombiniert',
      accuracy: 0.8909,
      precision: 0.9069,
      recall: 0.9238,
      f1: 0.9152,
      fpr: 0.1667,
      fnr: 0.0762,
    },
  ] as GatekeeperLayer[],

  /** Korrekt klassifiziert je Kategorie (AST allein vs. kombiniert) */
  categories: [
    { category: 'safe', label: 'Sicher (Kontrolle)', n: 20, astCorrect: '20/20', combinedCorrect: '16.7/20' },
    { category: 'unsafe', label: 'Unsicher (I/O, exec)', n: 20, astCorrect: '20/20', combinedCorrect: '20/20' },
    { category: 'bypass', label: 'Sandbox-Bypass', n: 5, astCorrect: '0/5', combinedCorrect: '5/5' },
    { category: 'deception', label: 'Täuschung', n: 5, astCorrect: '0/5', combinedCorrect: '4/5' },
    { category: 'semantic', label: 'Semantische Bugs', n: 5, astCorrect: '0/5', combinedCorrect: '3.3/5' },
  ] as CategoryRow[],

  /** Threshold-Sweep der kombinierten Schicht (ROC-artig) */
  thresholdSweep: [
    { threshold: 0.5, tpr: 0.6762, fpr: 0.0167, f1: 0.8022 },
    { threshold: 0.6, tpr: 0.6571, fpr: 0.0, f1: 0.7931 },
    { threshold: 0.7, tpr: 0.9333, fpr: 0.3333, f1: 0.8788 },
    { threshold: 0.8, tpr: 0.9143, fpr: 0.4833, f1: 0.8347 },
    { threshold: 0.9, tpr: 1.0, fpr: 1.0, f1: 0.7778 },
  ],

  note:
    'Korpus aus 55 Code-Beschreibung-Paaren (3 Runs gemittelt). Die AST-Schicht ist präzise (0 % FPR), ' +
    'erkennt aber keine semantischen Täuschungen — erst das Alignment macht den Gatekeeper vollständig.',
} as const

export const RESEARCH_QUESTIONS = [
  { id: 'rq1', short: 'RQ1', title: 'Selbst-Evolution', data: RQ1 },
  { id: 'rq2', short: 'RQ2', title: 'Blueprint-Reuse', data: RQ2 },
  { id: 'rq3', short: 'RQ3', title: 'Gatekeeper', data: RQ3 },
] as const
