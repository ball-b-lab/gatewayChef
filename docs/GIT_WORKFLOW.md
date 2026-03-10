# Git Workflow Rules

Stand: 2026-03-10

## Ziel
- Stabiler `main` Branch fuer produktive und deployte Staende.
- Feature-Branches nur fuer kurzfristige Arbeit, nicht als dauerhafte Deploy-Ziele.
- Nachvollziehbare Releases und schnelle Rollbacks.

## Branching Regeln
- `main`:
  - nur via PR
  - nur getestete, deployfaehige Staende
- Feature-Branches immer mit Prefix `codex/`:
  - `codex/api-*` fuer Cloud/API Themen
  - `codex/local-*` fuer Local-App Themen
  - `codex/docs-*` fuer reine Doku

## Praktischer Ablauf
1. Feature-Branch von `main` erstellen:
   - `git checkout main`
   - `git pull`
   - `git checkout -b codex/local-<thema>`
2. Kleine, klare Commits mit Scope:
   - `api: ...`
   - `local: ...`
   - `docs: ...`
3. Push + PR:
   - `git push origin <branch>`
4. Merge nach `main` erst nach:
   - passenden Tests/Smoke
   - kurzer Deploy-Checkliste

## Release/Deploy Regel
- Coolify deployt `main`.
- Nach Merge in `main` optional Tag setzen, z. B.:
  - `v2026.03.07-1`
- Optional kann auf Commit SHA oder Tag gepinnt werden.
- Keine produktiven Deploys auf wechselnde `codex/*` Branches.

## Deploy-Checkliste (kurz)
1. Erwarteten Commit/Tag notieren.
2. `/api/version` gegen Erwartung pruefen (`build_sha`, `app_mode`).
3. Smoke gegen Zielumgebung laufen lassen.

## Wenn Build-Metadaten nicht gesetzt sind
- Das ist ok.
- `build_sha` faellt auf Git SHA zurueck.
- `build_tag` und `build_time` sind dann `unknown`.
