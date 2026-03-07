class GatewayInventoryRepository:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetch_next_free_ip(self):
        self.cursor.execute(
            """
            SELECT vpn_ip, private_key
            FROM gateway_inventory
            WHERE status_overall = 'FREE'
            ORDER BY vpn_ip
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
        return self.cursor.fetchone()

    def fetch_vpn_key_by_ip(self, vpn_ip):
        self.cursor.execute(
            """
            SELECT private_key, serial_number
            FROM gateway_inventory
            WHERE vpn_ip = %s
            """,
            (vpn_ip,),
        )
        return self.cursor.fetchone()

    def fetch_gateway_for_update_by_vpn_ip(self, vpn_ip):
        self.cursor.execute(
            """
            SELECT id, status_overall
            FROM gateway_inventory
            WHERE vpn_ip = %s
            FOR UPDATE
            """,
            (vpn_ip,),
        )
        return self.cursor.fetchone()

    def update_gateway_customer_fields(
        self,
        gateway_id,
        current_status,
        gateway_name=None,
        serial_number=None,
        assigned_sim_id=None,
    ):
        update_fields = []
        params = []

        if current_status == "FREE":
            update_fields.append("status_overall = %s")
            params.append("IN_PROGRESS")
        if gateway_name:
            update_fields.append("gateway_name = %s")
            params.append(gateway_name)
        if serial_number:
            update_fields.append("serial_number = %s")
            params.append(serial_number)
        if assigned_sim_id:
            update_fields.append("sim_card_id = %s")
            params.append(assigned_sim_id)

        if not update_fields:
            return

        params.append(gateway_id)
        self.cursor.execute(
            f"""
            UPDATE gateway_inventory
            SET {', '.join(update_fields)}
            WHERE id = %s
            """,
            params,
        )

    def fetch_sim_public_id_by_card_id(self, sim_card_id):
        self.cursor.execute(
            """
            SELECT sim_id
            FROM sim_cards
            WHERE id = %s
            """,
            (sim_card_id,),
        )
        return self.cursor.fetchone()
