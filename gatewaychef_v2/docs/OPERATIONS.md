# Betriebsanleitung fuer Mitarbeiter

## Fall A: Neuer Gateway

1. Webservice-Login eingeben.
2. Discovery pruefen:
   `bbdbmon_golden` bedeutet: Gateway ist noch nicht fertig konfiguriert.
3. `Provisionierung starten`
4. `Precheck`
5. `Neue Zielwerte reservieren`
6. Zielwerte im Gateway setzen
7. `Aenderungen bestaetigen`
8. `Cloud Sync`
9. `Verifizieren`
10. `Gateway freigeben`

Wichtig:
- SSID-Wechsel immer zuletzt
- Ohne gruene Verifikation keine Freigabe

## Fall B: Gateway technisch ok, aber Draft

Erkennbar an:
- Status `Technisch ok, Draft`
- offene Aufgabe `Kunde zuordnen oder Draft speichern`

Vorgehen:
1. Wenn der Gateway sofort einem Kunden gehoeren soll:
   `Kunden-ID` eintragen.
2. Wenn er bewusst noch keinem Kunden gehoert:
   `Als Draft in Cloud DB speichern`
3. Spaeter Kunden-ID nachtragen und Webservice-Anlage ausfuehren.

Wichtig:
- Draft ist erlaubt
- Draft ist nicht freigegeben
- `Gateway freigeben` ist in diesem Zustand nicht zulaessig

## Fall C: Gateway technisch ok, Webservice offen

Erkennbar an:
- Status `Technisch ok, Webservice offen`
- offene Aufgabe `Webservice-Eintrag anlegen`

Vorgehen:
1. Sicherstellen, dass `Kunden-ID` gesetzt ist
2. `Gateway im Webservice beim Kunden anlegen`
3. `Verifizieren`
4. `Gateway freigeben`

## Fall D: Gateway technisch ok, Freigabe offen

Erkennbar an:
- Status `Technisch ok, Freigabe offen`
- keine technischen Abweichungen mehr

Vorgehen:
1. `Cloud-Status abgleichen`, falls angeboten
2. `Verifizieren`
3. `Gateway freigeben`

## Operator-Regeln

- Webservice-Zugangsdaten nur im Browser eingeben; sie werden nicht persistiert.
- `Status & Naechste Schritte` ist die fuehrende Liste. Dort steht nur, was noch fehlt.
- Bei `FAILED` zuerst die operatorische Fehlermeldung lesen, danach den Debug-Teil nur bei Bedarf.
- Keine manuelle Freigabe ausserhalb der v2, wenn der Report `BLOCK` zeigt.
