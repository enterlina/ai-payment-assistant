import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import requests

from agent.reliability import write_with_check
from data.gateway import mock_gateway
from support import journal


class IdempotentWriteIntegrationTest(unittest.TestCase):
    """Prove that a post-commit HTTP 500 is retried without a duplicate."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0),
                                         mock_gateway.PartnerGateway)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_same_key_retries_after_500_and_creates_one_refund(self):
        mock_gateway.reset_state()
        journal.API_LOG.clear()
        journal.start_trace("write_retry")
        base = f"http://127.0.0.1:{self.port}"
        headers = {"X-Api-Key": "demo-key"}
        try:
            # Position deterministic seed 42 immediately before the fourth
            # outcome. The fourth roll is "crashed": HTTP 500 after commit.
            for _ in range(3):
                mock_gateway.roll_failure()

            # The next seeded outcome is HTTP 500 after the refund is created.
            # The wrapper retries with the same key and receives duplicate=True.
            result = write_with_check(
                f"{base}/refund",
                {"order_id": "4126", "amount": 3990},
                "refund-4126",
                headers,
            )
            count = requests.get(
                f"{base}/refund_count", params={"order_id": "4126"}, timeout=5
            ).json()["count"]
        finally:
            journal.stop_trace()

        self.assertEqual(count, 1)
        self.assertTrue(result.get("duplicate"))
        posts = [entry for entry in journal.API_LOG
                 if entry["method"] == "POST" and entry["path"] == "/refund"]
        self.assertEqual([entry["status"] for entry in posts], [500, 200])
        self.assertEqual([entry["attempt"] for entry in posts], [1, 2])

        trace_path = Path(journal.trace_path("write_retry"))
        records = [json.loads(line) for line in trace_path.read_text(
            encoding="utf-8"
        ).splitlines()]
        post_records = [record for record in records
                        if record.get("method") == "POST"
                        and record.get("path") == "/refund"]
        hashes = {record["params"]["idempotency_key_hash"]
                  for record in post_records}
        self.assertEqual(len(hashes), 1)
        self.assertTrue(all(record["params"]["request_id"] == "***"
                            for record in post_records))


if __name__ == "__main__":
    unittest.main()
