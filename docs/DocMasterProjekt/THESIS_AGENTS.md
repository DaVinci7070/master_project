# Thesis-Agenten — Übersicht

Spezialisierte Claude-Code-Agenten für die Masterarbeit *"Enabling Secure Structural
Self-Evolution in Multi-Agent Systems via Retrieval-Augmented Blueprint Generation"*.
Sie liegen in `.claude/agents/` und decken die vier Phasen **Recherche → Aufbau → Schreiben →
LaTeX** ab. Darüber steht `professor` als kritischer Gutachter.

> **Wichtig:** Nach dem Anlegen neuer Agenten **Claude Code einmal neu starten** — Agenten
> werden nur beim Session-Start geladen.
>
> **Aufruf:** einfach natürlich adressieren, z. B. *"schreibstil-lektor: prüf Kapitel 5"*.
> `professor` hat zusätzlich den Slash-Command `/professor`.

---

## 🎓 Kritischer Anker

### `professor` — Erstgutachter
Strenger Informatik-Professor, der Kapitel, Methodik, Ergebnisse und Claims nach akademischen
Maßstäben zerlegt: deckt **Overclaiming** und methodische Schwächen auf, bewertet nach Rubrik
(Note 1–5), stellt harte **Verteidigungsfragen** und ist auf die Sollbruchstellen der Arbeit
geeicht (RQ1-Baseline, RQ2-Null-Ergebnis, RQ3-Zirkularität). *Nur lesen.*
`/professor Results.md` · `/professor <kapitel> methodik|claims|disputation|struktur`

---

## 🔍 Recherche

### `recherche-analyst`
Findet fehlende **Related Work**, prüft **Novelty-Ansprüche** ehrlich (ist es wirklich neu?),
bewertet Positionierung/Framing und antizipiert Gutachter-Einwände. *Liest + Websuche.*
→ *"recherche-analyst: prüf mein Related-Work-Kapitel auf fehlende Baselines"*

### `literatur-scout`
Sucht relevante Paper über **DBLP, OpenAlex und Websuche**, dedupliziert, bewertet Relevanz und
liefert **fertige BibTeX-Einträge**. *Liest + Web + curl.*
→ *"literatur-scout: finde Arbeiten zu LLM agent tool safety 2024–2026"*

---

## 🏗️ Aufbau & Struktur

### `argumentations-pruefer`
Prüft den **roten Faden**: Argumentstruktur, Übergänge zwischen Absätzen/Kapiteln, Erzählbogen
(Motivation → Methode → Ergebnis → Fazit), logische Lücken und Redundanzen. *Nur lesen.*
→ *"argumentations-pruefer: geh Kapitel 4 auf logische Brüche durch"*

### `konsistenz-pruefer`
Prüft **Konsistenz** über die ganze Arbeit: einheitliche Terminologie (speziell deine
Deutsch/Englisch-Begriffsmischung), Querverweise (`\ref`/`\cite`), Abbildung-Text-Caption,
Notation und Abkürzungen. *Nur lesen.*
→ *"konsistenz-pruefer: prüf die gesamte Arbeit auf Terminologie"*

---

## ✍️ Schreiben & Sprache

### `schreibstil-lektor`
Lektor für **deutschen Wissenschaftsstil**: Klarheit, Prägnanz, Grammatik, Ton — und erkennt
**"KI-Sprech"** (typische Floskeln generierter Texte). Meldet mit Umschreibvorschlag,
ändert aber nichts. *Nur lesen.*
→ *"schreibstil-lektor: Kapitel 5"*

### `sprachpolitur`
Setzt Stilverbesserungen **tatsächlich um** — schreibt Prosa klarer, bewahrt dabei Bedeutung,
Zitate und LaTeX-Befehle. Der einzige Agent, der Dateien bearbeitet. *Ändert Dateien (Edit).*
→ *"sprachpolitur: setz die Vorschläge in Kapitel 5 um"*

---

## 📐 LaTeX & Bibliografie

### `latex-lektor`
Zwei Jobs: **(A) LaTeX-Bau/Layout** — kompiliert, findet Overfull-hboxes, ungelöste
`\ref`/`\cite` (`??`), schlechte Float-Platzierung; **(B) BibTeX-Hygiene** — Vollständigkeit,
arXiv→publizierte Version, geschützte Eigennamen in Titeln, Dubletten. *Liest + kompiliert.*
→ *"latex-lektor: kompilier und prüf Floats + .bib"*

---

## Empfohlener Ablauf pro Kapitel

```
argumentations-pruefer   → roter Faden sitzt?
schreibstil-lektor       → Stil-Befunde
sprachpolitur            → Befunde umsetzen
konsistenz-pruefer       → Begriffe/Verweise konsistent?
latex-lektor             → kompiliert sauber, .bib ok?
professor                → Härtetest vor Abgabe (Claims, Methodik, Disputation)
```

*Die Agenten basieren auf [andrehuang/academic-writing-agents](https://github.com/andrehuang/academic-writing-agents)
(MIT), zugeschnitten auf Deutsch, LaTeX und diese Arbeit.*
