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
            self.assertEqual(payload["agent_role"], "Delivery Planner")
            self.assertEqual(payload["source_type"], "md")
            self.assertEqual(payload["analysis_status"], "needs_review")
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

    def test_manifest_without_schema_marker_is_still_decomposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            body = b'{"items": [{"stable_id": "E1", "kind": "epic", "title": "Game", "description": "Game", "acceptance_criteria": ["Works"]}, {"stable_id": "T1", "kind": "task", "title": "Move", "description": "Move", "parent_id": "E1", "acceptance_criteria": ["Moves"]}]}'
            with TestClient(create_app(workspace, workspace / "state.db")) as client:
                response = client.post("/api/backlog/analyze-upload", files={"specification": ("export.json", body)})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["counts"]["task"], 1)

    def test_plain_text_upload_is_accepted_as_generic_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db")) as client:
                response = client.post("/api/backlog/analyze-upload", files={"specification": ("brief.txt", b"# Game\n## Controls\n")})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["source_type"], "txt")

    def test_common_json_backlog_shape_is_expanded(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            body = b'{"backlog": [{"type": "feature", "name": "Doom", "tasks": [{"id": "T-1", "title": "Movement"}, {"id": "T-2", "title": "Scoring"}]}]}'
            with TestClient(create_app(workspace, workspace / "state.db")) as client:
                response = client.post("/api/backlog/analyze-upload", files={"specification": ("export.json", body)})
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["counts"]["epic"], 1)
            self.assertEqual(payload["counts"]["task"], 2)


if __name__ == "__main__":
    unittest.main()
