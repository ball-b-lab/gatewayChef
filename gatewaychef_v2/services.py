from gatewaychef_v2.config import current_env_status, missing_for_stage
from gatewaychef_v2.errors import GatewayChefV2Error, StateTransitionError
from gatewaychef_v2.workflow import (
    STATE_CLOUD_SYNCED,
    STATE_CONFIG_APPLIED,
    STATE_CONFIG_PENDING,
    STATE_DONE,
    STATE_DRAFT,
    STATE_FAILED,
    STATE_PRECHECK_PASSED,
    STATE_VERIFIED,
)


def _sanitize_status_payload(payload):
    clean = dict(payload or {})
    if "private_key" in clean:
        clean["private_key"] = "***"
    return clean


class ProvisioningOrchestrator:
    def __init__(
        self,
        repository,
        *,
        gateway,
        inventory,
        chirpstack,
        milesight,
        webservice,
        network,
        enforce_env_guards=True,
    ):
        self.repository = repository
        self.gateway = gateway
        self.inventory = inventory
        self.chirpstack = chirpstack
        self.milesight = milesight
        self.webservice = webservice
        self.network = network
        self.enforce_env_guards = enforce_env_guards

    def discover_gateway(self):
        gateway_info = self.gateway.fetch_device_info()
        lora_info = self.gateway.fetch_lora_info()
        lora_health = self.gateway.fetch_lora_health()

        device = gateway_info.get("device", {}) if isinstance(gateway_info, dict) else {}
        current_vpn_ip = (device.get("vpn_ip") or gateway_info.get("vpn_ip") or "").strip()
        current_ssid = (device.get("wifi_ssid") or device.get("ssid") or gateway_info.get("wifi_ssid") or "").strip()
        discovered_eui = (
            device.get("eui")
            or gateway_info.get("eui")
            or lora_info.get("gatewayEui")
            or lora_info.get("gatewayId")
            or ""
        ).strip().upper()
        db_record = None
        if current_vpn_ip or discovered_eui:
            db_record = self.inventory.fetch_gateway_record(vpn_ip=current_vpn_ip or None, eui=discovered_eui or None)
        next_ip = self.inventory.peek_next_free_ip()

        is_golden = current_ssid == "bbdbmon_golden"
        is_configured = current_ssid.startswith("bbdbmon_") and not is_golden
        phase = "NEEDS_CONFIGURATION" if is_golden else ("CONFIGURED" if is_configured else "IN_SERVICE_OR_PARTIAL")
        suggested = {
            "gateway_name": (db_record or {}).get("gateway_name") or "",
            "serial_number": (db_record or {}).get("serial_number") or "",
            "sim_vendor_id": str((db_record or {}).get("sim_vendor_id") or ""),
            "sim_iccid": (db_record or {}).get("sim_iccid") or "",
            "current_vpn_ip": current_vpn_ip,
            "current_ssid": current_ssid,
            "current_eui": discovered_eui,
            "next_free_vpn_ip": (next_ip or {}).get("vpn_ip"),
            "operation_mode": "reconcile" if is_configured else "new_config",
        }
        ping_result = None
        if current_vpn_ip:
            try:
                ping_result = self.network.ping(current_vpn_ip)
            except Exception as exc:
                ping_result = {"ok": False, "output": str(exc), "via": "cloud_proxy"}
        discrepancies = self._build_discovery_discrepancies(
            current_vpn_ip=current_vpn_ip,
            current_ssid=current_ssid,
            discovered_eui=discovered_eui,
            db_record=db_record,
            lora_health=lora_health,
            ping_result=ping_result,
            is_golden=is_golden,
            is_configured=is_configured,
        )
        return {
            "gateway_info": gateway_info,
            "lora_info": lora_info,
            "lora_health": lora_health,
            "db_record": db_record,
            "suggested_form": suggested,
            "discrepancies": discrepancies,
            "ping_result": ping_result,
            "classification": {
                "is_golden": is_golden,
                "is_configured": is_configured,
                "phase": phase,
                "ssid_is_finalized": bool(is_configured),
                "requires_new_vpn": is_golden,
                "ssid_change_must_be_last": True,
            },
        }

    def create_run(self, payload):
        required = ["operator_name", "gateway_name", "serial_number", "sim_vendor_id", "sim_iccid"]
        missing = [field for field in required if not str(payload.get(field) or "").strip()]
        if missing:
            raise GatewayChefV2Error(
                "Pflichtfelder fehlen.",
                code="missing_fields",
                status_code=400,
                details={"missing": missing},
                stage="create_run",
            )

        run_id = self.repository.create_run(
            {
                "state": STATE_DRAFT,
                "operator_name": payload["operator_name"].strip(),
                "gateway_name": payload["gateway_name"].strip(),
                "serial_number": payload["serial_number"].strip(),
                "sim_vendor_id": str(payload["sim_vendor_id"]).strip(),
                "sim_iccid": payload["sim_iccid"].strip(),
                "client_id": (payload.get("client_id") or "").strip() or None,
                "client_name": (payload.get("client_name") or "").strip() or None,
                "lns": (payload.get("lns") or "chirpstack").strip(),
                "manufacturer": (payload.get("manufacturer") or "Milesight").strip(),
                "gateway_type": (payload.get("gateway_type") or "UG67").strip(),
                "requested_by": payload.get("requested_by") or payload["operator_name"].strip(),
                "context": {
                    "env_status": current_env_status(),
                    "operation_mode": (payload.get("operation_mode") or "reconcile").strip(),
                    "current_vpn_ip": (payload.get("current_vpn_ip") or "").strip() or None,
                    "current_ssid": (payload.get("current_ssid") or "").strip() or None,
                    "current_eui": (payload.get("discovered_eui") or "").strip() or None,
                },
                "status": {"created": True, "operation_mode": (payload.get("operation_mode") or "reconcile").strip()},
                "report": {},
            }
        )
        self.repository.append_event(
            run_id,
            {
                "stage": "create_run",
                "event_type": "run_created",
                "message": "Provisionierungslauf angelegt.",
                "payload": {"operator_name": payload["operator_name"], "gateway_name": payload["gateway_name"]},
            },
        )
        return self.get_run(run_id)

    def get_run(self, run_id):
        run = self.repository.get_run(run_id)
        run["events"] = self.repository.list_events(run_id)
        return run

    def precheck(self, run_id):
        run = self.repository.get_run(run_id)
        try:
            gateway_info = self.gateway.fetch_device_info()
            lora_info = self.gateway.fetch_lora_info()
            lora_health = self.gateway.fetch_lora_health()
            next_ip = self.inventory.peek_next_free_ip()
            missing_inventory = missing_for_stage("inventory")
            if not next_ip:
                raise GatewayChefV2Error(
                    "Kein freier VPN-Eintrag verfuegbar.",
                    code="no_inventory_capacity",
                    status_code=409,
                    stage="precheck",
                )
            if self.enforce_env_guards and missing_inventory:
                raise GatewayChefV2Error(
                    "Kritische ENV-Werte fuer Inventar fehlen.",
                    code="missing_env",
                    status_code=500,
                    details={"missing": missing_inventory},
                    stage="precheck",
                )
            discovered_eui = (
                gateway_info.get("device", {}).get("eui")
                or gateway_info.get("eui")
                or lora_info.get("gateway_id")
                or ""
            ).strip().upper()
            if not discovered_eui:
                raise GatewayChefV2Error(
                    "Gateway liefert keine EUI.",
                    code="gateway_identity_missing",
                    status_code=422,
                    stage="precheck",
                )
            status = {
                "precheck_gateway_reachable": True,
                "precheck_inventory_ready": True,
                "precheck_discovered_eui": discovered_eui,
                "precheck_lora_status": lora_health.get("status"),
                "precheck_lns_connected": bool(lora_health.get("lns_connected")),
            }
            context = {
                "gateway_info": gateway_info,
                "lora_info": lora_info,
                "lora_health": lora_health,
                "discovered_eui": discovered_eui,
                "peek_next_ip": next_ip["vpn_ip"],
            }
            self.repository.update_run(
                run_id,
                next_state=STATE_PRECHECK_PASSED,
                context=context,
                status=status,
                clear_error=True,
            )
            self.repository.append_event(
                run_id,
                {
                    "stage": "precheck",
                    "event_type": "precheck_passed",
                    "message": "Preflight-Checks erfolgreich.",
                    "payload": {
                        "discovered_eui": discovered_eui,
                        "peek_next_ip": next_ip["vpn_ip"],
                        "lora_status": lora_health.get("status"),
                        "lns_connected": bool(lora_health.get("lns_connected")),
                    },
                },
            )
        except GatewayChefV2Error as exc:
            self._fail_run(run_id, exc)
            raise
        except Exception as exc:
            error = GatewayChefV2Error(
                f"Preflight fehlgeschlagen: {exc}",
                code="precheck_failed",
                status_code=502,
                stage="precheck",
                retryable=True,
            )
            self._fail_run(run_id, error)
            raise error
        return self.get_run(run_id)

    def reserve(self, run_id):
        run = self.repository.get_run(run_id)
        current_context = dict(run.get("context") or {})
        if current_context.get("reserved_inventory"):
            return self.get_run(run_id)
        if run["state"] not in {STATE_PRECHECK_PASSED, STATE_FAILED}:
            raise StateTransitionError(
                "Ressourcen duerfen erst nach erfolgreichem Preflight reserviert werden.",
                details={"current_state": run["state"]},
            )
        try:
            operation_mode = (run.get("context", {}).get("operation_mode") or "reconcile").strip()
            current_vpn_ip = run.get("context", {}).get("current_vpn_ip")
            existing = None
            if current_vpn_ip:
                existing = self.inventory.fetch_gateway_record(vpn_ip=current_vpn_ip)
            if operation_mode != "new_config" and existing:
                vpn_key = self.inventory.fetch_vpn_key(existing["vpn_ip"]) or {}
                reserved = {
                    "vpn_ip": existing["vpn_ip"],
                    "private_key": vpn_key.get("private_key"),
                    "apn": existing.get("apn"),
                    "wifi_ssid": existing.get("wifi_ssid"),
                    "sim_id": existing.get("sim_id"),
                    "sim_card_id": existing.get("sim_card_id"),
                    "source": "existing_record",
                }
            else:
                reserved = self.inventory.reserve_inventory(
                    gateway_name=run["gateway_name"],
                    serial_number=run["serial_number"],
                    sim_vendor_id=run["sim_vendor_id"],
                    sim_iccid=run["sim_iccid"],
                )
                reserved["source"] = "new_inventory"
            context = {
                "reserved_inventory": {
                    "vpn_ip": reserved["vpn_ip"],
                    "apn": reserved.get("apn"),
                    "wifi_ssid": reserved.get("wifi_ssid"),
                    "private_key_masked": "***",
                    "sim_id": reserved.get("sim_id"),
                    "source": reserved.get("source"),
                },
                "vpn_ip": reserved["vpn_ip"],
                "wifi_ssid": reserved.get("wifi_ssid"),
                "apn": reserved.get("apn"),
                "db_sim_id": reserved.get("sim_id"),
                "db_sim_card_id": reserved.get("sim_card_id"),
            }
            status = {
                "inventory_reserved": True,
                "vpn_ip": reserved["vpn_ip"],
                "wifi_ssid": reserved.get("wifi_ssid"),
                "inventory_source": reserved.get("source"),
            }
            self.repository.update_run(
                run_id,
                next_state=STATE_CONFIG_PENDING,
                context=context,
                status=status,
                clear_error=True,
            )
            self.repository.append_event(
                run_id,
                {
                    "stage": "reserve",
                    "event_type": "inventory_reserved",
                    "message": "Zielwerte fuer das Gateway vorbereitet.",
                    "payload": _sanitize_status_payload(reserved),
                },
            )
        except GatewayChefV2Error as exc:
            self._fail_run(run_id, exc)
            raise
        except Exception as exc:
            error = GatewayChefV2Error(
                f"Inventarreservierung fehlgeschlagen: {exc}",
                code="inventory_reservation_failed",
                status_code=502,
                stage="reserve",
                retryable=True,
            )
            self._fail_run(run_id, error)
            raise error
        return self.get_run(run_id)

    def confirm_config_applied(self, run_id, payload):
        run = self.repository.get_run(run_id)
        if run["state"] not in {STATE_CONFIG_PENDING, STATE_FAILED}:
            raise StateTransitionError(
                "Konfiguration kann in diesem Zustand nicht bestaetigt werden.",
                details={"current_state": run["state"]},
            )
        if payload.get("confirm_apply") is not True:
            raise GatewayChefV2Error(
                "Die Gateway-Konfiguration muss aktiv bestaetigt werden.",
                code="confirmation_required",
                status_code=400,
                stage="confirm_config",
            )
        self.repository.update_run(
            run_id,
            next_state=STATE_CONFIG_APPLIED,
            context={"operator_confirmation": {"confirm_apply": True, "note": payload.get("note")}},
            status={"config_applied": True},
            clear_error=True,
        )
        self.repository.append_event(
            run_id,
            {
                "stage": "confirm_config",
                "event_type": "config_confirmed",
                "message": "Gateway-Konfiguration durch Mitarbeiter bestaetigt.",
                "payload": {"note": payload.get("note")},
            },
        )
        return self.get_run(run_id)

    def sync_cloud(self, run_id, *, webservice_credentials=None):
        run = self.repository.get_run(run_id)
        if run["state"] not in {STATE_CONFIG_APPLIED, STATE_FAILED, STATE_CLOUD_SYNCED}:
            raise StateTransitionError(
                "Cloud-Sync ist erst nach bestaetigter Konfiguration erlaubt.",
                details={"current_state": run["state"]},
            )
        missing = missing_for_stage("cloud_sync")
        if self.enforce_env_guards and missing:
            raise GatewayChefV2Error(
                "Kritische ENV-Werte fuer Cloud-Sync fehlen.",
                code="missing_env",
                status_code=500,
                details={"missing": missing},
                stage="cloud_sync",
            )

        eui = self._run_eui(run)
        sync_status = {}

        chirp = self.chirpstack.check_gateway(eui)
        if not chirp.get("exists"):
            self.chirpstack.create_gateway(eui=eui, serial_number=run["serial_number"], gateway_name=run["gateway_name"])
            sync_status["chirpstack_created"] = True
        else:
            sync_status["chirpstack_created"] = False
        sync_status["chirpstack_exists"] = True

        mile = self.milesight.check_device(eui)
        if not mile.get("exists"):
            self.milesight.create_device(eui=eui, serial_number=run["serial_number"], gateway_name=run["gateway_name"])
            sync_status["milesight_created"] = True
        else:
            sync_status["milesight_created"] = False
        sync_status["milesight_exists"] = True

        if run.get("client_id"):
            credentials = self._ensure_webservice_credentials(webservice_credentials)
            web = self.webservice.search_gateway(eui, credentials)
            if not web.get("exists"):
                payload = {
                    "client_id": run["client_id"],
                    "lns": run["lns"],
                    "gateway_name": run["gateway_name"],
                    "serial_number": run["serial_number"],
                    "eui": eui,
                    "sim_iccid": run["sim_iccid"],
                    "sim_id": run.get("context", {}).get("db_sim_id") or "pending",
                    "manufacturer": run["manufacturer"],
                    "gateway_type": run["gateway_type"],
                }
                self.webservice.create_gateway(payload, credentials)
                sync_status["webservice_created"] = True
            else:
                sync_status["webservice_created"] = False
            sync_status["webservice_exists"] = True
        else:
            sync_status["webservice_exists"] = False
            sync_status["webservice_skipped"] = True

        self.repository.update_run(
            run_id,
            next_state=STATE_CLOUD_SYNCED,
            status=sync_status,
            context={"cloud_sync": sync_status},
            clear_error=True,
        )
        self.repository.append_event(
            run_id,
            {
                "stage": "cloud_sync",
                "event_type": "cloud_synced",
                "message": "Cloud-Eintraege synchronisiert.",
                "payload": sync_status,
            },
        )
        return self.get_run(run_id)

    def verify(self, run_id, *, webservice_credentials=None):
        run = self.repository.get_run(run_id)
        if run["state"] not in {STATE_CLOUD_SYNCED, STATE_FAILED, STATE_VERIFIED}:
            raise StateTransitionError(
                "Verifikation ist erst nach Cloud-Sync erlaubt.",
                details={"current_state": run["state"]},
            )
        try:
            eui = self._run_eui(run)
            vpn_ip = run.get("context", {}).get("vpn_ip")
            wifi_ssid = run.get("context", {}).get("wifi_ssid")
            apn = run.get("context", {}).get("apn")
            gateway_info = self.gateway.fetch_device_info()
            lora_info = self.gateway.fetch_lora_info()
            lora_health = self.gateway.fetch_lora_health()
            ping = self.network.ping(vpn_ip)
            db_before = self.inventory.fetch_gateway_record(vpn_ip=vpn_ip)

            report = {
                "gateway_configured": self._gateway_matches(gateway_info, eui=eui, vpn_ip=vpn_ip, wifi_ssid=wifi_ssid),
                "vpn_reachable": bool(ping.get("ok")),
                "lora_health": self._lora_health_ok(lora_health),
                "cloud_sync": {
                    "chirpstack": self.chirpstack.check_gateway(eui).get("exists", False),
                    "milesight": self.milesight.check_device(eui).get("exists", False),
                    "webservice": True,
                },
                "database": False,
                "observed": {
                    "gateway": gateway_info,
                    "lora": lora_info,
                    "lora_health": lora_health,
                    "ping": ping,
                    "db_before": db_before,
                },
                "checks": [],
            }
            if run.get("client_id"):
                credentials = self._ensure_webservice_credentials(webservice_credentials)
                report["cloud_sync"]["webservice"] = self.webservice.search_gateway(eui, credentials).get("exists", False)

            snapshot = {
                "vpn_ip": vpn_ip,
                "eui": eui,
                "serial_number": run["serial_number"],
                "gateway_name": run["gateway_name"],
                "wifi_ssid": wifi_ssid,
                "apn": apn,
                "cellular_status": lora_health.get("status"),
                "lte_connected": bool(gateway_info.get("device", {}).get("cellular_online", True)),
                "cellular_ip": None,
                "vpn_key_present": True,
                "gateway_vendor": run["manufacturer"],
                "gateway_model": run["gateway_type"],
                "lora_gateway_eui": eui,
                "lora_gateway_id": lora_info.get("gateway_id") or eui,
                "lora_active_server": lora_info.get("active_server") or run["lns"],
                "lora_status": lora_info.get("status"),
                "lora_pending": bool(lora_info.get("pending")),
                "status_overall": "VERIFIED",
                "conf_gateway_done": True,
                "sim_iccid": run["sim_iccid"],
                "sim_vendor_id": run["sim_vendor_id"],
                "sim_id": (db_before or {}).get("sim_id") or run.get("context", {}).get("db_sim_id"),
            }
            self.inventory.save_final_snapshot(snapshot)
            db_after = self.inventory.fetch_gateway_record(vpn_ip=vpn_ip)
            report["database"] = self._db_matches(db_after, snapshot)
            report["observed"]["db_after"] = db_after
            report["checks"] = [
                self._check_item("Gateway Konfiguration", report["gateway_configured"]),
                self._check_item("VPN Erreichbarkeit", report["vpn_reachable"]),
                self._check_item("LoRa Health", report["lora_health"]),
                self._check_item("ChirpStack", report["cloud_sync"]["chirpstack"]),
                self._check_item("Milesight", report["cloud_sync"]["milesight"]),
                self._check_item("Webservice", report["cloud_sync"]["webservice"]),
                self._check_item("Datenbank", report["database"]),
            ]
            report["ready"] = all(item["ok"] for item in report["checks"])
            report["release_gate"] = "PASS" if report["ready"] else "BLOCK"
            if not report["ready"]:
                raise GatewayChefV2Error(
                    "Readiness Report nicht bestanden.",
                    code="verification_failed",
                    status_code=409,
                    details={"report": report},
                    stage="verify",
                )
            self.repository.update_run(
                run_id,
                next_state=STATE_VERIFIED,
                report=report,
                status={"verified": True, "release_gate": "PASS"},
                clear_error=True,
            )
            self.repository.append_event(
                run_id,
                {
                    "stage": "verify",
                    "event_type": "verified",
                    "message": "Gateway vollstaendig verifiziert.",
                    "payload": {"release_gate": "PASS"},
                },
            )
        except GatewayChefV2Error as exc:
            self._fail_run(run_id, exc)
            raise
        except Exception as exc:
            error = GatewayChefV2Error(
                f"Verifikation fehlgeschlagen: {exc}",
                code="verification_failed",
                status_code=502,
                stage="verify",
                retryable=True,
            )
            self._fail_run(run_id, error)
            raise error
        return self.get_run(run_id)

    def reveal_secret_bundle(self, run_id, payload):
        run = self.repository.get_run(run_id)
        if payload.get("confirm_secret_access") is not True:
            raise GatewayChefV2Error(
                "Anzeige sensibler Werte muss bestaetigt werden.",
                code="confirmation_required",
                status_code=400,
                stage="reveal_secret",
            )
        vpn_ip = run.get("context", {}).get("vpn_ip")
        secret = self.inventory.fetch_vpn_key(vpn_ip)
        if not secret:
            raise GatewayChefV2Error(
                "VPN-Key nicht gefunden.",
                code="vpn_key_not_found",
                status_code=404,
                stage="reveal_secret",
            )
        self.repository.append_event(
            run_id,
            {
                "stage": "reveal_secret",
                "event_type": "secret_accessed",
                "message": "VPN-Key wurde explizit fuer die lokale Anzeige abgerufen.",
                "payload": {"vpn_ip": vpn_ip},
            },
        )
        return {
            "vpn_ip": vpn_ip,
            "serial_number": secret.get("serial_number"),
            "private_key": secret.get("private_key"),
        }

    def finalize(self, run_id):
        run = self.repository.get_run(run_id)
        if run["state"] != STATE_VERIFIED:
            raise StateTransitionError(
                "Abschluss ist nur nach erfolgreicher Verifikation erlaubt.",
                details={"current_state": run["state"]},
            )
        vpn_ip = run.get("context", {}).get("vpn_ip")
        self.inventory.mark_done(vpn_ip)
        self.repository.update_run(
            run_id,
            next_state=STATE_DONE,
            status={"completed": True},
            completed=True,
            clear_error=True,
        )
        self.repository.append_event(
            run_id,
            {
                "stage": "finalize",
                "event_type": "done",
                "message": "Provisionierungslauf abgeschlossen.",
                "payload": {"vpn_ip": vpn_ip},
            },
        )
        return self.get_run(run_id)

    def _run_eui(self, run):
        return (
            run.get("context", {}).get("discovered_eui")
            or run.get("context", {}).get("gateway_info", {}).get("device", {}).get("eui")
            or ""
        ).strip().upper()

    def _ensure_webservice_credentials(self, credentials):
        if not credentials or not credentials.get("username") or not credentials.get("password"):
            raise GatewayChefV2Error(
                "Webservice-Zugangsdaten fehlen.",
                code="missing_webservice_credentials",
                status_code=400,
                stage="cloud_sync",
            )
        return credentials

    def _gateway_matches(self, gateway_info, *, eui, vpn_ip, wifi_ssid):
        device = gateway_info.get("device", {}) if isinstance(gateway_info, dict) else {}
        observed_eui = (device.get("eui") or gateway_info.get("eui") or "").strip().upper()
        observed_vpn = (device.get("vpn_ip") or gateway_info.get("vpn_ip") or "").strip()
        observed_ssid = (device.get("wifi_ssid") or gateway_info.get("wifi_ssid") or "").strip()
        return observed_eui == eui and observed_vpn == vpn_ip and observed_ssid == wifi_ssid

    def _db_matches(self, record, snapshot):
        if not record:
            return False
        checks = [
            record.get("vpn_ip") == snapshot["vpn_ip"],
            record.get("eui") == snapshot["eui"],
            record.get("wifi_ssid") == snapshot["wifi_ssid"],
            record.get("serial_number") == snapshot["serial_number"],
            record.get("gateway_name") == snapshot["gateway_name"],
            record.get("status_overall") in {"VERIFIED", "DEPLOYED"},
        ]
        return all(checks)

    def _lora_health_ok(self, lora_health):
        if not isinstance(lora_health, dict):
            return False
        status = str(lora_health.get("status") or "").upper()
        lns_connected = bool(lora_health.get("lns_connected"))
        ack = lora_health.get("seconds_since_ack")
        stat = lora_health.get("seconds_since_stat")
        ack_ok = ack is None or ack <= 120
        stat_ok = stat is None or stat <= 120
        return status == "ONLINE" and lns_connected and ack_ok and stat_ok

    def _build_discovery_discrepancies(
        self,
        *,
        current_vpn_ip,
        current_ssid,
        discovered_eui,
        db_record,
        lora_health,
        ping_result,
        is_golden,
        is_configured,
    ):
        items = []
        db = db_record or {}
        if is_golden:
            items.append(
                {
                    "label": "Gateway ist Golden",
                    "ok": False,
                    "detail": "SSID ist bbdbmon_golden. Neue VPN-IP und finale SSID muessen noch gesetzt werden.",
                }
            )
        elif is_configured:
            items.append(
                {
                    "label": "SSID zeigt konfigurierten Zustand",
                    "ok": True,
                    "detail": f"Aktuelle SSID: {current_ssid}",
                }
            )
        else:
            items.append(
                {
                    "label": "SSID wirkt unklar",
                    "ok": False,
                    "detail": f"Aktuelle SSID: {current_ssid or '-'}",
                }
            )

        if db:
            items.extend(
                [
                    {
                        "label": "VPN stimmt mit DB ueberein",
                        "ok": db.get("vpn_ip") == current_vpn_ip,
                        "detail": f"Gateway {current_vpn_ip or '-'} / DB {db.get('vpn_ip') or '-'}",
                    },
                    {
                        "label": "SSID stimmt mit DB ueberein",
                        "ok": db.get("wifi_ssid") == current_ssid,
                        "detail": f"Gateway {current_ssid or '-'} / DB {db.get('wifi_ssid') or '-'}",
                    },
                    {
                        "label": "EUI stimmt mit DB ueberein",
                        "ok": db.get("eui") == discovered_eui,
                        "detail": f"Gateway {discovered_eui or '-'} / DB {db.get('eui') or '-'}",
                    },
                ]
            )
        else:
            items.append(
                {
                    "label": "DB-Zuordnung vorhanden",
                    "ok": False,
                    "detail": "Zu aktueller VPN-IP/EUI wurde kein DB-Eintrag gefunden.",
                }
            )
        if current_vpn_ip:
            items.append(
                {
                    "label": "VPN Ping ueber Cloud API",
                    "ok": bool((ping_result or {}).get("ok")),
                    "detail": (
                        f"VPN {current_vpn_ip} / via {(ping_result or {}).get('via') or 'lokal'} / "
                        f"{(ping_result or {}).get('output') or '-'}"
                    ),
                }
            )

        items.append(
            {
                "label": "LoRa-Verbindung gesund",
                "ok": self._lora_health_ok(lora_health),
                "detail": (
                    f"Status {lora_health.get('status') or '-'}, "
                    f"LNS {bool(lora_health.get('lns_connected'))}, "
                    f"Ack {lora_health.get('seconds_since_ack')}, "
                    f"Stat {lora_health.get('seconds_since_stat')}"
                ),
            }
        )
        return items

    def _check_item(self, label, ok):
        return {"label": label, "ok": bool(ok), "result": "PASS" if ok else "BLOCK"}

    def _fail_run(self, run_id, exc):
        self.repository.update_run(
            run_id,
            next_state=STATE_FAILED,
            last_error={"code": exc.code, "message": exc.message},
        )
        self.repository.append_event(
            run_id,
            {
                "stage": exc.stage or "unknown",
                "severity": "error",
                "event_type": "failure",
                "message": exc.message,
                "payload": {"code": exc.code, "details": exc.details},
            },
        )
