"""The progress screen, judged on what a person actually sees.

A run with a paid call in flight is seeded into a real database, the page is
opened in a real browser, and the claims on the screen are compared with what
the run can honestly support: an unknown finishing time stated as unknown, a
stop that admits what it cannot recall, and the same page in both languages.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_factory.accessibility import COLLECTOR_SCRIPT, audit
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - the suite skips without a browser
    sync_playwright = None


def stamp(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def seed(database: Path) -> None:
    storage = SQLiteStorage(database)
    try:
        with storage.db:
            storage.db.execute(
                "INSERT INTO projects(id,name,description) VALUES(1,'Lokvetia Core','')")
            storage.db.execute(
                "INSERT INTO work_items(id,project_id,identity,title,description,payload,status)"
                " VALUES(1,1,'task-1','Collector prototype','','{}','in_progress')")
            storage.db.execute(
                "INSERT INTO workflow_runs(id,identity,project_id,task_id,workflow_id,status)"
                " VALUES(1,'run-1',1,1,'delivery','running')")
            for index, (key, state) in enumerate((
                ("policy-precheck", "succeeded"),
                ("implementation", "running"),
                ("validation", "pending"),
            ), start=1):
                storage.db.execute(
                    "INSERT INTO workflow_stages(identity,run_id,stage_key,status,updated_at)"
                    " VALUES(?,1,?,?,?)", (f"stage-{index}", key, state, stamp(20)))
            storage.db.execute(
                "INSERT INTO provider_execution_gates(id,provider,agent_id,task_id)"
                " VALUES(1,'claude','coding-worker',1)")
            storage.db.execute(
                """INSERT INTO provider_execution_attempts
                   (identity,gate_id,provider,agent_id,task_id,request_hash,definition_hash,
                    status,started_at,heartbeat_at)
                   VALUES('attempt-1',1,'claude','coding-worker',1,'r','d','running',?,?)""",
                (stamp(120), stamp(5)))
            storage.db.execute(
                """INSERT INTO execution_traces
                   (id,identity,correlation_root,task_id,run_id,max_tokens,max_cost_usd,
                    max_stages,max_retries,max_tool_calls)
                   VALUES(1,'trace-1','root-1',1,1,100000,4.0,10,2,50)""")
            storage.db.execute(
                """INSERT INTO cost_ledger_entries
                   (identity,trace_id,idempotency_key,provider,source,tokens,duration_ms,
                    cost_usd,metadata_json)
                   VALUES('entry-1',1,'key-1','claude','provider_reported',1000,5000,1.25,'{}')""")
    finally:
        storage.db.close()


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class WorkPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import uvicorn

        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        database = cls.root / "state.db"
        seed(database)
        cls.app = create_app(cls.root, database)
        cls.server = uvicorn.Server(uvicorn.Config(
            cls.app, host="127.0.0.1", port=0, log_level="error", access_log=False,
        ))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 20
        while not cls.server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        if not cls.server.started:
            raise RuntimeError("The progress page server did not start")
        port = cls.server.servers[0].sockets[0].getsockname()[1]
        cls.url = f"http://127.0.0.1:{port}"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()
        cls.server.should_exit = True
        cls.thread.join(10)
        cls.directory.cleanup()

    def open(self, path: str, width: int = 1280, height: int = 900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        page.goto(f"{self.url}{path}", wait_until="networkidle")
        page.wait_for_selector("#stage:not(:empty)")
        page.wait_for_timeout(200)
        return page

    def test_the_screen_shows_the_stage_the_run_is_actually_on(self):
        page = self.open("/work")
        try:
            self.assertIn("implementation", page.inner_text("#stage"))
            self.assertIn("2", page.inner_text("#stage"))
            self.assertEqual(page.inner_text("#liveness"), "Працює")
        finally:
            page.close()

    def test_an_unknown_finishing_time_is_shown_as_unknown(self):
        page = self.open("/work?lang=en")
        try:
            estimate = page.inner_text("#estimate")
            self.assertIn("No estimate", estimate)
            self.assertNotRegex(estimate, r"\bAbout \d+ min")
        finally:
            page.close()

    def test_the_stop_panel_admits_what_it_cannot_recall(self):
        page = self.open("/work?lang=en")
        try:
            self.assertIn("cannot be recalled", page.inner_text("#spending"))
            self.assertIn("claude", page.inner_text("#finishes"))
            self.assertIn("Queueing", page.inner_text("#stops-now"))
        finally:
            page.close()

    def test_spending_shows_what_is_gone_and_what_is_left(self):
        page = self.open("/work?lang=en")
        try:
            money = page.inner_text("#money")
            self.assertIn("1.25 USD", money)
            self.assertIn("2.75 USD", money)
        finally:
            page.close()

    def test_pausing_is_disabled_with_the_reason_when_it_would_do_nothing(self):
        page = self.open("/work?lang=en")
        try:
            self.assertTrue(page.is_disabled("#pause"))
            self.assertIn("Temporal", page.inner_text("#pause-note"))
        finally:
            page.close()

    def test_a_stop_is_refused_until_its_consequence_is_acknowledged(self):
        page = self.open("/work?lang=en")
        try:
            page.click("#stop")
            page.wait_for_timeout(200)
            self.assertIn("understand", page.inner_text("#stop-result"))
            self.assertEqual(
                page.evaluate("document.querySelector('#liveness').textContent"),
                "Running",
                "nothing may change until the consequence is acknowledged",
            )
        finally:
            page.close()

    def test_the_populated_page_meets_the_accessibility_criteria(self):
        for path in ("/work", "/work?lang=en"):
            for width, height in ((320, 720), (1280, 900)):
                with self.subTest(page=path, width=width):
                    page = self.open(path, width, height)
                    try:
                        payload = page.evaluate(COLLECTOR_SCRIPT)
                        payload["url"] = path
                        result = audit(payload)
                        self.assertTrue(result.passed, result.report())
                    finally:
                        page.close()


if __name__ == "__main__":
    unittest.main()
