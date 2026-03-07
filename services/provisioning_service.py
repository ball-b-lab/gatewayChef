from repositories.gateway_inventory_repository import GatewayInventoryRepository
from db.sim import SimAssignmentError, assign_sim


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
