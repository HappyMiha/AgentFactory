import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agent_factory.web import create_app


class BacklogUploadTests(unittest.TestCase):
    def test_uploaded_markdown_is_decomposed_and_saved_as_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db")) as client:
                response = client.post(
                    "/api/backlog/analyze-upload",
                    files={"upload": ("game.md", b"# Windows game\n## Core loop\n### Movement\n### Scoring\n## Release\n")},
                )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["recommended_agent"], "backlog-steward")
            self.assertEqual(payload["counts"]["epic"], 1)
            self.assertEqual(payload["counts"]["story"], 2)
            self.assertEqual(payload["counts"]["task"], 2)
            self.assertTrue((workspace / payload["source_path"]).is_file())
            self.assertEqual(payload["items"][2]["labels"][-1], "subtask")

    def test_ui_specification_field_name_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db")) as client:
                response = client.post(
                    "/api/backlog/analyze-upload",
                    files={"specification": ("brief.json", b'{"schema_version": 1, "items": [{"stable_id": "epic:one", "kind": "epic", "title": "One", "description": "One", "acceptance_criteria": ["Works"]}]}')},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["counts"]["epic"], 1)


if __name__ == "__main__":
    unittest.main()
