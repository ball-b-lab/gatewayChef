# Startanleitung Alt und Neu

## Alt

1. Abhaengigkeiten installieren
   `pip install -r requirements.txt`
2. Root Migrationen ausfuehren
   `python scripts/migrate.py`
3. App starten
   `python app.py`
4. Alt-UI aufrufen
   `http://localhost:5000/`

## Neu

1. Bestehende App starten wie oben
2. v2 Migrationen ausfuehren
   `python gatewaychef_v2/scripts/migrate_v2.py`
3. v2 UI aufrufen
   `http://localhost:5000/gatewaychef-v2/`

Die v2 laeuft parallel zur bestehenden Variante. Der produktive Alt-Pfad bleibt unveraendert.
