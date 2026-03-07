# Betriebsanleitung fuer Mitarbeiter

## Sicherer v2 Ablauf

1. `Lauf anlegen`
   Pflichtfelder: Mitarbeiter, Gateway-Name, Seriennummer, SIM Vendor, SIM ICCID.
2. `Precheck`
   Prueft Gateway-Erreichbarkeit, EUI, Zellstatus und Inventar-Verfuegbarkeit.
3. `Konfigurationswerte reservieren`
   Reserviert VPN-IP/SIM und zeigt die Zielwerte fuer das Gateway.
4. `Gateway-Konfiguration bestaetigen`
   Erst nach manueller Uebernahme der Zielwerte im Gateway.
5. `Cloud Sync`
   Erstellt fehlende Eintraege idempotent in ChirpStack, Milesight und optional Webservice.
6. `Verifizieren`
   Erstellt den Readiness Report.
7. `Final abschliessen`
   Nur bei `PASS`.

## Operator-Regeln

- Webservice-Zugangsdaten nur im Browser eingeben; sie werden nicht persistiert.
- Bei `FAILED` zuerst den Audit-Verlauf lesen, dann den passenden Schritt erneut ausfuehren.
- Keine manuelle Freigabe ausserhalb der v2, wenn der Report `BLOCK` zeigt.
