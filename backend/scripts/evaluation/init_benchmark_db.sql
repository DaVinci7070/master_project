-- Lumari Benchmark-Datenbank: Realistische Baustellendaten
-- Wird automatisch beim ersten Start des benchmark-db Containers ausgeführt

-- ============================================================
-- Schema
-- ============================================================

CREATE TABLE projekte (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    auftraggeber VARCHAR(150) NOT NULL,
    startdatum DATE NOT NULL,
    enddatum_soll DATE NOT NULL,
    budget_eur NUMERIC(12, 2) NOT NULL
);

CREATE TABLE gewerke (
    id SERIAL PRIMARY KEY,
    projekt_id INTEGER NOT NULL REFERENCES projekte(id),
    name VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'in_arbeit',
    fortschritt_prozent INTEGER NOT NULL DEFAULT 0 CHECK (fortschritt_prozent BETWEEN 0 AND 100),
    verantwortlicher VARCHAR(100) NOT NULL
);

CREATE TABLE tagesberichte (
    id SERIAL PRIMARY KEY,
    gewerk_id INTEGER NOT NULL REFERENCES gewerke(id),
    datum DATE NOT NULL,
    wetter VARCHAR(100),
    arbeiter_anzahl INTEGER NOT NULL DEFAULT 0,
    beschreibung TEXT NOT NULL,
    stunden NUMERIC(5, 1) NOT NULL DEFAULT 0
);

CREATE TABLE maengel (
    id SERIAL PRIMARY KEY,
    gewerk_id INTEGER NOT NULL REFERENCES gewerke(id),
    datum DATE NOT NULL,
    beschreibung TEXT NOT NULL,
    schweregrad VARCHAR(20) NOT NULL CHECK (schweregrad IN ('gering', 'mittel', 'kritisch')),
    status VARCHAR(30) NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'in_bearbeitung', 'behoben')),
    frist DATE
);

CREATE TABLE kosten (
    id SERIAL PRIMARY KEY,
    gewerk_id INTEGER NOT NULL REFERENCES gewerke(id),
    datum DATE NOT NULL,
    kategorie VARCHAR(80) NOT NULL,
    betrag_eur NUMERIC(10, 2) NOT NULL,
    beleg_nr VARCHAR(50)
);

-- ============================================================
-- Projekt 1: Neubau Wohnanlage Bergstraße 12
-- ============================================================

INSERT INTO projekte (id, name, auftraggeber, startdatum, enddatum_soll, budget_eur)
VALUES (1, 'Neubau Wohnanlage Bergstraße 12', 'Bauträger Rheinland GmbH', '2025-11-01', '2026-08-31', 2850000.00);

-- Gewerke Projekt 1
INSERT INTO gewerke (id, projekt_id, name, status, fortschritt_prozent, verantwortlicher) VALUES
(1, 1, 'Rohbau', 'in_arbeit', 85, 'Polier Krause'),
(2, 1, 'Elektroinstallation', 'verzögert', 35, 'Meister Hoffmann'),
(3, 1, 'Sanitär/Heizung', 'in_arbeit', 55, 'Meister Weber'),
(4, 1, 'Dacharbeiten', 'in_arbeit', 70, 'Dachdecker Schulz'),
(5, 1, 'Fassade', 'geplant', 10, 'Vorarbeiter Becker'),
(6, 1, 'Innenausbau', 'geplant', 5, 'Meister Friedrich');

-- Projekt 2
INSERT INTO projekte (id, name, auftraggeber, startdatum, enddatum_soll, budget_eur)
VALUES (2, 'Sanierung Grundschule Am Park', 'Stadtverwaltung Neustadt', '2025-12-15', '2026-07-15', 1450000.00);

-- Gewerke Projekt 2
INSERT INTO gewerke (id, projekt_id, name, status, fortschritt_prozent, verantwortlicher) VALUES
(7, 2, 'Abbruch/Entkernung', 'abgeschlossen', 100, 'Polier Hartmann'),
(8, 2, 'Rohbau/Mauerwerk', 'in_arbeit', 60, 'Polier Neumann'),
(9, 2, 'Elektroinstallation', 'in_arbeit', 40, 'Meister Klein'),
(10, 2, 'Sanitär', 'in_arbeit', 30, 'Meister Richter'),
(11, 2, 'Fenster/Türen', 'in_arbeit', 45, 'Monteur Lange'),
(12, 2, 'Bodenbeläge', 'geplant', 0, 'Fliesenleger Vogel');

-- ============================================================
-- Tagesberichte Projekt 1 — Rohbau (Gewerk 1)
-- 3 Monate: Februar bis April 2026
-- ============================================================

INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
-- Februar 2026
(1, '2026-02-02', 'bewölkt, 3°C', 8, 'Fundamentarbeiten Block B abgeschlossen. Schalung Keller aufgestellt.', 64.0),
(1, '2026-02-03', 'Regen, 4°C', 5, 'Bewehrung Kellergeschoss eingebaut, Arbeiten wegen Regen teilweise unterbrochen.', 35.0),
(1, '2026-02-04', 'bewölkt, 2°C', 8, 'Betonage Kellersohle Block B (45 m³ C30/37). Verdichtung mit Innenrüttler.', 68.0),
(1, '2026-02-05', 'sonnig, 5°C', 7, 'Schalung Kellerwände aufgestellt, Bewehrung begonnen.', 56.0),
(1, '2026-02-06', 'bewölkt, 1°C', 8, 'Bewehrung Kellerwände fertiggestellt. Betonpumpe für Montag bestellt.', 64.0),
(1, '2026-02-09', 'sonnig, 6°C', 9, 'Betonage Kellerwände (60 m³). Glatte Oberfläche erzielt.', 72.0),
(1, '2026-02-10', 'bewölkt, 4°C', 7, 'Ausschalung nach 24h. Nachbehandlung mit Folie. Qualität gut.', 49.0),
(1, '2026-02-11', 'Frost, -2°C', 4, 'Nur Sicherungsarbeiten wegen Frost. Heizung Kellerbereich aufgestellt.', 24.0),
(1, '2026-02-12', 'bewölkt, 3°C', 8, 'Schalung Bodenplatte EG vorbereitet. PE-Folie und Dämmung verlegt.', 64.0),
(1, '2026-02-13', 'sonnig, 7°C', 9, 'Bewehrung Bodenplatte EG. 12 t Stahl verbaut. Abnahme durch Statiker.', 72.0),
(1, '2026-02-16', 'bewölkt, 5°C', 10, 'Betonage Bodenplatte EG (85 m³ C25/30). Betonpumpe 36m. Glättung.', 80.0),
(1, '2026-02-17', 'Regen, 6°C', 3, 'Nachbehandlung Bodenplatte. Folienabdeckung. Materialplanung OG.', 21.0),
(1, '2026-02-18', 'bewölkt, 4°C', 8, 'Mauerwerk EG Außenwände begonnen. Poroton T7 36,5cm.', 64.0),
(1, '2026-02-19', 'sonnig, 8°C', 8, 'Mauerwerk EG fortgesetzt. 2. Schicht fertig. Sturzeinbau Fenster.', 64.0),
(1, '2026-02-20', 'bewölkt, 6°C', 8, 'Mauerwerk EG Innenwände. KS-Steine 17,5cm. Türöffnungen ausgespart.', 64.0),
(1, '2026-02-23', 'sonnig, 9°C', 8, 'Mauerwerk EG abgeschlossen. Ringbalken Schalung aufgestellt.', 64.0),
(1, '2026-02-24', 'bewölkt, 7°C', 9, 'Ringbalken EG betoniert. Deckenplanung mit Fertigteilwerk abgestimmt.', 63.0),
(1, '2026-02-25', 'bewölkt, 5°C', 8, 'Filigrandecken EG angeliefert und eingehoben. Kran 50t.', 64.0),
(1, '2026-02-26', 'sonnig, 10°C', 9, 'Aufbeton Decke EG (35 m³). Bewehrung Zulage. Elektro-Leerrohre eingelegt.', 72.0),
(1, '2026-02-27', 'bewölkt, 8°C', 7, 'Nachbehandlung Decke EG. Abstützung kontrolliert. Wochenabschluss.', 49.0),
-- März 2026
(1, '2026-03-02', 'sonnig, 11°C', 9, 'Mauerwerk 1.OG begonnen. Außenwände bis 1. Schicht.', 72.0),
(1, '2026-03-03', 'bewölkt, 9°C', 9, 'Mauerwerk 1.OG fortgesetzt. Fensteröffnungen und Stürze.', 72.0),
(1, '2026-03-04', 'Regen, 7°C', 6, 'Arbeiten teilweise unterbrochen. Innenwände 1.OG.', 42.0),
(1, '2026-03-05', 'bewölkt, 8°C', 9, 'Mauerwerk 1.OG fast fertig. Ringbalken vorbereitet.', 72.0),
(1, '2026-03-06', 'sonnig, 12°C', 9, 'Ringbalken 1.OG betoniert. Mauerwerk 1.OG abgeschlossen.', 72.0),
(1, '2026-03-09', 'bewölkt, 10°C', 9, 'Filigrandecken 1.OG eingehoben. Bewehrung Aufbeton.', 72.0),
(1, '2026-03-10', 'sonnig, 13°C', 10, 'Aufbeton Decke 1.OG (35 m³). Einbauteile gesetzt.', 80.0),
(1, '2026-03-11', 'bewölkt, 11°C', 7, 'Nachbehandlung Decke 1.OG. Abstützung gesetzt.', 49.0),
(1, '2026-03-12', 'sonnig, 14°C', 9, 'Mauerwerk 2.OG Außenwände begonnen.', 72.0),
(1, '2026-03-13', 'bewölkt, 12°C', 9, 'Mauerwerk 2.OG fortgesetzt. Guter Fortschritt.', 72.0),
(1, '2026-03-16', 'sonnig, 15°C', 9, 'Mauerwerk 2.OG Innenwände. Installationsschächte ausgespart.', 72.0),
(1, '2026-03-17', 'bewölkt, 13°C', 9, 'Ringbalken 2.OG. Mauerwerk abgeschlossen.', 72.0),
(1, '2026-03-18', 'sonnig, 16°C', 10, 'Filigrandecken 2.OG. Aufbeton vorbereitet.', 80.0),
(1, '2026-03-19', 'bewölkt, 14°C', 10, 'Aufbeton Decke 2.OG (35 m³). Letzte Geschossdecke.', 80.0),
(1, '2026-03-20', 'sonnig, 15°C', 7, 'Nachbehandlung. Abstützung. Wochenplanung Dachgeschoss.', 49.0),
(1, '2026-03-23', 'bewölkt, 12°C', 8, 'Drempel Dachgeschoss gemauert. Giebelwände begonnen.', 64.0),
(1, '2026-03-24', 'Regen, 10°C', 5, 'Giebelwände fortgesetzt, nachmittags Regen.', 35.0),
(1, '2026-03-25', 'sonnig, 14°C', 8, 'Giebelwände fertiggestellt. Rohbau zu 85% abgeschlossen.', 64.0),
-- April 2026
(1, '2026-04-01', 'sonnig, 16°C', 6, 'Restarbeiten Rohbau: Schornsteinköpfe, Attika.', 48.0),
(1, '2026-04-02', 'bewölkt, 14°C', 6, 'Lichtschächte betoniert. Kellertreppen nachgebessert.', 48.0),
(1, '2026-04-03', 'sonnig, 17°C', 5, 'Feinarbeiten Rohbau. Durchbrüche für Haustechnik gebohrt.', 40.0);

-- Tagesberichte Projekt 1 — Elektro (Gewerk 2) — verzögert wegen Materialengpass
INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(2, '2026-03-02', 'sonnig, 11°C', 3, 'Leerrohrverlegung EG begonnen. Schlitze gestemmt.', 24.0),
(2, '2026-03-03', 'bewölkt, 9°C', 3, 'Leerrohrverlegung EG Wohnungen 1-3.', 24.0),
(2, '2026-03-04', 'Regen, 7°C', 2, 'UP-Dosen gesetzt EG. Verteilervorbereitung.', 16.0),
(2, '2026-03-09', 'bewölkt, 10°C', 3, 'Kabel eingezogen EG teilweise. Lieferung NYM fehlt.', 24.0),
(2, '2026-03-10', 'sonnig, 13°C', 2, 'WARTEZEIT: NYM-Kabel 5x2,5 nicht lieferbar. Lieferant meldet 3 Wochen Verzug.', 8.0),
(2, '2026-03-11', 'bewölkt, 11°C', 1, 'Nur Planungsarbeiten. Alternativlieferant kontaktiert.', 8.0),
(2, '2026-03-16', 'sonnig, 15°C', 2, 'Teillieferung NYM 3x1,5 eingetroffen. Kabel EG eingezogen.', 16.0),
(2, '2026-03-17', 'bewölkt, 13°C', 3, 'Schalter und Steckdosen EG montiert. 1.OG Schlitze begonnen.', 24.0),
(2, '2026-03-23', 'bewölkt, 12°C', 3, 'Leerrohre 1.OG. Immer noch kein NYM 5x2,5 verfügbar.', 24.0),
(2, '2026-03-30', 'sonnig, 18°C', 3, 'Restliche Kabel EG. NYM 5x2,5 endlich eingetroffen (4 Wochen Verzug).', 24.0),
(2, '2026-04-01', 'sonnig, 16°C', 4, 'Kabel 1.OG eingezogen. Aufholjagd begonnen.', 32.0),
(2, '2026-04-02', 'bewölkt, 14°C', 4, 'Verteilung 1.OG verdrahtet. UP-Dosen gesetzt.', 32.0),
(2, '2026-04-03', 'sonnig, 17°C', 4, '1.OG Schalter/Steckdosen teilweise montiert. 2.OG Schlitze.', 32.0);

-- Tagesberichte Projekt 1 — Sanitär (Gewerk 3)
INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(3, '2026-02-23', 'sonnig, 9°C', 3, 'Grundleitungen Keller verlegt. KG-Rohr DN 100/150.', 24.0),
(3, '2026-02-24', 'bewölkt, 7°C', 3, 'Fallleitungen EG montiert. Schallschutzschellen.', 24.0),
(3, '2026-03-02', 'sonnig, 11°C', 4, 'Steigeleitungen Heizung bis 2.OG. Kupferrohr gepresst.', 32.0),
(3, '2026-03-03', 'bewölkt, 9°C', 4, 'Fußbodenheizung EG Wohnung 1-2 verlegt.', 32.0),
(3, '2026-03-09', 'bewölkt, 10°C', 4, 'Fußbodenheizung EG Wohnung 3 + 1.OG Wohnung 1.', 32.0),
(3, '2026-03-10', 'sonnig, 13°C', 4, 'Fußbodenheizung 1.OG Wohnung 2-3.', 32.0),
(3, '2026-03-16', 'sonnig, 15°C', 3, 'Trinkwasserleitungen EG. Edelstahl Pressfittings.', 24.0),
(3, '2026-03-17', 'bewölkt, 13°C', 3, 'Trinkwasserleitungen 1.OG. Druckprüfung EG bestanden.', 24.0),
(3, '2026-03-23', 'bewölkt, 12°C', 4, 'Fußbodenheizung 2.OG komplett. Heizkreisverteiler montiert.', 32.0),
(3, '2026-03-30', 'sonnig, 18°C', 3, 'Abwasserleitungen 2.OG angeschlossen. Dichtigkeitsprüfung OK.', 24.0),
(3, '2026-04-01', 'sonnig, 16°C', 3, 'Heizungsverteiler Keller montiert. Wärmepumpenanschluss vorbereitet.', 24.0),
(3, '2026-04-02', 'bewölkt, 14°C', 4, 'Regenentwässerung Dach vorbereitet. Rohre bis Fallleitung.', 32.0);

-- Tagesberichte Projekt 1 — Dach (Gewerk 4)
INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(4, '2026-03-25', 'sonnig, 14°C', 6, 'Dachstuhl aufgerichtet. Sparren montiert. Zimmermannsmäßige Verbindungen.', 48.0),
(4, '2026-03-26', 'bewölkt, 12°C', 6, 'Konterlattung und Unterspannbahn. Dampfbremse innen.', 48.0),
(4, '2026-03-27', 'sonnig, 15°C', 6, 'Lattung. Dachfenster-Ausschnitte. Gauben Unterkonstruktion.', 48.0),
(4, '2026-03-30', 'sonnig, 18°C', 5, 'Dacheindeckung Südseite begonnen. Tondachziegel Braas Rubin.', 40.0),
(4, '2026-03-31', 'bewölkt, 15°C', 5, 'Dacheindeckung Südseite abgeschlossen. First und Grat.', 40.0),
(4, '2026-04-01', 'sonnig, 16°C', 5, 'Dacheindeckung Nordseite. Schneefanggitter montiert.', 40.0),
(4, '2026-04-02', 'bewölkt, 14°C', 4, 'Dachfenster eingebaut (8 Stück Velux). Anschlüsse.', 32.0),
(4, '2026-04-03', 'sonnig, 17°C', 4, 'Gauben verkleidet. Traufbleche montiert. Ca. 70% fertig.', 32.0);

-- Tagesberichte Projekt 1 — Fassade (Gewerk 5)
INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(5, '2026-04-01', 'sonnig, 16°C', 3, 'Gerüst aufgestellt. WDVS-Planung abgestimmt. Dämmstofflieferung bestellt.', 24.0),
(5, '2026-04-02', 'bewölkt, 14°C', 2, 'Sockelschiene montiert. Erdberührte Dämmung (XPS) verklebt.', 16.0),
(5, '2026-04-03', 'sonnig, 17°C', 3, 'WDVS EG Südseite begonnen. EPS 160mm verklebt und verdübelt.', 24.0);

-- ============================================================
-- Tagesberichte Projekt 2 — Sanierung Grundschule Am Park
-- ============================================================

-- Abbruch (Gewerk 7) — abgeschlossen
INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(7, '2026-01-06', 'bewölkt, 2°C', 6, 'Entkernung Gebäudeflügel Ost begonnen. Alte Böden entfernt.', 48.0),
(7, '2026-01-07', 'Regen, 3°C', 5, 'Entkernung Flügel Ost fortgesetzt. Schadstoffprobe Linoleum unauffällig.', 40.0),
(7, '2026-01-08', 'bewölkt, 1°C', 6, 'Alte Sanitärinstallation demontiert. Abfuhr Container 1+2.', 48.0),
(7, '2026-01-09', 'sonnig, 4°C', 6, 'Entkernung Flügel West. Alte Deckenplatten entfernt.', 48.0),
(7, '2026-01-10', 'bewölkt, 2°C', 6, 'Entkernung abgeschlossen. Rohbausubstanz freigelegt. Statiker-Begehung.', 48.0),
(7, '2026-01-13', 'Frost, -3°C', 4, 'Restabbruch Nebengebäude. Fundament freigelegt. Altlasten: negativ.', 32.0),
(7, '2026-01-14', 'bewölkt, 0°C', 5, 'Aufräumarbeiten. Letzte Container abgefahren. Abbruch vollständig abgeschlossen.', 40.0);

-- Rohbau/Mauerwerk Projekt 2 (Gewerk 8)
INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(8, '2026-01-20', 'bewölkt, 3°C', 5, 'Neue Innenwände Flügel Ost begonnen. Porenbeton d=11,5cm.', 40.0),
(8, '2026-01-21', 'sonnig, 5°C', 5, 'Innenwände Flügel Ost fortgesetzt. Türöffnungen ausgespart.', 40.0),
(8, '2026-01-22', 'bewölkt, 4°C', 5, 'Deckenöffnungen für neue Treppe geschnitten. Bewehrung freigelegt.', 40.0),
(8, '2026-01-27', 'bewölkt, 2°C', 6, 'Neue Treppe betoniert. Schalung + Bewehrung + Betonage in einem Tag.', 54.0),
(8, '2026-01-28', 'sonnig, 6°C', 5, 'Innenwände Flügel West begonnen.', 40.0),
(8, '2026-02-03', 'Regen, 4°C', 4, 'Innenwände Flügel West fortgesetzt. Nachmittags Regen, nur innen gearbeitet.', 32.0),
(8, '2026-02-04', 'bewölkt, 2°C', 6, 'Sturz- und Ringbalkenarbeiten Flügel Ost. Stahlbetonfertigteile.', 48.0),
(8, '2026-02-10', 'bewölkt, 4°C', 5, 'Neue Stahlstützen Aula eingebaut. Brandschutzbeschichtung.', 40.0),
(8, '2026-02-17', 'Regen, 6°C', 4, 'Estrichvorbereitung Flügel Ost. Dämmung und PE-Folie.', 32.0),
(8, '2026-02-24', 'bewölkt, 7°C', 6, 'Fließestrich Flügel Ost eingebracht. CT-C30-F5, 65mm.', 48.0),
(8, '2026-03-03', 'bewölkt, 9°C', 5, 'Estrich Flügel West. Aufheizprotokoll Flügel Ost begonnen.', 40.0),
(8, '2026-03-10', 'sonnig, 13°C', 4, 'Putzarbeiten Flügel Ost begonnen. Maschinenputz Kalkzement.', 32.0),
(8, '2026-03-17', 'bewölkt, 13°C', 5, 'Putzarbeiten fortgesetzt. Flügel Ost fast fertig.', 40.0),
(8, '2026-03-24', 'Regen, 10°C', 4, 'Putzarbeiten Flügel West. Fortschritt 60%.', 32.0);

-- Elektro Projekt 2 (Gewerk 9)
INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(9, '2026-02-03', 'Regen, 4°C', 3, 'Neue Hauptverteilung gesetzt. Zählerplatz umgebaut nach TAB.', 24.0),
(9, '2026-02-10', 'bewölkt, 4°C', 4, 'Kabeltrassen in Fluren verlegt. Brandschotts vorbereitet.', 32.0),
(9, '2026-02-17', 'Regen, 6°C', 3, 'Klassenzimmer Flügel Ost verkabelt. Doppelsteckdosen und Datendosen.', 24.0),
(9, '2026-02-24', 'bewölkt, 7°C', 3, 'Beleuchtung Flügel Ost. LED-Panels eingebaut.', 24.0),
(9, '2026-03-03', 'bewölkt, 9°C', 4, 'Flügel West Elektro begonnen. Brandmeldeanlage Leitungen.', 32.0),
(9, '2026-03-10', 'sonnig, 13°C', 3, 'Brandmeldeanlage Melder gesetzt. EDV-Verkabelung Serverraum.', 24.0),
(9, '2026-03-17', 'bewölkt, 13°C', 4, 'Beleuchtung Flügel West. Notbeleuchtung Fluchtwege.', 32.0),
(9, '2026-03-24', 'Regen, 10°C', 3, 'Außenbeleuchtung Schulhof. Erdkabel verlegt.', 24.0),
(9, '2026-04-01', 'sonnig, 16°C', 3, 'Sprechanlage und Türöffner. Intercom Sekretariat-Eingang.', 24.0);

-- Sanitär Projekt 2 (Gewerk 10)
INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(10, '2026-02-10', 'bewölkt, 4°C', 3, 'Neue Steigeleitungen Toilettentrakt. Edelstahl Trinkwasser.', 24.0),
(10, '2026-02-17', 'Regen, 6°C', 3, 'Toilettenanlagen Flügel Ost Vorwandinstallation.', 24.0),
(10, '2026-02-24', 'bewölkt, 7°C', 4, 'WC-Keramik und Waschtische Flügel Ost montiert.', 32.0),
(10, '2026-03-03', 'bewölkt, 9°C', 3, 'Heizungsleitungen Flügel West erneuert. Alte Radiatoren demontiert.', 24.0),
(10, '2026-03-10', 'sonnig, 13°C', 3, 'Neue Plattenheizkörper Flügel West montiert.', 24.0),
(10, '2026-03-17', 'bewölkt, 13°C', 4, 'Toilettentrakt Flügel West Rohinstallation.', 32.0),
(10, '2026-03-24', 'Regen, 10°C', 3, 'Druckprüfung Trinkwasser Flügel West bestanden.', 24.0);

-- Fenster/Türen Projekt 2 (Gewerk 11)
INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(11, '2026-02-17', 'Regen, 6°C', 4, 'Fensteraustausch Flügel Ost begonnen. 3-fach Verglasung Uw=0,9.', 32.0),
(11, '2026-02-18', 'bewölkt, 4°C', 4, 'Fensteraustausch Flügel Ost fortgesetzt. 12 von 28 Fenstern eingebaut.', 32.0),
(11, '2026-02-19', 'sonnig, 8°C', 4, 'Fensteraustausch Flügel Ost abgeschlossen. RAL-Montage. Schaumfugen.', 32.0),
(11, '2026-03-02', 'sonnig, 11°C', 4, 'Fensteraustausch Flügel West begonnen. 22 Fenster geplant.', 32.0),
(11, '2026-03-03', 'bewölkt, 9°C', 4, 'Flügel West fortgesetzt. 10 Fenster eingebaut.', 32.0),
(11, '2026-03-04', 'Regen, 7°C', 3, 'Flügel West: restliche 12 Fenster. Abdichtung außen.', 24.0),
(11, '2026-03-10', 'sonnig, 13°C', 3, 'Innentüren Flügel Ost eingebaut. Brandschutztüren T30.', 24.0),
(11, '2026-03-17', 'bewölkt, 13°C', 3, 'Innentüren Flügel West. Haupteingang neue Automatiktür.', 24.0),
(11, '2026-03-24', 'Regen, 10°C', 2, 'Restarbeiten Türen. Beschläge, Türschließer, Panikschlösser Fluchttüren.', 16.0);

-- ============================================================
-- Zusätzliche Tagesberichte — Innenausbau Projekt 1 (Gewerk 6)
-- ============================================================

INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(6, '2026-03-30', 'sonnig, 18°C', 4, 'Trockenbau EG begonnen. Ständerwerk CW75 in Wohnungen 1-2 aufgestellt.', 32.0),
(6, '2026-03-31', 'bewölkt, 15°C', 4, 'Ständerwerk EG Wohnungen 3-4. Installationsebene Sanitärwand.', 32.0),
(6, '2026-04-01', 'sonnig, 16°C', 5, 'Beplankung EG Wohnung 1 einseitig. Mineralwolle eingelegt. Akustik-Profile.', 40.0),
(6, '2026-04-02', 'bewölkt, 14°C', 5, 'Beplankung EG Wohnung 2-3 einseitig. Installationen laufen parallel.', 40.0),
(6, '2026-04-03', 'sonnig, 17°C', 5, 'Beplankung EG Wohnung 1-2 beidseitig abgeschlossen. Spachteln vorbereitet.', 40.0),
(6, '2026-04-06', 'bewölkt, 13°C', 4, 'Spachtelarbeiten EG Q3-Qualität. Fugen und Schrauben verspachtelt.', 32.0),
(6, '2026-04-07', 'sonnig, 15°C', 4, 'Spachteln EG fortgesetzt. Trocknungszeit beachten. 2. Spachtelgang.', 32.0),
(6, '2026-04-08', 'Regen, 12°C', 3, 'Schleifen und Grundieren EG Wohnung 1. Trockenbau 1.OG Aufmaß.', 24.0),
(6, '2026-04-09', 'bewölkt, 14°C', 5, 'Ständerwerk 1.OG begonnen. EG Wohnung 2 schleifen + grundieren.', 40.0),
(6, '2026-04-10', 'sonnig, 16°C', 5, 'Ständerwerk 1.OG Wohnungen 1-3 komplett. Mineralwolle bestellt.', 40.0),
(6, '2026-04-13', 'bewölkt, 15°C', 5, 'Beplankung 1.OG begonnen. Feuchtraumplatten Bad/WC (grün imprägniert).', 40.0),
(6, '2026-04-14', 'sonnig, 17°C', 5, 'Beplankung 1.OG Wohnungen 1-2 fertig. Revisionsklappe HWR eingebaut.', 40.0),
(6, '2026-04-15', 'bewölkt, 14°C', 4, 'Deckenabhängungen Flure für LED-Spots. Rigips auf Direktabhänger.', 32.0),
(6, '2026-04-16', 'sonnig, 18°C', 4, 'Spachteln 1.OG Wohnung 1. Malerarbeiten EG Wohnung 1 (Grundanstrich).', 32.0),
(6, '2026-04-17', 'bewölkt, 15°C', 6, 'Maler EG Wohnung 1 Decken + Wände weiß. Trockenbau 2.OG Aufmaß.', 48.0),
(6, '2026-04-20', 'sonnig, 19°C', 5, 'Ständerwerk 2.OG begonnen. Maler EG Wohnung 2 (2. Anstrich).', 40.0),
(6, '2026-04-21', 'bewölkt, 16°C', 5, 'Beplankung 2.OG Nassräume. Maler EG Wohnung 3.', 40.0),
(6, '2026-04-22', 'Regen, 13°C', 4, 'Spachteln 1.OG fortgesetzt. EG Türzargen setzen (Stahlzargen).', 32.0),
(6, '2026-04-23', 'bewölkt, 15°C', 5, 'Estricharbeiten EG vorbereitet: Randdämmstreifen, Trennlage PE-Folie.', 40.0),
(6, '2026-04-24', 'sonnig, 18°C', 6, 'Fließestrich EG (CT-C30-F5, 55mm). Heizestrich. Raumtemperatur 14°C.', 48.0);

-- ============================================================
-- Zusätzliche Tagesberichte — Mehr Tiefe Sanitär Projekt 1 (Gewerk 3)
-- ============================================================

INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(3, '2026-04-06', 'bewölkt, 13°C', 3, 'Wärmepumpe (Luft-Wasser, 12kW) angeliefert und aufgestellt. Fundamentplatte OK.', 24.0),
(3, '2026-04-07', 'sonnig, 15°C', 4, 'Wärmepumpe hydraulisch angeschlossen. Pufferspeicher 500L montiert.', 32.0),
(3, '2026-04-08', 'Regen, 12°C', 3, 'Frischwasserstation montiert. Zirkulation Trinkwasser warm eingerichtet.', 24.0),
(3, '2026-04-09', 'bewölkt, 14°C', 4, 'Sanitärobjekte EG Wohnung 1: WC, Waschtisch, Dusche, Badewanne montiert.', 32.0),
(3, '2026-04-10', 'sonnig, 16°C', 4, 'Sanitärobjekte EG Wohnung 2-3. Silikonfugen. Dichtbänder Dusche.', 32.0),
(3, '2026-04-13', 'bewölkt, 15°C', 3, 'Sanitärobjekte 1.OG Wohnung 1-2. Vorwandtechnik komplett.', 24.0),
(3, '2026-04-14', 'sonnig, 17°C', 3, 'Heizungseinregulierung EG. Durchflussmengen eingestellt. Protokoll erstellt.', 24.0),
(3, '2026-04-15', 'bewölkt, 14°C', 4, 'Sanitärobjekte 1.OG Wohnung 3. Küchen-Anschlüsse (Spüle, GS).', 32.0),
(3, '2026-04-16', 'sonnig, 18°C', 3, 'Druckprüfung Heizung gesamtes Gebäude: 3 bar, 2h Standzeit — bestanden.', 24.0),
(3, '2026-04-17', 'bewölkt, 15°C', 3, 'Sanitärobjekte 2.OG begonnen. Regenwasserleitung Dach final angeschlossen.', 24.0);

-- ============================================================
-- Zusätzliche Tagesberichte — Mehr Tiefe Elektro Projekt 1 (Gewerk 2)
-- ============================================================

INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(2, '2026-04-06', 'bewölkt, 13°C', 4, '2.OG Leerrohre verlegt. Schlitze gefräst. Verteilerschrank gesetzt.', 32.0),
(2, '2026-04-07', 'sonnig, 15°C', 4, '2.OG Kabel eingezogen (NYM 3x1,5 + 5x2,5). UP-Dosen gesetzt.', 32.0),
(2, '2026-04-08', 'Regen, 12°C', 3, 'Hauptverteilung Keller verdrahtet. Zählerplatz nach TAB vorbereitet.', 24.0),
(2, '2026-04-09', 'bewölkt, 14°C', 4, 'Starkstrom Küchen (Herd 5x2,5). Sprechanlage Leitungen gezogen.', 32.0),
(2, '2026-04-10', 'sonnig, 16°C', 4, 'Netzwerk Cat6a alle Wohnungen. Multimediadosen gesetzt. Patchpanel Keller.', 32.0),
(2, '2026-04-13', 'bewölkt, 15°C', 4, 'Außenbeleuchtung Tiefgarage. Bewegungsmelder Hausflur. Klingeltableau.', 32.0),
(2, '2026-04-14', 'sonnig, 17°C', 5, 'E-Check EG: Isolationsmessung, Schleifenimpedanz, FI-Prüfung — bestanden.', 40.0),
(2, '2026-04-15', 'bewölkt, 14°C', 3, 'Photovoltaik-Vorbereitung: Wechselrichter-Platz Keller, DC-Leitungen Dach.', 24.0),
(2, '2026-04-16', 'sonnig, 18°C', 4, 'E-Check 1.OG bestanden. Schalter/Steckdosen 2.OG montiert (Busch-Jaeger).', 32.0),
(2, '2026-04-17', 'bewölkt, 15°C', 4, 'Gegensprechanlage montiert + programmiert. Elektro-Prüfprotokoll 2.OG.', 32.0);

-- ============================================================
-- Zusätzliche Tagesberichte — Fassade Projekt 1 (Gewerk 5)
-- ============================================================

INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(5, '2026-04-06', 'bewölkt, 13°C', 4, 'WDVS EG Westseite. Verklebung + Verdübelung EPS 160mm.', 32.0),
(5, '2026-04-07', 'sonnig, 15°C', 4, 'WDVS EG Nordseite. Fensterlaibungen mit XPS 30mm gedämmt.', 32.0),
(5, '2026-04-08', 'Regen, 12°C', 2, 'Arbeiten ruhen wegen Nässe (Kleber nicht verarbeitbar bei Regen).', 8.0),
(5, '2026-04-09', 'bewölkt, 14°C', 4, 'WDVS 1.OG Südseite. Brandriegel aus Mineralwolle über Fenster.', 32.0),
(5, '2026-04-10', 'sonnig, 16°C', 4, 'WDVS 1.OG West + Nord. Guter Fortschritt. Gerüstumfahrten.', 32.0),
(5, '2026-04-13', 'bewölkt, 15°C', 5, 'WDVS 2.OG komplett verklebt. Armierungsschicht EG Südseite.', 40.0),
(5, '2026-04-14', 'sonnig, 17°C', 5, 'Armierungsschicht EG + 1.OG. Gewebeeinlage diagonal an Ecken.', 40.0),
(5, '2026-04-15', 'bewölkt, 14°C', 4, 'Armierungsschicht 2.OG. Trocknung abwarten (min. 3 Tage vor Putz).', 32.0),
(5, '2026-04-20', 'sonnig, 19°C', 5, 'Oberputz EG Südseite (Silikonharzputz 2mm Korn, RAL 9010 reinweiß).', 40.0),
(5, '2026-04-21', 'bewölkt, 16°C', 5, 'Oberputz EG West + Nord. Sockel: Mosaikputz grau.', 40.0),
(5, '2026-04-22', 'Regen, 13°C', 0, 'Putzarbeiten Pause — Regen. Abdeckungen kontrolliert.', 0.0),
(5, '2026-04-23', 'bewölkt, 15°C', 5, 'Oberputz 1.OG + 2.OG. Fassade zu ca. 75% fertig.', 40.0);

-- ============================================================
-- Zusätzliche Tagesberichte — Dach Projekt 1 (Gewerk 4)
-- ============================================================

INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(4, '2026-04-06', 'bewölkt, 13°C', 3, 'Dachdämmung zwischen Sparren (Mineralwolle WLG 035, 180mm).', 24.0),
(4, '2026-04-07', 'sonnig, 15°C', 3, 'Dachdämmung fortgesetzt. Dampfbremse innen verklebt (Intello Plus).', 24.0),
(4, '2026-04-08', 'Regen, 12°C', 2, 'Nur Innenarbeiten: Dampfbremse Anschlüsse Wand/Fenster. Dichtheitstest.', 16.0),
(4, '2026-04-09', 'bewölkt, 14°C', 4, 'Schornsteineinfassung Blei. Dachrinnen komplett montiert (Kupfer).', 32.0),
(4, '2026-04-10', 'sonnig, 16°C', 3, 'Dachflächenfenster Eindeckrahmen nachgedichtet. Restarbeiten Ziegel First.', 24.0);

-- ============================================================
-- Zusätzliche Tagesberichte — Bodenbeläge Projekt 2 (Gewerk 12)
-- ============================================================

INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(12, '2026-04-01', 'sonnig, 16°C', 3, 'Estrichprüfung Flügel Ost: CM-Messung 1,8% (max 2,0% für Fliesen — OK).', 24.0),
(12, '2026-04-02', 'bewölkt, 14°C', 4, 'Fliesen Toilettentrakt Ost: Bodenfliesen R10 rutschhemmend. Kreuzfuge 3mm.', 32.0),
(12, '2026-04-03', 'sonnig, 17°C', 4, 'Fliesen Toilettentrakt Ost fortgesetzt. Wandfliesen halbhoch (1,50m).', 32.0),
(12, '2026-04-06', 'bewölkt, 13°C', 4, 'Fliesen Toilettentrakt Ost fertig. Fugen Epoxidharz (feuchtebest��ndig).', 32.0),
(12, '2026-04-07', 'sonnig, 15°C', 3, 'Linoleum Klassenräume Flügel Ost: Untergrund gespachtelt (Nivelliermasse).', 24.0),
(12, '2026-04-08', 'Regen, 12°C', 3, 'Nivelliermasse Flügel Ost fertig. 24h Trocknungszeit.', 24.0),
(12, '2026-04-09', 'bewölkt, 14°C', 4, 'Linoleum Klassenräume 1-3 verlegt. Bahnenware verklebt. Nahtverschweißung.', 32.0),
(12, '2026-04-10', 'sonnig, 16°C', 4, 'Linoleum Klassenräume 4-5 + Lehrerzimmer. Sockelleisten.', 32.0),
(12, '2026-04-13', 'bewölkt, 15°C', 3, 'Fliesen Toilettentrakt West begonnen. Abdichtung unter Fliesen (Verbundabdichtung).', 24.0),
(12, '2026-04-14', 'sonnig, 17°C', 4, 'Fliesen Toilettentrakt West Böden. Bodenablauf eingepasst.', 32.0),
(12, '2026-04-15', 'bewölkt, 14°C', 4, 'Fliesen Toilettentrakt West fertig. Fugen + Silikon Sanitärobjekte.', 32.0),
(12, '2026-04-16', 'sonnig, 18°C', 3, 'Linoleum Flure: Bahnenware in Schulfarbe (blau). Treppenkanten Alu.', 24.0),
(12, '2026-04-17', 'bewölkt, 15°C', 4, 'Linoleum Flügel West Klassenräume. Fußbodenleisten PVC.', 32.0),
(12, '2026-04-20', 'sonnig, 19°C', 3, 'Aula: Sportboden vorbereitet (Prallwand + schwingender Unterbau).', 24.0),
(12, '2026-04-21', 'bewölkt, 16°C', 4, 'Aula Sportboden verlegt (Linoleum-Sportbelag, DIN 18032). Spielfeldlinien.', 32.0);

-- ============================================================
-- Zusätzliche Tagesberichte — Mehr Tiefe Rohbau Projekt 2 (Gewerk 8)
-- ============================================================

INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(8, '2026-03-31', 'bewölkt, 15°C', 4, 'Putzarbeiten Flügel West abgeschlossen. Trocknungsphase beginnt.', 32.0),
(8, '2026-04-01', 'sonnig, 16°C', 3, 'Feinputz Aula (Gipsputz Q3). Brandschutzputz Stahlstützen nachgebessert.', 24.0),
(8, '2026-04-02', 'bewölkt, 14°C', 4, 'Malerarbeiten Flügel Ost begonnen: Grundierung + 1. Anstrich (Dispersion weiß).', 32.0),
(8, '2026-04-03', 'sonnig, 17°C', 4, 'Malerarbeiten Flügel Ost fortgesetzt. 2. Anstrich Klassenräume 1-3.', 32.0),
(8, '2026-04-06', 'bewölkt, 13°C', 4, 'Malerarbeiten Flügel Ost abgeschlossen. Akzentfarben Treppenhäuser.', 32.0),
(8, '2026-04-07', 'sonnig, 15°C', 5, 'Malerarbeiten Flügel West begonnen. Decken + Wände Grundierung.', 40.0),
(8, '2026-04-08', 'Regen, 12°C', 3, 'Nur Innenarbeiten: Maler Flügel West 1. Anstrich Klassenräume.', 24.0),
(8, '2026-04-09', 'bewölkt, 14°C', 5, 'Maler Flügel West 2. Anstrich. Aula Farbkonzept (RAL 1015 Wandsockel).', 40.0),
(8, '2026-04-10', 'sonnig, 16°C', 4, 'Malerarbeiten Aula fertig. Flure 2. Anstrich. Rohbau/Ausbau 60% gesamt.', 32.0);

-- ============================================================
-- Zusätzliche Tagesberichte — Elektro + Sanitär Projekt 2 (Gewerke 9, 10)
-- ============================================================

INSERT INTO tagesberichte (gewerk_id, datum, wetter, arbeiter_anzahl, beschreibung, stunden) VALUES
(9, '2026-04-06', 'bewölkt, 13°C', 4, 'Brandmeldeanlage: fehlende 4 Melder in Loop registriert (Mangelbehebung).', 32.0),
(9, '2026-04-07', 'sonnig, 15°C', 3, 'Sicherheitsbeleuchtung Prüfung. Akkulaufzeit 3h OK (Anforderung 1h).', 24.0),
(9, '2026-04-08', 'Regen, 12°C', 3, 'EDV-Netzwerk Klassenräume: WLAN Access Points montiert (26 Stück).', 24.0),
(9, '2026-04-09', 'bewölkt, 14°C', 4, 'Schaltschrank Aula: Bühnenbeleuchtung, Verdunkelung, Medientechnik.', 32.0),
(9, '2026-04-10', 'sonnig, 16°C', 3, 'E-Check Flügel Ost komplett: Messprotokolle erstellt. Alles im Soll.', 24.0),
(10, '2026-03-31', 'bewölkt, 15°C', 3, 'Toilettentrakt West: Keramik montiert (6x WC, 4x Urinal, 8x Waschtisch).', 24.0),
(10, '2026-04-01', 'sonnig, 16°C', 3, 'Behindertengerechtes WC EG: Stützklappgriffe, unterfahrbarer Waschtisch.', 24.0),
(10, '2026-04-02', 'bewölkt, 14°C', 2, 'Teeküche Lehrerzimmer: Spüle, Durchlauferhitzer, Absperrventile.', 16.0),
(10, '2026-04-07', 'sonnig, 15°C', 3, 'Heizungseinregulierung komplett. Raumthermostate Flügel West kalibriert.', 24.0),
(10, '2026-04-09', 'bewölkt, 14°C', 2, 'Druckprüfung Trinkwasser gesamt: 10 bar, 30 min — bestanden. Protokoll.', 16.0);

-- ============================================================
-- Mängel — 30 Stück (verschiedene Schweregrade)
-- ============================================================

-- Projekt 1: Neubau Wohnanlage
INSERT INTO maengel (gewerk_id, datum, beschreibung, schweregrad, status, frist) VALUES
-- Kritische Mängel
(1, '2026-02-26', 'Kiesnester Decke EG Achse B3-B4, Bewehrung teilweise sichtbar. Sanierung erforderlich.', 'kritisch', 'offen', '2026-03-15'),
(2, '2026-03-10', 'Elektroverteilung EG ohne FI-Schutzschalter installiert. Sofortige Nachrüstung nötig.', 'kritisch', 'offen', '2026-03-20'),
(4, '2026-04-02', 'Dachfenster Nr. 3 (Nordseite) undicht bei Schlagregen. Anschlussfolie nicht korrekt verklebt.', 'kritisch', 'offen', '2026-04-15'),
(1, '2026-03-19', 'Decke 2.OG Durchbiegung 18mm bei 6m Spannweite (L/333, max L/500 nach EC2). Statiker einschalten.', 'kritisch', 'in_bearbeitung', '2026-04-01'),
-- Mittlere Mängel
(1, '2026-03-05', 'Mauerwerk 1.OG Wohnung 2: Stoßfugen nicht vollständig vermörtelt (3 Stellen).', 'mittel', 'behoben', '2026-03-20'),
(3, '2026-03-17', 'Fußbodenheizung Wohnung 3 EG: Heizkreis 2 Durchfluss zu gering. Spülung erforderlich.', 'mittel', 'offen', '2026-04-10'),
(2, '2026-04-01', 'Kabelquerschnitt Herd-Anschluss Wohnung 4: 3x2,5mm² statt 5x2,5mm². Nachlegen.', 'mittel', 'offen', '2026-04-20'),
(4, '2026-03-31', 'Traufblech Westseite: Überlappung nur 3cm statt 5cm. Schlagregen kann eindringen.', 'mittel', 'offen', '2026-04-15'),
(5, '2026-04-03', 'WDVS Sockel Südseite: Stoß zwischen XPS und EPS nicht vermörtelt. Wärmebrücke.', 'mittel', 'offen', '2026-04-20'),
(3, '2026-04-02', 'Regenfallrohr DN75 statt DN100 eingebaut. Kapazität für Dachfläche nicht ausreichend.', 'mittel', 'offen', '2026-04-25'),
-- Geringe Mängel
(1, '2026-02-18', 'Sichtbeton Kellerwand Block B: leichte Farbunterschiede durch Chargen. Nur optisch.', 'gering', 'behoben', '2026-03-01'),
(1, '2026-03-12', 'Mauerwerk 2.OG: 2 Mauersteine mit Abplatzung verbaut. Austausch empfohlen.', 'gering', 'offen', '2026-04-15'),
(3, '2026-03-03', 'Heizungsrohr Keller: Isolierung an Durchführung Wand beschädigt. Nachbessern.', 'gering', 'behoben', '2026-03-15'),
(2, '2026-03-09', 'UP-Dose Flur EG schief gesetzt (5° Versatz). Optischer Mangel.', 'gering', 'offen', '2026-04-30'),
(4, '2026-04-03', 'Dachrinne Ostseite: leichtes Gefälle zu gering (0,3% statt 0,5%). Funktioniert aber.', 'gering', 'offen', '2026-04-30');

-- Projekt 2: Sanierung Grundschule
INSERT INTO maengel (gewerk_id, datum, beschreibung, schweregrad, status, frist) VALUES
-- Kritische Mängel
(8, '2026-02-04', 'Tragender Sturz Aula: Riss 2mm breit, 80cm lang. Statiker sofort benachrichtigt.', 'kritisch', 'in_bearbeitung', '2026-02-20'),
(9, '2026-03-10', 'Brandmeldeanlage Flügel Ost: 4 Melder nicht im Loop registriert. Brandschutz gefährdet.', 'kritisch', 'offen', '2026-03-25'),
(11, '2026-03-04', 'Brandschutztür Treppenhaus B schließt nicht selbstständig. Türschließer defekt.', 'kritisch', 'offen', '2026-03-15'),
-- Mittlere Mängel
(8, '2026-03-17', 'Putz Flügel Ost Klassenraum 3: Hohlstellen hinter Putz (Klopfprobe). 2m² betroffen.', 'mittel', 'offen', '2026-04-01'),
(10, '2026-02-24', 'Waschtisch Toilette EG: Silikon-Anschluss ungleichmäßig. Schimmelgefahr.', 'mittel', 'behoben', '2026-03-10'),
(9, '2026-03-24', 'Außenbeleuchtung Schulhof: 2 von 8 LED-Strahlern flackern. Vorschaltgerät prüfen.', 'mittel', 'offen', '2026-04-10'),
(8, '2026-02-24', 'Estrich Klassenraum 5: Schüsselung an Türschwelle (3mm Höhenunterschied). Nachschleifen.', 'mittel', 'offen', '2026-03-20'),
(11, '2026-03-03', 'Fenster Klassenraum 7: Beschlag schwergängig, Fenster lässt sich nicht kippen.', 'mittel', 'behoben', '2026-03-15'),
-- Geringe Mängel
(8, '2026-01-28', 'Innenwand Lehrerzimmer: Fugenbreite Mauerwerk ungleichmäßig (8-15mm). Nur optisch.', 'gering', 'offen', '2026-03-15'),
(10, '2026-03-10', 'Heizkörper Sekretariat: Entlüftungsventil undicht (tropft minimal). Ventil tauschen.', 'gering', 'offen', '2026-04-01'),
(9, '2026-02-17', 'Kabelkanal Flur Ost: Deckel schließt nicht bündig an Ecke. Optischer Mangel.', 'gering', 'behoben', '2026-03-01'),
(11, '2026-02-19', 'Fensterbrett Klassenraum 2: Kratzer in Oberfläche vom Transport. Kosmetisch.', 'gering', 'offen', '2026-04-30'),
(8, '2026-03-24', 'Putz Flur West: Pinselstriche sichtbar nach Ausbesserung Elektroschlitze.', 'gering', 'offen', '2026-04-30'),
(10, '2026-03-17', 'WC-Spülung Damen EG: Spülvolumen 7,5L statt 6L eingestellt. Nachjustieren.', 'gering', 'offen', '2026-04-15');

-- ============================================================
-- Kosten — 150 Einträge
-- ============================================================

-- Projekt 1: Neubau Wohnanlage — Rohbau (Gewerk 1)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(1, '2026-02-02', 'Material: Beton C30/37', 4950.00, 'RE-2026-001'),
(1, '2026-02-04', 'Material: Beton C30/37 (Kellersohle 45m³)', 5850.00, 'RE-2026-002'),
(1, '2026-02-05', 'Material: Bewehrungsstahl BSt 500', 8200.00, 'RE-2026-003'),
(1, '2026-02-06', 'Leistung: Schalung Kellerwände', 3400.00, 'RE-2026-004'),
(1, '2026-02-09', 'Material: Beton C30/37 (Kellerwände 60m³)', 7800.00, 'RE-2026-005'),
(1, '2026-02-09', 'Gerät: Betonpumpe Miete', 1200.00, 'RE-2026-006'),
(1, '2026-02-12', 'Material: PE-Folie + XPS-Dämmung Bodenplatte', 4500.00, 'RE-2026-007'),
(1, '2026-02-13', 'Material: Bewehrungsstahl 12t', 9600.00, 'RE-2026-008'),
(1, '2026-02-16', 'Material: Beton C25/30 (Bodenplatte 85m³)', 10200.00, 'RE-2026-009'),
(1, '2026-02-16', 'Gerät: Betonpumpe 36m Miete', 1800.00, 'RE-2026-010'),
(1, '2026-02-18', 'Material: Poroton T7 36,5cm', 12400.00, 'RE-2026-011'),
(1, '2026-02-20', 'Material: KS-Steine 17,5cm Innenwände', 3800.00, 'RE-2026-012'),
(1, '2026-02-24', 'Material: Beton Ringbalken', 1800.00, 'RE-2026-013'),
(1, '2026-02-25', 'Leistung: Filigrandecken + Kran', 18500.00, 'RE-2026-014'),
(1, '2026-02-26', 'Material: Aufbeton Decke EG 35m³', 4200.00, 'RE-2026-015'),
(1, '2026-03-02', 'Material: Poroton T7 1.OG', 12400.00, 'RE-2026-016'),
(1, '2026-03-06', 'Material: Beton Ringbalken 1.OG', 1800.00, 'RE-2026-017'),
(1, '2026-03-09', 'Leistung: Filigrandecken + Kran 1.OG', 18500.00, 'RE-2026-018'),
(1, '2026-03-10', 'Material: Aufbeton Decke 1.OG', 4200.00, 'RE-2026-019'),
(1, '2026-03-12', 'Material: Poroton T7 2.OG', 12400.00, 'RE-2026-020'),
(1, '2026-03-17', 'Material: Beton Ringbalken 2.OG', 1800.00, 'RE-2026-021'),
(1, '2026-03-18', 'Leistung: Filigrandecken + Kran 2.OG', 18500.00, 'RE-2026-022'),
(1, '2026-03-19', 'Material: Aufbeton Decke 2.OG', 4200.00, 'RE-2026-023'),
(1, '2026-03-23', 'Material: Porenbeton Drempel + Giebel', 3600.00, 'RE-2026-024'),
(1, '2026-04-01', 'Material: Beton Schornsteinköpfe, Attika', 1200.00, 'RE-2026-025');

-- Projekt 1: Elektro (Gewerk 2)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(2, '2026-03-02', 'Material: Leerrohre + UP-Dosen', 2800.00, 'RE-2026-026'),
(2, '2026-03-09', 'Material: NYM-Kabel 3x1,5mm²', 1900.00, 'RE-2026-027'),
(2, '2026-03-16', 'Material: NYM-Kabel Teillieferung', 1200.00, 'RE-2026-028'),
(2, '2026-03-17', 'Material: Schalter/Steckdosen Busch-Jaeger', 4200.00, 'RE-2026-029'),
(2, '2026-03-30', 'Material: NYM 5x2,5mm² (Nachlieferung)', 3500.00, 'RE-2026-030'),
(2, '2026-04-01', 'Material: Verteilerschränke 1.OG', 2200.00, 'RE-2026-031'),
(2, '2026-04-02', 'Material: Sicherungsautomaten + FI', 1800.00, 'RE-2026-032'),
(2, '2026-03-10', 'Kosten: Materialengpass-Aufpreis NYM', 850.00, 'RE-2026-033');

-- Projekt 1: Sanitär (Gewerk 3)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(3, '2026-02-23', 'Material: KG-Rohre DN100/150 Grundleitungen', 3200.00, 'RE-2026-034'),
(3, '2026-02-24', 'Material: Guss-Fallleitungen + Schallschutz', 4800.00, 'RE-2026-035'),
(3, '2026-03-02', 'Material: Kupferrohr Heizung Steigeleitungen', 5600.00, 'RE-2026-036'),
(3, '2026-03-03', 'Material: Fußbodenheizung Komplettsystem', 14200.00, 'RE-2026-037'),
(3, '2026-03-16', 'Material: Edelstahl Trinkwasserleitungen', 6800.00, 'RE-2026-038'),
(3, '2026-03-23', 'Material: Heizkreisverteiler 6x', 3600.00, 'RE-2026-039'),
(3, '2026-04-01', 'Material: Heizungsverteiler Keller', 2400.00, 'RE-2026-040'),
(3, '2026-04-02', 'Material: HT-Rohre Regenentwässerung', 1800.00, 'RE-2026-041');

-- Projekt 1: Dach (Gewerk 4)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(4, '2026-03-25', 'Material: Konstruktionsholz Dachstuhl', 22000.00, 'RE-2026-042'),
(4, '2026-03-26', 'Material: Unterspannbahn + Konterlattung', 4500.00, 'RE-2026-043'),
(4, '2026-03-27', 'Material: Lattung + Gauben-Holz', 3200.00, 'RE-2026-044'),
(4, '2026-03-30', 'Material: Tondachziegel Braas Rubin', 16800.00, 'RE-2026-045'),
(4, '2026-04-01', 'Material: Schneefanggitter', 2800.00, 'RE-2026-046'),
(4, '2026-04-02', 'Material: Dachfenster Velux 8 Stück', 9600.00, 'RE-2026-047'),
(4, '2026-04-03', 'Material: Traufbleche + Gaubenverkleidung', 3800.00, 'RE-2026-048'),
(4, '2026-03-25', 'Leistung: Zimmermann Dachstuhl', 12000.00, 'RE-2026-049');

-- Projekt 1: Fassade (Gewerk 5)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(5, '2026-04-01', 'Leistung: Gerüstbau', 8500.00, 'RE-2026-050'),
(5, '2026-04-02', 'Material: XPS Sockeldämmung', 2200.00, 'RE-2026-051'),
(5, '2026-04-03', 'Material: EPS 160mm WDVS', 6800.00, 'RE-2026-052');

-- Projekt 1: Innenausbau (Gewerk 6)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(6, '2026-04-01', 'Material: Trockenbauprofile UA/CW/UW', 4200.00, 'RE-2026-053'),
(6, '2026-04-02', 'Material: Gipskartonplatten 12,5mm', 3100.00, 'RE-2026-054');

-- Projekt 2: Abbruch (Gewerk 7)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(7, '2026-01-06', 'Leistung: Entkernung Flügel Ost', 8500.00, 'RE-2026-055'),
(7, '2026-01-08', 'Entsorgung: Container Bauschutt 2x', 2400.00, 'RE-2026-056'),
(7, '2026-01-09', 'Leistung: Entkernung Flügel West', 7200.00, 'RE-2026-057'),
(7, '2026-01-13', 'Leistung: Abbruch Nebengebäude', 4500.00, 'RE-2026-058'),
(7, '2026-01-14', 'Entsorgung: Container 3+4 + Sondermüll', 3800.00, 'RE-2026-059');

-- Projekt 2: Rohbau/Mauerwerk (Gewerk 8)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(8, '2026-01-20', 'Material: Porenbeton 11,5cm', 3800.00, 'RE-2026-060'),
(8, '2026-01-22', 'Leistung: Betonschneiden Deckenöffnung', 2200.00, 'RE-2026-061'),
(8, '2026-01-27', 'Material: Beton + Bewehrung Treppe', 4500.00, 'RE-2026-062'),
(8, '2026-01-28', 'Material: Porenbeton Flügel West', 3200.00, 'RE-2026-063'),
(8, '2026-02-04', 'Material: Stahlbetonfertigteile Stürze', 5600.00, 'RE-2026-064'),
(8, '2026-02-10', 'Leistung: Stahlstützen Aula + Brandschutz', 8900.00, 'RE-2026-065'),
(8, '2026-02-17', 'Material: Trittschalldämmung + PE-Folie', 2800.00, 'RE-2026-066'),
(8, '2026-02-24', 'Material: Fließestrich CT-C30-F5', 6200.00, 'RE-2026-067'),
(8, '2026-03-03', 'Material: Estrich Flügel West', 5800.00, 'RE-2026-068'),
(8, '2026-03-10', 'Material: Maschinenputz Kalkzement', 4200.00, 'RE-2026-069'),
(8, '2026-03-17', 'Leistung: Putzarbeiten (2 Mann, 5 Tage)', 6500.00, 'RE-2026-070'),
(8, '2026-03-24', 'Leistung: Putzarbeiten Flügel West', 5800.00, 'RE-2026-071');

-- Projekt 2: Elektro (Gewerk 9)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(9, '2026-02-03', 'Material: Hauptverteilung + Zählerplatz', 8500.00, 'RE-2026-072'),
(9, '2026-02-10', 'Material: Kabeltrassen + Brandschotts', 4200.00, 'RE-2026-073'),
(9, '2026-02-17', 'Material: NYM-Kabel + Doppel-/Datendosen', 5600.00, 'RE-2026-074'),
(9, '2026-02-24', 'Material: LED-Panels Flügel Ost', 7200.00, 'RE-2026-075'),
(9, '2026-03-03', 'Material: Brandmeldeanlage Leitungen + Melder', 12500.00, 'RE-2026-076'),
(9, '2026-03-10', 'Material: EDV-Verkabelung Cat6a + Patchfeld', 4800.00, 'RE-2026-077'),
(9, '2026-03-17', 'Material: LED-Panels + Notbeleuchtung Flügel West', 9200.00, 'RE-2026-078'),
(9, '2026-03-24', 'Material: Außenbeleuchtung + Erdkabel', 5400.00, 'RE-2026-079'),
(9, '2026-04-01', 'Material: Sprechanlage + Türöffner', 3200.00, 'RE-2026-080');

-- Projekt 2: Sanitär (Gewerk 10)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(10, '2026-02-10', 'Material: Edelstahl-Steigeleitungen', 4800.00, 'RE-2026-081'),
(10, '2026-02-17', 'Material: Vorwandinstallation Geberit', 6200.00, 'RE-2026-082'),
(10, '2026-02-24', 'Material: WC-Keramik + Waschtische (8 Sets)', 5600.00, 'RE-2026-083'),
(10, '2026-03-03', 'Leistung: Heizungsleitungen Demontage + Neu', 4500.00, 'RE-2026-084'),
(10, '2026-03-10', 'Material: Plattenheizkörper 22x', 8800.00, 'RE-2026-085'),
(10, '2026-03-17', 'Material: Toilettentrakt West Rohinstallation', 3900.00, 'RE-2026-086');

-- Projekt 2: Fenster/Türen (Gewerk 11)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(11, '2026-02-17', 'Material: Fenster 3-fach Uw=0,9 (28 Stk Ost)', 42000.00, 'RE-2026-087'),
(11, '2026-02-17', 'Leistung: RAL-Montage Fenster Flügel Ost', 5600.00, 'RE-2026-088'),
(11, '2026-03-02', 'Material: Fenster 3-fach (22 Stk West)', 33000.00, 'RE-2026-089'),
(11, '2026-03-02', 'Leistung: RAL-Montage Fenster Flügel West', 4400.00, 'RE-2026-090'),
(11, '2026-03-10', 'Material: Brandschutztüren T30 (12 Stk)', 14400.00, 'RE-2026-091'),
(11, '2026-03-17', 'Material: Innentüren + Automatiktür Eingang', 18500.00, 'RE-2026-092'),
(11, '2026-03-24', 'Material: Beschläge + Türschließer + Panikschlösser', 4200.00, 'RE-2026-093');

-- Zusätzliche allgemeine Kosten Projekt 1
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(1, '2026-02-01', 'Leistung: Baustelleneinrichtung', 15000.00, 'RE-2026-094'),
(1, '2026-02-01', 'Gerät: Kran Monatsmiete Februar', 4500.00, 'RE-2026-095'),
(1, '2026-03-01', 'Gerät: Kran Monatsmiete März', 4500.00, 'RE-2026-096'),
(1, '2026-04-01', 'Gerät: Kran Monatsmiete April', 4500.00, 'RE-2026-097'),
(1, '2026-02-15', 'Leistung: Vermessung + Absteckung', 2800.00, 'RE-2026-098'),
(1, '2026-03-15', 'Leistung: Bauleitung Monat März', 8500.00, 'RE-2026-099'),
(1, '2026-04-01', 'Leistung: Bauleitung Monat April', 8500.00, 'RE-2026-100');

-- Zusätzliche allgemeine Kosten Projekt 2
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(7, '2026-01-05', 'Leistung: Baustelleneinrichtung Schule', 8500.00, 'RE-2026-101'),
(7, '2026-01-05', 'Leistung: Sicherung Schulgelände + Bauzaun', 3200.00, 'RE-2026-102'),
(8, '2026-02-01', 'Gerät: Gerüst Monatsmiete Februar', 2800.00, 'RE-2026-103'),
(8, '2026-03-01', 'Gerät: Gerüst Monatsmiete März', 2800.00, 'RE-2026-104'),
(8, '2026-04-01', 'Gerät: Gerüst Monatsmiete April', 2800.00, 'RE-2026-105'),
(8, '2026-02-01', 'Leistung: Bauleitung Monat Februar', 6500.00, 'RE-2026-106'),
(8, '2026-03-01', 'Leistung: Bauleitung Monat März', 6500.00, 'RE-2026-107'),
(8, '2026-04-01', 'Leistung: Bauleitung Monat April', 6500.00, 'RE-2026-108');

-- Weitere Material- und Leistungskosten (auffüllen auf ~150)
INSERT INTO kosten (gewerk_id, datum, kategorie, betrag_eur, beleg_nr) VALUES
(1, '2026-02-10', 'Material: Schalungsplatten Miete', 3200.00, 'RE-2026-109'),
(1, '2026-02-20', 'Material: Mauermörtel + Dünnbettmörtel', 2100.00, 'RE-2026-110'),
(1, '2026-03-05', 'Material: Mauermörtel 1.OG', 1800.00, 'RE-2026-111'),
(1, '2026-03-15', 'Material: Mauermörtel 2.OG', 1800.00, 'RE-2026-112'),
(2, '2026-04-03', 'Leistung: Elektro Aufmaß (Abschlag 2)', 8500.00, 'RE-2026-113'),
(3, '2026-03-30', 'Leistung: Sanitär Aufmaß (Abschlag 2)', 12000.00, 'RE-2026-114'),
(4, '2026-03-25', 'Leistung: Zimmermann Anlieferung', 1500.00, 'RE-2026-115'),
(5, '2026-04-03', 'Material: Armierungsmörtel + Gewebe WDVS', 3400.00, 'RE-2026-116'),
(6, '2026-04-03', 'Material: Spachtelmasse + Grundierung', 1200.00, 'RE-2026-117'),
(1, '2026-02-11', 'Leistung: Winterbaumaßnahmen (Heizung)', 1800.00, 'RE-2026-118'),
(3, '2026-02-23', 'Leistung: Tiefbau Grundleitungen (extern)', 5200.00, 'RE-2026-119'),
(4, '2026-03-26', 'Material: Dampfbremse Intello Plus', 2200.00, 'RE-2026-120'),
(1, '2026-03-25', 'Leistung: Statiker Abnahme Rohbau', 2400.00, 'RE-2026-121'),
(8, '2026-01-27', 'Leistung: Schalung Treppe (extern)', 3200.00, 'RE-2026-122'),
(9, '2026-03-03', 'Leistung: Brandschutz-Fachplaner', 4500.00, 'RE-2026-123'),
(10, '2026-02-17', 'Leistung: Kernbohrungen Toilettentrakt', 1800.00, 'RE-2026-124'),
(11, '2026-02-19', 'Material: Fensterbänke innen Naturstein', 3600.00, 'RE-2026-125'),
(11, '2026-03-10', 'Leistung: Brandschutztüren Einbau', 3600.00, 'RE-2026-126'),
(8, '2026-02-10', 'Material: Stahlstützen HEB 200', 6800.00, 'RE-2026-127'),
(9, '2026-02-24', 'Leistung: Elektro-Montage (Abschlag 1)', 8000.00, 'RE-2026-128'),
(10, '2026-03-10', 'Leistung: Sanitär-Montage (Abschlag 1)', 6500.00, 'RE-2026-129'),
(8, '2026-03-03', 'Material: Estrich-Randstreifen + Folie', 800.00, 'RE-2026-130'),
(1, '2026-04-02', 'Material: Beton Lichtschächte', 950.00, 'RE-2026-131'),
(3, '2026-03-09', 'Material: Fußbodenheizung 1.OG Zubehör', 2400.00, 'RE-2026-132'),
(2, '2026-03-03', 'Leistung: Schlitze stemmen (Hilfsarbeiter)', 1600.00, 'RE-2026-133'),
(4, '2026-04-01', 'Material: Firstziegel + Gratsteine', 1800.00, 'RE-2026-134'),
(5, '2026-04-01', 'Material: Sockelschiene Alu', 950.00, 'RE-2026-135'),
(8, '2026-03-10', 'Material: Putzgrund + Eckschutzschienen', 1400.00, 'RE-2026-136'),
(9, '2026-04-01', 'Leistung: Sprechanlage Programmierung', 800.00, 'RE-2026-137'),
(10, '2026-03-24', 'Material: Absperrventile + Durchflussbegrenzer', 1200.00, 'RE-2026-138'),
(11, '2026-03-24', 'Material: Panikschlösser Fluchttüren', 2800.00, 'RE-2026-139'),
(1, '2026-03-01', 'Versicherung: Bauwesenversicherung Monat 3', 1200.00, 'RE-2026-140'),
(1, '2026-04-01', 'Versicherung: Bauwesenversicherung Monat 4', 1200.00, 'RE-2026-141'),
(7, '2026-01-10', 'Leistung: Schadstoffgutachter (Probenahme)', 2200.00, 'RE-2026-142'),
(8, '2026-01-22', 'Leistung: Statiker Bestandsbewertung', 3500.00, 'RE-2026-143'),
(9, '2026-03-17', 'Material: Notbeleuchtung Akkupacks', 2400.00, 'RE-2026-144'),
(10, '2026-02-10', 'Leistung: Bestandsaufnahme Leitungen', 1800.00, 'RE-2026-145'),
(1, '2026-02-01', 'Leistung: SiGe-Koordinator Monat Feb', 2200.00, 'RE-2026-146'),
(1, '2026-03-01', 'Leistung: SiGe-Koordinator Monat März', 2200.00, 'RE-2026-147'),
(1, '2026-04-01', 'Leistung: SiGe-Koordinator Monat April', 2200.00, 'RE-2026-148'),
(8, '2026-02-24', 'Leistung: Estrichleger (extern, 2 Mann)', 4800.00, 'RE-2026-149'),
(8, '2026-03-03', 'Leistung: Estrichleger Flügel West', 4200.00, 'RE-2026-150');

-- ============================================================
-- Zusammenfassung der eingebetteten Geschichten:
--
-- Projekt 1 "Neubau Wohnanlage Bergstraße 12":
--   - Rohbau bei 85%, gut im Zeitplan
--   - Elektro VERZÖGERT: NYM 5x2,5mm² Materialengpass (4 Wochen)
--   - 4 kritische Mängel offen (Kiesnester, FI fehlt, Dachfenster undicht, Deckendurchbiegung)
--   - Budget 2.850.000 EUR, bisherige Kosten ca. 420.000 EUR (Rohbau+Dach Hauptposten)
--
-- Projekt 2 "Sanierung Grundschule Am Park":
--   - Abbruch abgeschlossen, Rohbau/Mauerwerk 60%
--   - 3 kritische Mängel (Sturz Aula, Brandmelder, Brandschutztür)
--   - Budget 1.450.000 EUR, bisherige Kosten ca. 450.000 EUR
-- ============================================================
