import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from tools.gmail.gmail_broker_protocol import PROTOCOL_VERSION
from tools.gmail.gmail_broker_state import (
    BrokerStateStore,
    LifetimeFileLock,
    SanitizedRotatingLogger,
)
from tools.gmail.gmail_edge_broker import (
    BrowserApplicationError,
    GmailEdgeBroker,
)


SENTINEL = "SOAK_SENTINEL_SECRET_7b91"


class NoopLockBackend:
    def acquire(self, _stream):
        return None

    def release(self, _stream):
        return None


class SoakBrowser:
    def __init__(self, delay=0.005):
        self.delay = delay
        self.start_count = 0
        self.current_concurrency = 0
        self.max_concurrency = 0

    async def start(self):
        self.start_count += 1

    async def close(self):
        return None

    async def execute(self, method, params):
        self.current_concurrency += 1
        self.max_concurrency = max(self.max_concurrency, self.current_concurrency)
        try:
            await asyncio.sleep(self.delay)
            mode = params.get("mode")
            if mode == "error":
                raise BrowserApplicationError(params.get("secret", ""))
            if mode == "timeout":
                await asyncio.Event().wait()
            return params.get("result", f"{method}:{params.get('value', '')}")
        finally:
            self.current_concurrency -= 1

    async def interactive_login(self):
        return None


class SingleEdgeBrokerSoakTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_clients_complete_twenty_requests_with_one_browser_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            store = BrokerStateStore(directory, acl_applier=None)
            owner_lock = LifetimeFileLock(
                store.paths.broker_lock_file,
                backend=NoopLockBackend(),
                acl_applier=None,
            )
            logger = SanitizedRotatingLogger(store.paths.log_file, acl_applier=None)
            browser = SoakBrowser()
            broker = GmailEdgeBroker(
                browser,
                state_store=store,
                owner_lock=owner_lock,
                logger=logger,
                build_id="soak-build",
                instance_id="soak-instance",
                token="soak-token",
                queue_wait_timeout=0.5,
                execution_timeout=0.2,
                idle_timeout=3600,
                idle_check_interval=0.01,
            )
            await broker.start()
            try:
                async def request(request_id, params=None, method="gmail_search"):
                    payload = {
                        "version": PROTOCOL_VERSION,
                        "id": request_id,
                        "token": "soak-token",
                        "method": method,
                        "params": params or {},
                    }
                    reader, writer = await asyncio.open_connection(*broker.address)
                    try:
                        writer.write(json.dumps(payload).encode("utf-8") + b"\n")
                        await writer.drain()
                        return json.loads((await reader.readline()).decode("utf-8"))
                    finally:
                        writer.close()
                        await writer.wait_closed()

                async def client(number):
                    return await asyncio.gather(
                        *(request(f"client-{number}-{index}", {"value": str(index)}) for index in range(5))
                    )

                grouped = await asyncio.gather(*(client(number) for number in range(4)))
                responses = [response for group in grouped for response in group]
                self.assertEqual(len(responses), 20)
                self.assertTrue(all(response["ok"] for response in responses))
                self.assertEqual(browser.start_count, 1)
                self.assertEqual(browser.max_concurrency, 1)

                error = await request(
                    "soak-error",
                    {"mode": "error", "secret": SENTINEL},
                )
                timeout = await request(
                    "soak-timeout",
                    {"mode": "timeout", "secret": SENTINEL},
                )
                self.assertEqual(error["error"]["code"], "APP_ERROR")
                self.assertEqual(timeout["error"]["code"], "REQUEST_TIMEOUT")

                log_text = "".join(
                    path.read_text(encoding="utf-8")
                    for path in directory.glob("broker.log*")
                )
                self.assertNotIn(SENTINEL, log_text)
                health = await request("soak-health", method="health")
                self.assertEqual(health["result"]["max_browser_concurrency"], 1)
                self.assertEqual(health["result"]["request_count"], 22)
            finally:
                await broker.stop()


if __name__ == "__main__":
    unittest.main()
