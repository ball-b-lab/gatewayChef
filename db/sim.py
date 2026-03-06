class SimAssignmentError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def assign_sim(cur, gateway_id, sim_vendor_id, sim_iccid, sim_card_id):
    assigned_sim_id = None

    if sim_card_id or sim_vendor_id or sim_iccid:
        if sim_card_id:
            cur.execute(
                """
                SELECT id, iccid, vendor_id
                FROM sim_cards
                WHERE id = %s
                """,
                (sim_card_id,),
            )
            sim_row = cur.fetchone()
            if not sim_row:
                raise SimAssignmentError("SIM Karte nicht gefunden.", 404)
            if sim_vendor_id and str(sim_row[2]) != str(sim_vendor_id):
                raise SimAssignmentError("SIM Vendor passt nicht zur gewaehlten Karte.", 400)
            if sim_iccid and sim_row[1] and sim_row[1] != sim_iccid:
                raise SimAssignmentError("SIM ICCID passt nicht zur gewaehlten Karte.", 400)
            assigned_sim_id = sim_row[0]
        else:
            if not (sim_vendor_id and sim_iccid):
                raise SimAssignmentError("SIM Vendor und SIM ICCID erforderlich.", 400)
            cur.execute(
                """
                SELECT id
                FROM sim_cards
                WHERE vendor_id = %s AND iccid = %s
                """,
                (sim_vendor_id, sim_iccid),
            )
            sim_row = cur.fetchone()
            if sim_row:
                assigned_sim_id = sim_row[0]
            else:
                cur.execute(
                    """
                    INSERT INTO sim_cards (vendor_id, iccid)
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (sim_vendor_id, sim_iccid),
                )
                assigned_sim_id = cur.fetchone()[0]

        cur.execute(
            """
            UPDATE sim_cards
            SET assigned_gateway_id = %s, assigned_at = NOW()
            WHERE id = %s
            """,
            (gateway_id, assigned_sim_id),
        )

    return assigned_sim_id
