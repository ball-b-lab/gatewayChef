import unittest
from unittest.mock import patch

from db.sim import SimAssignmentError
from services.provisioning_service import ProvisioningError, ProvisioningService


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, rows):
        self._rows = rows
        self.commit_calls = 0
        self.rollback_calls = 0

    def cursor(self):
        return FakeCursor(self._rows)

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


class ProvisioningServiceTest(unittest.TestCase):
    def test_fetch_next_free_ip_success(self):
        service = ProvisioningService(FakeConnection(rows=[("10.10.10.10", "priv")]))

        result = service.fetch_next_free_ip()

        self.assertEqual(result["vpn_ip"], "10.10.10.10")
        self.assertEqual(result["private_key"], "priv")

    def test_fetch_next_free_ip_not_found(self):
        service = ProvisioningService(FakeConnection(rows=[]))

        with self.assertRaises(ProvisioningError) as ctx:
            service.fetch_next_free_ip()

        self.assertEqual(ctx.exception.status_code, 404)

    def test_fetch_vpn_key_requires_ip(self):
        service = ProvisioningService(FakeConnection(rows=[]))

        with self.assertRaises(ProvisioningError) as ctx:
            service.fetch_vpn_key("")

        self.assertEqual(ctx.exception.status_code, 400)

    def test_fetch_vpn_key_success(self):
        service = ProvisioningService(FakeConnection(rows=[("secret", "SER123")]))

        result = service.fetch_vpn_key("10.0.0.2")

        self.assertEqual(result["private_key"], "secret")
        self.assertEqual(result["serial_number"], "SER123")

    def test_fetch_vpn_key_not_found(self):
        service = ProvisioningService(FakeConnection(rows=[]))

        with self.assertRaises(ProvisioningError) as ctx:
            service.fetch_vpn_key("10.0.0.2")

        self.assertEqual(ctx.exception.status_code, 404)

    @patch("services.provisioning_service.assign_sim", return_value=55)
    def test_update_customer_data_success(self, assign_sim_mock):
        conn = FakeConnection(rows=[(99, "FREE"), ("SIM-ABC",)])
        service = ProvisioningService(conn)

        result = service.update_customer_data(
            vpn_ip="10.0.0.5",
            gateway_name="GW-1",
            serial_number="SER-1",
            sim_iccid="123",
            sim_vendor_id=3,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["sim_card_id"], 55)
        self.assertEqual(result["sim_id"], "SIM-ABC")
        self.assertEqual(conn.commit_calls, 1)
        self.assertEqual(conn.rollback_calls, 0)
        assign_sim_mock.assert_called_once()

    def test_update_customer_data_requires_vpn_ip(self):
        conn = FakeConnection(rows=[])
        service = ProvisioningService(conn)

        with self.assertRaises(ProvisioningError) as ctx:
            service.update_customer_data(vpn_ip="")

        self.assertEqual(ctx.exception.status_code, 400)

    def test_update_customer_data_requires_any_change(self):
        conn = FakeConnection(rows=[])
        service = ProvisioningService(conn)

        with self.assertRaises(ProvisioningError) as ctx:
            service.update_customer_data(vpn_ip="10.0.0.5")

        self.assertEqual(ctx.exception.status_code, 400)

    def test_update_customer_data_gateway_not_found(self):
        conn = FakeConnection(rows=[None])
        service = ProvisioningService(conn)

        with self.assertRaises(ProvisioningError) as ctx:
            service.update_customer_data(vpn_ip="10.0.0.5", gateway_name="GW")

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(conn.commit_calls, 0)
        self.assertEqual(conn.rollback_calls, 1)

    @patch("services.provisioning_service.assign_sim")
    def test_update_customer_data_sim_error_rolls_back(self, assign_sim_mock):
        assign_sim_mock.side_effect = SimAssignmentError("SIM kaputt", 422)
        conn = FakeConnection(rows=[(99, "FREE")])
        service = ProvisioningService(conn)

        with self.assertRaises(ProvisioningError) as ctx:
            service.update_customer_data(
                vpn_ip="10.0.0.5",
                gateway_name="GW-1",
                sim_iccid="123",
                sim_vendor_id=3,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(conn.commit_calls, 0)
        self.assertEqual(conn.rollback_calls, 1)


if __name__ == "__main__":
    unittest.main()
