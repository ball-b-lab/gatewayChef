import csv
import io

from repositories.gateway_inventory_repository import GatewayInventoryRepository
from db.sim import SimAssignmentError, assign_sim
from utils.helpers import derive_wifi_ssid


class ProvisioningError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ProvisioningService:
    def __init__(self, connection):
        self.connection = connection

    def fetch_next_free_ip(self):
        with self.connection.cursor() as cursor:
            repo = GatewayInventoryRepository(cursor)
            row = repo.fetch_next_free_ip()

        if not row:
            raise ProvisioningError("Keine freien IPs (Status 'FREE') gefunden.", 404)

        return {"vpn_ip": row[0], "private_key": row[1]}

    def fetch_vpn_key(self, vpn_ip):
        if not vpn_ip:
            raise ProvisioningError("VPN IP fehlt.", 400)

        with self.connection.cursor() as cursor:
            repo = GatewayInventoryRepository(cursor)
            row = repo.fetch_vpn_key_by_ip(vpn_ip)

        if not row:
            raise ProvisioningError("VPN IP nicht gefunden.", 404)

        return {"private_key": row[0], "serial_number": row[1]}

    def update_customer_data(
        self,
        vpn_ip,
        gateway_name=None,
        serial_number=None,
        sim_iccid=None,
        sim_vendor_id=None,
        sim_card_id=None,
    ):
        if not vpn_ip:
            raise ProvisioningError("VPN IP fehlt.", 400)

        if not any([gateway_name, serial_number, sim_iccid, sim_vendor_id, sim_card_id]):
            raise ProvisioningError("Keine Kundendaten vorhanden.", 400)

        try:
            with self.connection.cursor() as cursor:
                repo = GatewayInventoryRepository(cursor)
                row = repo.fetch_gateway_for_update_by_vpn_ip(vpn_ip)
                if not row:
                    self.connection.rollback()
                    raise ProvisioningError("Gateway nicht gefunden.", 404)

                gateway_id = row[0]
                current_status = row[1]

                try:
                    assigned_sim_id = assign_sim(
                        cursor,
                        gateway_id,
                        sim_vendor_id,
                        sim_iccid,
                        sim_card_id,
                    )
                except SimAssignmentError as exc:
                    self.connection.rollback()
                    raise ProvisioningError(exc.message, exc.status_code) from exc

                repo.update_gateway_customer_fields(
                    gateway_id=gateway_id,
                    current_status=current_status,
                    gateway_name=gateway_name,
                    serial_number=serial_number,
                    assigned_sim_id=assigned_sim_id,
                )

                sim_id_str = None
                if assigned_sim_id:
                    sim_row = repo.fetch_sim_public_id_by_card_id(assigned_sim_id)
                    if sim_row:
                        sim_id_str = sim_row[0]

            self.connection.commit()
            return {"status": "success", "sim_card_id": assigned_sim_id, "sim_id": sim_id_str}
        except ProvisioningError:
            raise

    def import_gateway_inventory_csv(self, csv_text):
        if not csv_text or not str(csv_text).strip():
            raise ProvisioningError("CSV-Datei ist leer.", 400)

        try:
            reader = csv.DictReader(io.StringIO(csv_text))
        except csv.Error as exc:
            raise ProvisioningError(f"CSV kann nicht gelesen werden: {exc}", 400) from exc

        if not reader.fieldnames:
            raise ProvisioningError("CSV-Header fehlt.", 400)

        normalized_fieldnames = {name.strip() for name in reader.fieldnames if name}
        required = {"vpn_ip", "private_key"}
        missing = required - normalized_fieldnames
        if missing:
            raise ProvisioningError(
                f"CSV-Header unvollstaendig. Es fehlen: {', '.join(sorted(missing))}",
                400,
            )

        rows_to_import = []
        ignored = 0
        seen_gateway_ips = set()

        for index, row in enumerate(reader, start=2):
            normalized = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in (row or {}).items()}
            vpn_ip = normalized.get("vpn_ip") or ""
            private_key = normalized.get("private_key") or ""
            profile = (normalized.get("profile") or "gateway").strip().lower()
            inventory_enabled = (normalized.get("inventory_enabled") or "").strip().lower()
            status_overall = (normalized.get("inventory_status") or "FREE").strip() or "FREE"
            wifi_ssid = (normalized.get("wifi_ssid") or "").strip() or derive_wifi_ssid(vpn_ip)

            should_import = True
            if profile and profile != "gateway":
                should_import = False
            if inventory_enabled in {"false", "0", "no"}:
                should_import = False

            if not should_import:
                ignored += 1
                continue

            if not vpn_ip:
                raise ProvisioningError(f"CSV Zeile {index}: vpn_ip fehlt.", 400)
            if not private_key:
                raise ProvisioningError(f"CSV Zeile {index}: private_key fehlt.", 400)
            if vpn_ip in seen_gateway_ips:
                raise ProvisioningError(f"CSV enthaelt doppelte Gateway-VPN-IP: {vpn_ip}", 400)
            seen_gateway_ips.add(vpn_ip)

            rows_to_import.append(
                {
                    "vpn_ip": vpn_ip,
                    "private_key": private_key,
                    "wifi_ssid": wifi_ssid,
                    "status_overall": status_overall,
                }
            )

        inserted = 0
        skipped = 0
        with self.connection.cursor() as cursor:
            repo = GatewayInventoryRepository(cursor)
            for row in rows_to_import:
                result = repo.insert_gateway_inventory_seed_row(
                    vpn_ip=row["vpn_ip"],
                    private_key=row["private_key"],
                    wifi_ssid=row["wifi_ssid"],
                    status_overall=row["status_overall"],
                )
                if result:
                    inserted += 1
                else:
                    skipped += 1

        self.connection.commit()
        return {
            "inserted": inserted,
            "skipped_existing": skipped,
            "ignored_non_gateway": ignored,
            "processed_gateway_rows": len(rows_to_import),
        }
