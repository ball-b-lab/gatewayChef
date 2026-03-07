# GatewayChef Provisioner

A robust Flask-based web application for provisioning Milesight LoRa Gateways. It streamlines the process of configuring device settings, assigning VPN IPs, and syncing data with PostgreSQL, ChirpStack, and the Milesight Development Platform.

## 📚 Documentation

-   **[Architecture & System Overview](docs/ARCHITECTURE.md)**: Understand the system components, data flow, and file structure.
-   **[Deployment Guide](docs/DEPLOYMENT.md)**: Instructions for running locally and building standalone executables for Windows, macOS, and Linux.
-   **[Coolify Runtime Architecture](docs/COOLIFY_RUNTIME_ARCHITECTURE.md)**: What runs where (containers, ports, proxy, envs, migration paths).
-   **[Target Architecture (Local + Cloud)](docs/TARGET_ARCHITECTURE_LOCAL_CLOUD.md)**: Final operating model with containers, ports, reverse proxy, envs, and migration roles.
-   **[API Reference](docs/API.md)**: Detailed specification of the backend JSON API.

## ✨ Features

-   **Automated Discovery:** Fetches device info directly from the gateway via Node-RED and HTTP endpoints.
-   **Inventory Management:** Manages VPN IPs, SIM cards, and gateway configurations in a cloud PostgreSQL database.
-   **Integration:** seamless integration with ChirpStack (LoRaWAN Network Server) and Milesight Development Platform.
-   **Cross-Platform:** Runs on Windows, macOS, and Linux (Source or Standalone EXE).
-   **Resilience:** Handles network timeouts and platform-specific quirks (e.g., Windows console encoding) gracefully.

## 🚀 Quick Start (Local Development)

1.  **Clone & Install:**
    ```bash
    git clone <repository>
    cd provisioner
    python3 -m venv venv
    source venv/bin/activate  # or venv\Scripts\activate on Windows
    pip install -r requirements.txt
    ```

2.  **Configure:**
    Copy `.env.example` to `.env` and update the values:
    ```ini
    DB_HOST=your-db-host
    DB_USER=your-user
    DB_PASSWORD=your-password
    # ... see .env.example for full list
    ```

3.  **Run:**
    ```bash
    python scripts/migrate.py
    python app.py
    ```
    The application will automatically open `http://localhost:5000` in your default browser.

## Authentication API

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me` (requires `Authorization: Bearer <token>`)

## Docker Quick Start

```bash
cp .env.example .env
docker compose up --build
```

## Legacy DB Cutover

- Import-Script: `scripts/import_legacy_dump.sh`
- Checkliste: `docs/CUTOVER_CHECKLIST.md`

## 📦 Building Executables

To build a standalone executable for your current platform:

```bash
pip install pyinstaller
pyinstaller --noconfirm gatewaychef.spec
```

See the [Deployment Guide](docs/DEPLOYMENT.md) for more details.

## Smoke Test

```bash
BASE_URL='http://localhost:5000' ./scripts/smoke_test.sh
```

Optional write smoke (uses test data):

```bash
RUN_WRITE_SMOKE=true TEST_VPN_IP='10.0.0.123' BASE_URL='http://localhost:5000' ./scripts/smoke_test.sh
```
