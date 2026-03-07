# Deployment Guide

This guide covers setting up the development environment, running the application locally, and building standalone executables for Windows, macOS, and Linux.

## Prerequisites

- **Python 3.12+**: Ensure Python is installed and added to your system PATH.
- **Git**: For version control.

## Development Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd provisioner
    ```

2.  **Create a virtual environment:**
    -   **macOS/Linux:**
        ```bash
        python3 -m venv venv
        source venv/bin/activate
        ```
    -   **Windows:**
        ```cmd
        python -m venv venv
        venv\Scripts\activate
        ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configuration:**
    -   Copy `.env.example` to `.env`.
    -   Edit `.env` and fill in your database credentials, API keys, and gateway details.

5.  **Run locally:**
    ```bash
    python scripts/migrate.py
    python app.py
    ```
    The application will open in your default browser at `http://localhost:5000`.

## Docker (Local, Coolify-nah)

1.  **Prepare env:**
    ```bash
    cp .env.example .env
    ```

2.  **Start stack:**
    ```bash
    docker compose up --build
    ```

3.  **Stop stack:**
    ```bash
    docker compose down
    ```

The app container runs `python scripts/migrate.py && python app.py` automatically.

## Legacy DB Import (Einmalig)

Use this when you replace the old public DB with a new internal DB:

```bash
SOURCE_DATABASE_URL='postgresql://user:pass@old-host:5432/dbname' \
TARGET_DATABASE_URL='postgresql://user:pass@new-host:5432/dbname' \
IMPORT_MODE='schema-and-data' \
./scripts/import_legacy_dump.sh
```

Optional:
- `IMPORT_MODE=data-only` if target schema is already aligned.
- `TABLES=\"gateway_inventory sim_cards sim_vendors\"` to override selection.

## Coolify Setup

-   **Build Pack:** Dockerfile
-   **Dockerfile:** `Dockerfile`
-   **Port:** `5000`
-   **Start Command:** leave default from Dockerfile
-   **Required env vars:** `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
-   **Mode:** `APP_MODE=cloud_api`
-   **Recommended service auth:** `API_SERVICE_TOKEN` (protects `/api/db*`, `/api/sim*`, `/api/provision`, `/api/confirm`)
-   **Recommended env vars:** `OPEN_BROWSER=false`, `FLASK_DEBUG=false`, `HOST=0.0.0.0`, `PORT=5000`
-   **Optional for VPN reachability from local app:** `VPN_PING_SERVICE_TOKEN`
-   **Recommended build metadata:** `APP_BUILD_SHA`, `APP_BUILD_TAG`, `APP_BUILD_TIME`
-   **Cloud scope only:** DB API + VPN Ping Service (no Gateway/ChirpStack/Milesight/Webservice routes in `cloud_api`)

If you use an external managed PostgreSQL in Coolify, point `DB_*` to that database.  
If you use the compose file locally, Postgres runs as service `db`.

### Database Configuration Modes (Important)

You can configure DB connection in exactly one of these modes:

1. `DATABASE_URL` mode (single variable):
```env
DATABASE_URL=postgres://user:password@host:5432/dbname
```

2. `DB_*` mode (separate variables):
```env
DB_HOST=host
DB_PORT=5432
DB_NAME=dbname
DB_USER=user
DB_PASSWORD=password
```

Do not put a full `postgres://...` URL into `DB_HOST`.  
That causes host resolution errors like `could not translate host name "postgres://..."`.

### VPN Ping via Cloud API (optional)

Use this if your local workstation cannot reach VPN targets directly:

1. On cloud deployment set:
   - `VPN_PING_SERVICE_TOKEN=<shared-secret>`
2. On local app set:
   - `VPN_PING_PROVIDER_URL=https://<cloud-app-url>`
   - `VPN_PING_SERVICE_TOKEN=<shared-secret>`

Then `/api/network/vpn-check` on local app will forward ping checks to cloud `/api/network/ping-service`.

### DB via Cloud API (recommended for local runner)

Use this to keep PostgreSQL only in cloud/internal network while local app stays main runner:

1. On cloud deployment set:
   - `APP_MODE=cloud_api`
   - `API_SERVICE_TOKEN=<shared-secret>`
2. On local app set:
   - `APP_MODE=local`
   - `DB_API_PROVIDER_URL=https://<cloud-app-url>`
   - `API_SERVICE_TOKEN=<shared-secret>`

Then local `/api/db*`, `/api/sim*`, `/api/provision`, `/api/confirm` are proxied server-side to cloud DB API.

### Deploy Version Check (recommended)

The app exposes `GET /api/version` and returns:
- `data.app_mode`
- `data.build_sha`
- `data.build_tag`
- `data.build_time`

Suggested post-deploy check:
```bash
curl -sS 'https://<deine-coolify-app-url>/api/version'
```

Build metadata behavior:
- `build_sha`: uses `APP_BUILD_SHA` if set, otherwise falls back to Git SHA.
- `build_tag` / `build_time`: use `APP_BUILD_TAG` / `APP_BUILD_TIME` if set, otherwise `unknown`.

Pros/Cons of filling build metadata envs:
- Pros:
  - exact deploy traceability (especially for rollback/hotfix scenarios)
  - clearer audits (`which image was deployed when`)
  - no ambiguity if multiple deploys use similar code state
- Cons:
  - extra release discipline (you must set/update values per deploy)
  - mismatch risk if values are copied manually and not automated

If you want to fill them in Coolify:
1. In the app environment set:
   - `APP_BUILD_SHA=<short-git-sha>`
   - `APP_BUILD_TAG=<release-tag>`
   - `APP_BUILD_TIME=<UTC timestamp, e.g. 2026-03-07T11:30:00Z>`
2. Redeploy.
3. Verify:
```bash
curl -sS 'https://<deine-coolify-app-url>/api/version'
```
4. Optional strict smoke check:
```bash
EXPECTED_APP_MODE='cloud_api' EXPECTED_BUILD_SHA='<short-sha>' BASE_URL='https://<deine-coolify-app-url>' ./scripts/smoke_test.sh
```

## Empfohlener Testablauf (2 Phasen)

1. Lokal komplett testen (inkl. Datenmigration):
```bash
cp .env.example .env
docker compose up --build -d

SOURCE_DATABASE_URL='postgresql://user:pass@old-host:5432/dbname' \
TARGET_DATABASE_URL='postgresql://user:pass@localhost:5432/gatewaychef' \
IMPORT_MODE='schema-and-data' \
./scripts/import_legacy_dump.sh

BASE_URL='http://localhost:5000' ./scripts/smoke_test.sh
```

2. Nach Installation auf Coolify erneut testen:
```bash
BASE_URL='https://<deine-coolify-app-url>' ./scripts/smoke_test.sh
```

Hinweis:
- In `cloud_api` mode ueberspringt `smoke_test.sh` automatisch `/api/auth/*` und testet nur Root + DB-Endpunkte.
- Optional strict check:
```bash
EXPECTED_APP_MODE='cloud_api' EXPECTED_BUILD_SHA='<short-sha>' BASE_URL='https://<deine-coolify-app-url>' ./scripts/smoke_test.sh
```

Optionaler Schreibtest (nur mit dedizierter Test-IP):
```bash
RUN_WRITE_SMOKE=true TEST_VPN_IP='10.0.0.123' BASE_URL='http://localhost:5000' ./scripts/smoke_test.sh
```



## Building Standalone Executables

We use [PyInstaller](https://pyinstaller.org/) to create standalone executables. A `gatewaychef.spec` file is provided to configure the build.

### Windows One-Click Build Script

For Windows you can run a single PowerShell script from the `provisioner` folder:

```powershell
.\build_windows.ps1
```

This will:
- create `.venv`
- install dependencies
- install PyInstaller
- ensure `.env` exists and sets `PORT` (default `5000`)
- build the EXE

To override the port:

```powershell
.\build_windows.ps1 -Port 5000
```

### 1. Install PyInstaller
Ensure your virtual environment is active, then install PyInstaller if it's not already in `requirements.txt`:
```bash
pip install pyinstaller
```

### 2. Build the Executable

Run the following command in your terminal (same for Windows, macOS, and Linux):

```bash
pyinstaller --noconfirm gatewaychef.spec
```

### 3. Locate the Output

After a successful build, you will find the executable in the `dist/` directory:

-   **Windows:** `dist\GatewayChef\GatewayChef.exe`
-   **macOS/Linux:** `dist/GatewayChef/GatewayChef`

The `dist/GatewayChef` folder is portable. You can zip this folder and distribute it. It contains the executable and all necessary internal dependencies.

## Port (Default 5000)

By default the app runs on `http://localhost:5000` on Windows/macOS/Linux.
To change it, set `PORT` in `.env`:

```text
PORT=5000
```

### Platform-Specific Notes

#### Windows
-   **Console Encoding:** The application handles Windows console encoding (e.g., `cp850`, `cp1252`) automatically to prevent crashes when capturing output from system commands like `ping`.
-   **Antivirus:** Some antivirus software might flag PyInstaller-generated EXEs as false positives. If this happens, exclude the `dist` folder.

#### macOS
-   **Permissions:** You might need to grant the application permission to access the network or local network devices depending on macOS security settings.
-   **Signing:** The generated executable is not code-signed. To distribute it to other users without them seeing "Unidentified Developer" warnings, you would need to sign and notarize the app using an Apple Developer ID.

#### Linux
-   **GLIBC:** Binaries built with PyInstaller are linked against the system's `glibc`. For maximum compatibility, build on an older distribution (like CentOS 7 or Ubuntu 18.04) or ensuring the target system has a compatible `glibc` version.

## Troubleshooting

-   **"NameError: name 'file' is not defined" during build:**
    -   This issue has been fixed in `gatewaychef.spec` by using `os.getcwd()` instead of `__file__`. Ensure you are using the latest version of the spec file.

-   **Missing Data Files:**
    -   If the app crashes saying it can't find `templates` or `static` files, ensure the `gatewaychef.spec` correctly includes them in `datas=[]`. The current spec file expects `templates` and `static` folders in the project root.


### Smoke Test with API token

If `API_SERVICE_TOKEN` is set in cloud, run smoke with:

```bash
API_TOKEN='<token>' BASE_URL='https://<deine-coolify-app-url>' ./scripts/smoke_test.sh
```


### Token Klarstellung

- `API_SERVICE_TOKEN`: gleich in lokaler App und Cloud API setzen.
- `VPN_PING_SERVICE_TOKEN`: gleich in lokaler App und Cloud API setzen.
- `JWT_SECRET`: getrenntes Thema fuer User-Login (`/api/auth/*`), fuer den aktuellen DB/Ping-Betrieb nicht zwingend.

### Optional fuer Local-App Betrieb

- `ENABLE_LOCAL_AUTH=true|false`
  - `true` (Default): lokale `/api/auth/*` Routen sind aktiv.
  - `false`: Auth-Routen werden nicht registriert (nuetzlich fuer reinen Local+Cloud-DB-Proxy Betrieb).
- `SKIP_AUTH=true|false`
  - Nur Operator-/Testhinweis in der UI (Badge `Auth: SKIP (Test)`).
  - Veraendert keine API-Security automatisch; ist fuer Smoke/Runtime-Transparenz gedacht.
