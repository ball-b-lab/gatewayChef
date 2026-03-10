import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from db.connection import get_db_connection
from gatewaychef_v2.errors import GatewayChefV2Error
from gatewaychef_v2.workflow import ensure_transition


def _utcnow():
    return datetime.now(timezone.utc)


class JsonProvisioningRepository:
    def __init__(self, path=None):
        self.path = Path(path or Path(__file__).resolve().parent / "data" / "provisioning_runs.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"runs": {}, "events": {}})

    def _read(self):
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload):
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
        temp.replace(self.path)

    def create_run(self, payload):
        run_id = str(uuid.uuid4())
        now = _utcnow().isoformat()
        record = {
            "run_id": run_id,
            "state": payload["state"],
            "operator_name": payload["operator_name"],
            "gateway_name": payload["gateway_name"],
            "serial_number": payload["serial_number"],
            "sim_vendor_id": payload["sim_vendor_id"],
            "sim_iccid": payload["sim_iccid"],
            "client_id": payload.get("client_id"),
            "client_name": payload.get("client_name"),
            "lns": payload.get("lns"),
            "manufacturer": payload.get("manufacturer"),
            "gateway_type": payload.get("gateway_type"),
            "requested_by": payload.get("requested_by"),
            "context": payload.get("context", {}),
            "status": payload.get("status", {}),
            "report": payload.get("report", {}),
            "last_error_code": None,
            "last_error_message": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        with self._lock:
            store = self._read()
            store["runs"][run_id] = record
            store["events"].setdefault(run_id, [])
            self._write(store)
        return run_id

    def get_run(self, run_id):
        with self._lock:
            store = self._read()
            run = store["runs"].get(run_id)
        if not run:
            raise GatewayChefV2Error(
                "Provisionierungslauf nicht gefunden.",
                code="run_not_found",
                status_code=404,
            )
        return dict(run)

    def update_run(
        self,
        run_id,
        *,
        next_state=None,
        fields=None,
        context=None,
        status=None,
        report=None,
        last_error=None,
        clear_error=False,
        completed=False,
    ):
        with self._lock:
            store = self._read()
            run = store["runs"].get(run_id)
            if not run:
                raise GatewayChefV2Error(
                    "Provisionierungslauf nicht gefunden.",
                    code="run_not_found",
                    status_code=404,
                )
            if next_state:
                ensure_transition(run["state"], next_state)
                run["state"] = next_state
            if fields:
                for key, value in fields.items():
                    run[key] = value
            if context:
                merged = dict(run.get("context") or {})
                merged.update(context)
                run["context"] = merged
            if status:
                merged = dict(run.get("status") or {})
                merged.update(status)
                run["status"] = merged
            if report is not None:
                run["report"] = report
            if clear_error:
                run["last_error_code"] = None
                run["last_error_message"] = None
            if last_error:
                run["last_error_code"] = last_error.get("code")
                run["last_error_message"] = last_error.get("message")
            run["updated_at"] = _utcnow().isoformat()
            if completed:
                run["completed_at"] = run["updated_at"]
            store["runs"][run_id] = run
            self._write(store)

    def append_event(self, run_id, event):
        with self._lock:
            store = self._read()
            store["events"].setdefault(run_id, []).append(
                {
                    "stage": event.get("stage"),
                    "severity": event.get("severity", "info"),
                    "event_type": event.get("event_type", "event"),
                    "message": event.get("message"),
                    "payload": event.get("payload", {}),
                    "created_at": _utcnow().isoformat(),
                }
            )
            self._write(store)

    def list_events(self, run_id):
        with self._lock:
            store = self._read()
            return list(store["events"].get(run_id, []))


class PostgresProvisioningRepository:
    def create_run(self, payload):
        run_id = str(uuid.uuid4())
        now = _utcnow()
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO provisioning_v2_runs (
                        run_id,
                        state,
                        operator_name,
                        gateway_name,
                        serial_number,
                        sim_vendor_id,
                        sim_iccid,
                        client_id,
                        client_name,
                        lns,
                        manufacturer,
                        gateway_type,
                        requested_by,
                        context_json,
                        status_json,
                        report_json,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        payload["state"],
                        payload["operator_name"],
                        payload["gateway_name"],
                        payload["serial_number"],
                        payload["sim_vendor_id"],
                        payload["sim_iccid"],
                        payload.get("client_id"),
                        payload.get("client_name"),
                        payload.get("lns"),
                        payload.get("manufacturer"),
                        payload.get("gateway_type"),
                        payload.get("requested_by"),
                        json.dumps(payload.get("context", {})),
                        json.dumps(payload.get("status", {})),
                        json.dumps(payload.get("report", {})),
                        now,
                        now,
                    ),
                )
            conn.commit()
            return run_id
        finally:
            conn.close()

    def get_run(self, run_id):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT run_id, state, operator_name, gateway_name, serial_number,
                           sim_vendor_id, sim_iccid, client_id, client_name, lns,
                           manufacturer, gateway_type, requested_by, context_json,
                           status_json, report_json, last_error_code, last_error_message,
                           created_at, updated_at, completed_at
                    FROM provisioning_v2_runs
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            raise GatewayChefV2Error(
                "Provisionierungslauf nicht gefunden.",
                code="run_not_found",
                status_code=404,
            )

        return {
            "run_id": row[0],
            "state": row[1],
            "operator_name": row[2],
            "gateway_name": row[3],
            "serial_number": row[4],
            "sim_vendor_id": row[5],
            "sim_iccid": row[6],
            "client_id": row[7],
            "client_name": row[8],
            "lns": row[9],
            "manufacturer": row[10],
            "gateway_type": row[11],
            "requested_by": row[12],
            "context": row[13] or {},
            "status": row[14] or {},
            "report": row[15] or {},
            "last_error_code": row[16],
            "last_error_message": row[17],
            "created_at": row[18].isoformat() if row[18] else None,
            "updated_at": row[19].isoformat() if row[19] else None,
            "completed_at": row[20].isoformat() if row[20] else None,
        }

    def update_run(
        self,
        run_id,
        *,
        next_state=None,
        fields=None,
        context=None,
        status=None,
        report=None,
        last_error=None,
        clear_error=False,
        completed=False,
    ):
        run = self.get_run(run_id)
        current_state = run["state"]
        if next_state:
            ensure_transition(current_state, next_state)
        merged_context = dict(run.get("context") or {})
        merged_status = dict(run.get("status") or {})
        merged_report = dict(run.get("report") or {})
        merged_fields = {
            "operator_name": run["operator_name"],
            "gateway_name": run["gateway_name"],
            "serial_number": run["serial_number"],
            "sim_vendor_id": run["sim_vendor_id"],
            "sim_iccid": run["sim_iccid"],
            "client_id": run.get("client_id"),
            "client_name": run.get("client_name"),
            "lns": run.get("lns"),
            "manufacturer": run.get("manufacturer"),
            "gateway_type": run.get("gateway_type"),
            "requested_by": run.get("requested_by"),
        }
        if fields:
            merged_fields.update(fields)
        if context:
            merged_context.update(context)
        if status:
            merged_status.update(status)
        if report is not None:
            merged_report = report

        error_code = run.get("last_error_code")
        error_message = run.get("last_error_message")
        if clear_error:
            error_code = None
            error_message = None
        if last_error:
            error_code = last_error.get("code")
            error_message = last_error.get("message")

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE provisioning_v2_runs
                    SET state = %s,
                        operator_name = %s,
                        gateway_name = %s,
                        serial_number = %s,
                        sim_vendor_id = %s,
                        sim_iccid = %s,
                        client_id = %s,
                        client_name = %s,
                        lns = %s,
                        manufacturer = %s,
                        gateway_type = %s,
                        requested_by = %s,
                        context_json = %s,
                        status_json = %s,
                        report_json = %s,
                        last_error_code = %s,
                        last_error_message = %s,
                        updated_at = now(),
                        completed_at = CASE WHEN %s THEN now() ELSE completed_at END
                    WHERE run_id = %s
                    """,
                    (
                        next_state or current_state,
                        merged_fields["operator_name"],
                        merged_fields["gateway_name"],
                        merged_fields["serial_number"],
                        merged_fields["sim_vendor_id"],
                        merged_fields["sim_iccid"],
                        merged_fields["client_id"],
                        merged_fields["client_name"],
                        merged_fields["lns"],
                        merged_fields["manufacturer"],
                        merged_fields["gateway_type"],
                        merged_fields["requested_by"],
                        json.dumps(merged_context),
                        json.dumps(merged_status),
                        json.dumps(merged_report),
                        error_code,
                        error_message,
                        completed,
                        run_id,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def append_event(self, run_id, event):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO provisioning_v2_events (
                        run_id, stage, severity, event_type, message, payload_json, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        run_id,
                        event.get("stage"),
                        event.get("severity", "info"),
                        event.get("event_type", "event"),
                        event.get("message"),
                        json.dumps(event.get("payload", {})),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def list_events(self, run_id):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT stage, severity, event_type, message, payload_json, created_at
                    FROM provisioning_v2_events
                    WHERE run_id = %s
                    ORDER BY id
                    """,
                    (run_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        return [
            {
                "stage": row[0],
                "severity": row[1],
                "event_type": row[2],
                "message": row[3],
                "payload": row[4] or {},
                "created_at": row[5].isoformat() if row[5] else None,
            }
            for row in rows
        ]


class InMemoryProvisioningRepository:
    def __init__(self):
        self.runs = {}
        self.events = {}
        self.seq = 0

    def create_run(self, payload):
        self.seq += 1
        run_id = f"run-{self.seq}"
        now = _utcnow().isoformat()
        self.runs[run_id] = {
            "run_id": run_id,
            "state": payload["state"],
            "operator_name": payload["operator_name"],
            "gateway_name": payload["gateway_name"],
            "serial_number": payload["serial_number"],
            "sim_vendor_id": payload["sim_vendor_id"],
            "sim_iccid": payload["sim_iccid"],
            "client_id": payload.get("client_id"),
            "client_name": payload.get("client_name"),
            "lns": payload.get("lns"),
            "manufacturer": payload.get("manufacturer"),
            "gateway_type": payload.get("gateway_type"),
            "requested_by": payload.get("requested_by"),
            "context": payload.get("context", {}),
            "status": payload.get("status", {}),
            "report": payload.get("report", {}),
            "last_error_code": None,
            "last_error_message": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        self.events[run_id] = []
        return run_id

    def get_run(self, run_id):
        run = self.runs.get(run_id)
        if not run:
            raise GatewayChefV2Error(
                "Provisionierungslauf nicht gefunden.",
                code="run_not_found",
                status_code=404,
            )
        return dict(run)

    def update_run(
        self,
        run_id,
        *,
        next_state=None,
        fields=None,
        context=None,
        status=None,
        report=None,
        last_error=None,
        clear_error=False,
        completed=False,
    ):
        run = self.get_run(run_id)
        if next_state:
            ensure_transition(run["state"], next_state)
            run["state"] = next_state
        if fields:
            for key, value in fields.items():
                run[key] = value
        if context:
            merged = dict(run.get("context") or {})
            merged.update(context)
            run["context"] = merged
        if status:
            merged = dict(run.get("status") or {})
            merged.update(status)
            run["status"] = merged
        if report is not None:
            run["report"] = report
        if clear_error:
            run["last_error_code"] = None
            run["last_error_message"] = None
        if last_error:
            run["last_error_code"] = last_error.get("code")
            run["last_error_message"] = last_error.get("message")
        run["updated_at"] = _utcnow().isoformat()
        if completed:
            run["completed_at"] = run["updated_at"]
        self.runs[run_id] = run

    def append_event(self, run_id, event):
        self.events.setdefault(run_id, []).append(
            {
                "stage": event.get("stage"),
                "severity": event.get("severity", "info"),
                "event_type": event.get("event_type", "event"),
                "message": event.get("message"),
                "payload": event.get("payload", {}),
                "created_at": _utcnow().isoformat(),
            }
        )

    def list_events(self, run_id):
        return list(self.events.get(run_id, []))
