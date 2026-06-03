#!/usr/bin/env bash
# Rendert alle Mermaid-Diagramme als SVG (+ PNG) und fügt einen dezenten
# Schlagschatten via SVG-Filter ein. Erneut ausführen nach jeder .mmd-Änderung.
set -euo pipefail
cd "$(dirname "$0")"

for f in 00_overview_blackbox 01_system_overview 02_evolution_loop 03_skill_pipeline 04_pre_execution 05_execution_verify 06_gatekeeper; do
  mmdc -i "$f.mmd" -o "$f.svg" -b transparent -C style.css
  mmdc -i "$f.mmd" -o "$f.png" -b white -s 2 -C style.css
  python3 add_shadow.py "$f.svg"
  echo "fertig: $f.svg + $f.png"
done
