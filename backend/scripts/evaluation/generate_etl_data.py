import csv
import os
import random
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "data" / "etl_csvs"

HEADER = [
    "datum", "gewerk", "taetigkeit", "arbeiter", "stunden",
    "material", "material_menge", "material_einheit", "bemerkung"
]

random.seed(42)


def generate_elektro_mueller():
    """Elektro Müller GmbH — 420 Stunden, ~85.000€ Material"""
    dates = _spread_dates("2025-07", "2025-09", 10)
    entries_per_day = []

    taetigkeiten = [
        ("Kabeltrassen montieren", "Kabeltrasse", 120, "m"),
        ("Kabeltrasse verlegen", "Kabelkanal", 80, "m"),
        ("Verteilerkästen setzen", "Verteilerkasten UP", 6, "Stk"),
        ("Leitungen einziehen", "NYM-J 5x2,5", 450, "m"),
        ("Verteilerkästen verdrahten", "Klemmen/Sicherungen", 1, "Palette"),
        ("Kabelkanal montieren", "Kabelrinne 200mm", 65, "m"),
        ("Schalter/Steckdosen setzen", "Schalterprogramm Busch-Jaeger", 48, "Stk"),
        ("Deckenleuchten anschließen", "LED-Deckenleuchte", 24, "Stk"),
        ("Unterverteilung bestücken", "FI/LS-Schalter", 36, "Stk"),
        ("Erdung verlegen", "Erdungskabel 16mm²", 85, "m"),
    ]

    preise = [45, 38, 1200, 4.5, 8500, 52, 85, 189, 45, 12]

    total_stunden = 0
    target_stunden = 420

    for i, datum in enumerate(dates):
        rows = []
        n_rows = random.randint(3, 6)
        tages_stunden = 0

        used = random.sample(range(len(taetigkeiten)), min(n_rows, len(taetigkeiten)))
        for j in used:
            taetigkeit, material, menge_base, einheit = taetigkeiten[j]
            arbeiter = random.randint(2, 4)
            stunden = round(random.uniform(4, 9), 1)
            tages_stunden += stunden

            menge = round(menge_base * random.uniform(0.1, 0.3), 1)
            if einheit == "Stk":
                menge = max(1, int(menge))
            elif einheit == "Palette":
                menge = 1

            bemerkung = random.choice([
                "", "", "", "Baufeld West", "OG2", "EG Flur",
                "nach Plan Rev. C", "Treppenhaus", "UG Technik"
            ])

            rows.append([datum, "Elektroinstallation", taetigkeit,
                        arbeiter, stunden, material, menge, einheit, bemerkung])

        total_stunden += tages_stunden
        entries_per_day.append(rows)

    factor = target_stunden / max(total_stunden, 1)
    for day_rows in entries_per_day:
        for row in day_rows:
            row[4] = round(row[4] * factor, 1)

    return dates, entries_per_day


def generate_rohbau_schmidt():
    """Rohbau Schmidt AG — 680 Stunden, ~120.000€ Material"""
    dates = _spread_dates("2025-07", "2025-09", 10)
    entries_per_day = []

    taetigkeiten = [
        ("Betonage Decke OG2", "Beton C25/30", 18, "m³"),
        ("Bewehrung verlegen", "Bewehrungsstahl BSt500", 2800, "kg"),
        ("Schalung Wände OG2", "Schaltafeln Doka", 45, "m²"),
        ("Mauerwerk OG2", "Kalksandstein 24cm", 12, "Palette"),
        ("Betonage Stützen", "Beton C30/37", 6, "m³"),
        ("Bewherung Stützen", "Bewehrungsmatten Q335", 24, "Stk"),
        ("Decke ausschalen", "Deckenstützen mieten", 80, "Stk"),
        ("Sturz einbauen", "Fertigsturz 2,0m", 8, "Stk"),
        ("Ringbalken betonieren", "Beton C25/30", 4.5, "m³"),
        ("Treppen-Fertigteile setzen", "Fertigteiltreppe", 2, "Stk"),
    ]

    total_stunden = 0
    target_stunden = 680

    for i, datum in enumerate(dates):
        rows = []
        n_rows = random.randint(4, 8)
        tages_stunden = 0

        used = random.sample(range(len(taetigkeiten)), min(n_rows, len(taetigkeiten)))
        for j in used:
            taetigkeit, material, menge_base, einheit = taetigkeiten[j]
            arbeiter = random.randint(4, 8)
            stunden = round(random.uniform(6, 10), 1)
            tages_stunden += stunden

            menge = round(menge_base * random.uniform(0.08, 0.2), 1)
            if einheit in ("Stk", "Palette"):
                menge = max(1, int(menge))

            bemerkung = random.choice([
                "", "", "Achse A-D", "OG2 Nordseite",
                "Wetter gut", "lt. Statik Rev.B", "Pumpe 36m"
            ])

            rows.append([datum, "Rohbau", taetigkeit,
                        arbeiter, stunden, material, menge, einheit, bemerkung])

        total_stunden += tages_stunden
        entries_per_day.append(rows)

    factor = target_stunden / max(total_stunden, 1)
    for day_rows in entries_per_day:
        for row in day_rows:
            row[4] = round(row[4] * factor, 1)

    return dates, entries_per_day


def generate_sanitaer_weber():
    """Sanitär Weber — 290 Stunden, ~45.000€ Material"""
    dates = _spread_dates("2025-07", "2025-09", 10)
    entries_per_day = []

    taetigkeiten = [
        ("Steigleitungen montieren", "Kupferrohr 28mm", 120, "m"),
        ("Bad-Installation OG1", "Anschlussgarnitur", 6, "Stk"),
        ("Heizungsrohre verlegen", "Mehrschichtrohr 20mm", 180, "m"),
        ("Abwasserleitungen", "HT-Rohr DN100", 45, "m"),
        ("Armaturen montieren", "Waschtischarmatur", 8, "Stk"),
        ("Fußbodenheizung verlegen", "PE-Xa Rohr 17mm", 240, "m"),
        ("Heizkörper setzen", "Flachheizkörper Typ 22", 4, "Stk"),
        ("Schachtinstallation", "Schallschutzschelle", 32, "Stk"),
        ("Druckprüfung", "Prüfprotokoll", 1, "Stk"),
        ("Regenwasserleitung", "KG-Rohr DN150", 25, "m"),
    ]

    total_stunden = 0
    target_stunden = 290

    for i, datum in enumerate(dates):
        rows = []
        n_rows = random.randint(3, 6)
        tages_stunden = 0

        used = random.sample(range(len(taetigkeiten)), min(n_rows, len(taetigkeiten)))
        for j in used:
            taetigkeit, material, menge_base, einheit = taetigkeiten[j]
            arbeiter = random.randint(2, 3)
            stunden = round(random.uniform(4, 8), 1)
            tages_stunden += stunden

            menge = round(menge_base * random.uniform(0.1, 0.25), 1)
            if einheit == "Stk":
                menge = max(1, int(menge))

            bemerkung = random.choice([
                "", "", "Steigstrang 2", "Bad OG1",
                "Heizraum UG", "nach DIN 1988", "Küche EG"
            ])

            rows.append([datum, "Sanitär/Heizung", taetigkeit,
                        arbeiter, stunden, material, menge, einheit, bemerkung])

        total_stunden += tages_stunden
        entries_per_day.append(rows)

    factor = target_stunden / max(total_stunden, 1)
    for day_rows in entries_per_day:
        for row in day_rows:
            row[4] = round(row[4] * factor, 1)

    return dates, entries_per_day


def generate_dach_krause():
    """Dachdeckerei Krause — 180 Stunden, ~62.000€ Material"""
    dates = _spread_dates("2025-07", "2025-09", 10)
    entries_per_day = []

    taetigkeiten = [
        ("Flachdach Abdichtung", "Bitumenbahn V60S5", 85, "m²"),
        ("Attika verkleiden", "Zinkblech 0,7mm", 24, "m"),
        ("Dämmung verlegen", "PUR-Dämmplatte 160mm", 120, "m²"),
        ("Dampfsperre", "PE-Folie 0,2mm", 130, "m²"),
        ("Dachrandabschluss", "Alu-Randprofil", 38, "m"),
        ("Dachentwässerung", "Dachablauf DN100", 6, "Stk"),
        ("Lichtkuppel einbauen", "Lichtkuppel 120x120", 3, "Stk"),
        ("Attika-Abdichtung", "EPDM-Folie", 45, "m²"),
        ("Kiesschüttung", "Rundkies 16/32", 18, "m³"),
        ("Notüberlauf setzen", "Notablauf Edelstahl", 4, "Stk"),
    ]

    total_stunden = 0
    target_stunden = 180

    for i, datum in enumerate(dates):
        rows = []
        n_rows = random.randint(3, 5)
        tages_stunden = 0

        used = random.sample(range(len(taetigkeiten)), min(n_rows, len(taetigkeiten)))
        for j in used:
            taetigkeit, material, menge_base, einheit = taetigkeiten[j]
            arbeiter = random.randint(2, 4)
            stunden = round(random.uniform(4, 7), 1)
            tages_stunden += stunden

            menge = round(menge_base * random.uniform(0.1, 0.25), 1)
            if einheit == "Stk":
                menge = max(1, int(menge))

            bemerkung = random.choice([
                "", "", "Baufeld Ost", "Dach Hauptgebäude",
                "Wetter trocken nötig", "Anschluss Attika"
            ])

            rows.append([datum, "Dacharbeiten", taetigkeit,
                        arbeiter, stunden, material, menge, einheit, bemerkung])

        total_stunden += tages_stunden
        entries_per_day.append(rows)

    factor = target_stunden / max(total_stunden, 1)
    for day_rows in entries_per_day:
        for row in day_rows:
            row[4] = round(row[4] * factor, 1)

    return dates, entries_per_day


def generate_innenausbau_hoffmann():
    """Innenausbau Hoffmann — 350 Stunden, ~38.000€ Material"""
    dates = _spread_dates("2025-07", "2025-09", 10)
    entries_per_day = []

    taetigkeiten = [
        ("Trockenbau Ständerwerk", "CW-Profil 75mm", 180, "m"),
        ("Gipskarton beplanken", "GKB 12,5mm", 95, "m²"),
        ("Spachteln und schleifen", "Fugenfüller", 25, "kg"),
        ("Estrich einbringen", "Fließestrich CT-C30", 8, "m³"),
        ("Putz auftragen", "Kalkzementputz", 85, "m²"),
        ("Trockenbauwand EG", "Gipskarton-Feuerschutz", 42, "m²"),
        ("Abhangdecke montieren", "Deckenplatte 60x60", 36, "m²"),
        ("Türzargen setzen", "Stahlzarge 875mm", 8, "Stk"),
        ("Sockelleisten", "MDF-Sockelleiste 80mm", 120, "m"),
        ("Estrichranddämmung", "PE-Randstreifen 10mm", 95, "m"),
    ]

    total_stunden = 0
    target_stunden = 350

    for i, datum in enumerate(dates):
        rows = []
        n_rows = random.randint(3, 7)
        tages_stunden = 0

        used = random.sample(range(len(taetigkeiten)), min(n_rows, len(taetigkeiten)))
        for j in used:
            taetigkeit, material, menge_base, einheit = taetigkeiten[j]
            arbeiter = random.randint(2, 5)
            stunden = round(random.uniform(5, 9), 1)
            tages_stunden += stunden

            menge = round(menge_base * random.uniform(0.08, 0.2), 1)
            if einheit == "Stk":
                menge = max(1, int(menge))

            bemerkung = random.choice([
                "", "", "EG Büro", "OG1 Flur",
                "Trocknungszeit beachten", "Brandschutzwand F90"
            ])

            rows.append([datum, "Innenausbau", taetigkeit,
                        arbeiter, stunden, material, menge, einheit, bemerkung])

        total_stunden += tages_stunden
        entries_per_day.append(rows)

    factor = target_stunden / max(total_stunden, 1)
    for day_rows in entries_per_day:
        for row in day_rows:
            row[4] = round(row[4] * factor, 1)

    return dates, entries_per_day


def _spread_dates(start_month: str, end_month: str, count: int) -> list[str]:
    """Verteilt `count` Arbeitstage über den Zeitraum (Mo-Fr)."""
    from datetime import date, timedelta

    year, month_start = map(int, start_month.split("-"))
    _, month_end = map(int, end_month.split("-"))

    start = date(year, month_start, 1)
    if month_end == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month_end + 1, 1) - timedelta(days=1)

    workdays = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            workdays.append(current)
        current += timedelta(days=1)

    selected = sorted(random.sample(workdays, min(count, len(workdays))))
    return [d.isoformat() for d in selected]


def _filename(firma: str, datum: str) -> str:
    """Erstellt Dateinamen im Format subunternehmer_datum.csv"""
    mapping = {
        "Elektro Müller GmbH": "elektro_mueller",
        "Rohbau Schmidt AG": "rohbau_schmidt",
        "Sanitär Weber": "sanitaer_weber",
        "Dachdeckerei Krause": "dach_krause",
        "Innenausbau Hoffmann": "innenausbau_hoffmann",
    }
    prefix = mapping[firma]
    return f"{prefix}_{datum}.csv"


def write_csvs(firma: str, dates: list[str], entries_per_day: list[list]):
    """Schreibt CSV-Dateien für einen Subunternehmer."""
    for datum, rows in zip(dates, entries_per_day):
        filename = _filename(firma, datum)
        filepath = OUTPUT_DIR / filename
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)
            writer.writerows(rows)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for f in OUTPUT_DIR.glob("*.csv"):
        f.unlink()

    print("Generiere ETL-Testdaten für L5-Benchmark...")

    generators = [
        ("Elektro Müller GmbH", generate_elektro_mueller),
        ("Rohbau Schmidt AG", generate_rohbau_schmidt),
        ("Sanitär Weber", generate_sanitaer_weber),
        ("Dachdeckerei Krause", generate_dach_krause),
        ("Innenausbau Hoffmann", generate_innenausbau_hoffmann),
    ]

    total_files = 0
    for firma, gen_fn in generators:
        dates, entries = gen_fn()
        write_csvs(firma, dates, entries)
        total_files += len(dates)
        print(f"  {firma}: {len(dates)} Dateien")

    print(f"\nGesamt: {total_files} CSV-Dateien in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
