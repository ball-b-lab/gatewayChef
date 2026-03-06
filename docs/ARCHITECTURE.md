# Architecture & System Overview

This document describes the system architecture, component interaction, and data flow of the GatewayChef application.

## High-Level Architecture

GatewayChef is a standalone Flask web application designed to run on a local technician's machine. It orchestrates the provisioning of LoRa gateways by interacting with:

1.  **Local Hardware:** The Milesight Gateway (via HTTP/REST and Node-RED endpoints).
2.  **Cloud Database:** A PostgreSQL database storing inventory and SIM data.
3.  **Third-Party APIs:** ChirpStack (LoRaWAN Network Server) and Milesight Development Platform.

### Components

-   **Frontend (UI):**
    -   **Technology:** HTML5, Bootstrap 5, Vanilla JavaScript.
    -   **Responsibility:** User interaction, state management (in-memory), orchestrating API calls to the backend, rendering status feedback.
    -   **Entry Point:** `templates/index.html` (Single Page Application feel).

-   **Backend (API Layer):**
    -   **Technology:** Python 3.12+, Flask.
    -   **Responsibility:**
        -   Exposing a JSON API for the frontend.
        -   Handling business logic (validation, data transformation).
        -   Managing external connections (DB, Gateway, APIs).
        -   Running system commands (Ping).
    -   **Entry Point:** `app.py`.

-   **Persistence Layer:**
    -   **Technology:** PostgreSQL (Cloud).
    -   **Responsibility:** Permanent storage of `gateway_inventory`, `sim_cards`, and `sim_vendors`.
    -   **Access:** Direct SQL queries via `psycopg2` (managed in `routes/db.py`).

## Data Flow & Provisioning Lifecycle

The provisioning process follows a linear 4-step workflow:

1.  **Initialization:**
    -   App starts, loads configuration from `.env`.
    -   Frontend loads, fetches SIM vendor lists (`GET /api/sim/vendors`).
    -   Auto-discovery begins: probing the gateway (`192.168.1.1`) for device info.

2.  **Step 1: Customer Data & Identity:**
    -   Technician inputs/verifies customer data.
    -   App fetches a new, free VPN IP from the DB (`GET /api/db/fetch-ip`).
    -   Customer data is linked to the IP in the DB (`POST /api/db/customer-update`).

3.  **Step 2: Gateway Status & Discovery:**
    -   Backend polls Gateway endpoints (`/node-red/device-info`, `/node-red/device-info-lora`).
    -   Backend checks Cloud APIs (ChirpStack, Milesight) for existing registrations.
    -   Frontend aggregates this data into a "Status Matrix" (Gateway vs. Target/DB).

4.  **Step 3: Configuration & Sync:**
    -   **ChirpStack:** Checks if EUI exists; offers creation if missing.
    -   **Milesight:** Checks if EUI exists; offers registration if missing.
    -   **Database:** Final "Provision" step (`POST /api/provision`) saves the complete state (EUI, Serial, SIM, Config) to the PostgreSQL database.

5.  **Step 4: Confirmation:**
    -   Final handshake to mark the gateway as `DEPLOYED` in the database (`POST /api/confirm`).

## File Structure

```
/
├── app.py                  # Application entry point & configuration loading
├── gatewaychef.spec        # PyInstaller build specification
├── config.py               # Centralized configuration management
├── requirements.txt        # Python dependencies
├── routes/                 # Blueprint definitions (API endpoints)
│   ├── gateway.py          # Gateway local API interactions
│   ├── db.py               # Database operations
│   ├── chirpstack.py       # ChirpStack API integration
│   ├── milesight.py        # Milesight API integration
│   ├── network.py          # System network tools (Ping)
│   └── webservice.py       # (Legacy/Future) External web service hooks
├── services/               # Business logic & reusable service layers
├── static/                 # Static assets (CSS, JS, Images, Help MD)
│   ├── js/                 # Frontend logic (main.js, ui.js, api.js, workflow.js)
│   └── help/               # Contextual help content (JSON + Markdown)
├── templates/              # HTML templates (Jinja2)
└── utils/                  # Helper functions (Response formatting, etc.)
```

## Security & Configuration

-   **Credentials:** All sensitive credentials (DB passwords, API tokens) are loaded from environment variables (`.env`).
-   **Error Handling:**
    -   The backend intercepts exceptions and returns JSON error responses (`500`, `502`, `504`) instead of HTML stack traces.
    -   Connection timeouts are explicitly handled for network operations.
-   **Cross-Platform:** The application uses `platform`-aware logic for system commands (e.g., `ping` arguments) and handles filesystem path encoding differences.

## Deployment View

The application is designed to be bundled as a single-folder executable using PyInstaller.

-   **Spec File:** `gatewaychef.spec` defines the build process, including hidden imports and data file inclusion (`templates`, `static`, `.env`).
-   **Execution:** The resulting executable includes a bundled Python interpreter and all dependencies, requiring no pre-installed Python on the target machine.
