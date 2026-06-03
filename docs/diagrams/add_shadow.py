#!/usr/bin/env python3
"""Injiziert einen weichen Schlagschatten-Filter in ein Mermaid-SVG.
Wirkt nur auf Knoten-Formen (.node), nicht auf Cluster/Kanten."""
import re
import sys

INJECT = """<defs>
<filter id="softshadow" x="-30%" y="-30%" width="160%" height="160%">
  <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#26344D" flood-opacity="0.16"/>
</filter>
</defs>
<style>
.node rect,.node circle,.node ellipse,.node polygon,.node path{filter:url(#softshadow);}
</style>"""


def main(path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        svg = fh.read()
    if "id=\"softshadow\"" in svg:
        return
    svg = re.sub(r"(<svg\b[^>]*>)", r"\1\n" + INJECT, svg, count=1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)


if __name__ == "__main__":
    main(sys.argv[1])
