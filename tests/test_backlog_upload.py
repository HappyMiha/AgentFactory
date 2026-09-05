import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agent_factory.web import create_app


class BacklogUploadTests(unittest.TestCase):
    def test_uploaded_markdown_is_decomposed_and_saved_as_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db"), base_url="http://localhost") as client:
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
            self.assertEqual(payload["counts"]["task"], 3)
            self.assertTrue((workspace / payload["source_path"]).is_file())
            self.assertEqual(payload["items"][2]["labels"][-1], "subtask")

    def test_ui_specification_field_name_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db"), base_url="http://localhost") as client:
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
            with TestClient(create_app(workspace, workspace / "state.db"), base_url="http://localhost") as client:
                response = client.post("/api/backlog/analyze-upload", files={"specification": ("export.json", body)})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["counts"]["task"], 1)

    def test_plain_text_upload_is_accepted_as_generic_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db"), base_url="http://localhost") as client:
                response = client.post("/api/backlog/analyze-upload", files={"specification": ("brief.txt", b"# Game\n## Controls\n")})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["source_type"], "txt")

    def test_common_json_backlog_shape_is_expanded(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            body = b'{"backlog": [{"type": "feature", "name": "Doom", "tasks": [{"id": "T-1", "title": "Movement"}, {"id": "T-2", "title": "Scoring"}]}]}'
            with TestClient(create_app(workspace, workspace / "state.db"), base_url="http://localhost") as client:
                response = client.post("/api/backlog/analyze-upload", files={"specification": ("export.json", body)})
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["counts"]["epic"], 1)
            self.assertEqual(payload["counts"]["task"], 2)

    def test_plain_briefs_preserve_semantics_source_and_executable_leaves(self):
        for brief in ("A cat collects coins and has three lives.",
                      "Кіт збирає монети та має три життя."):
            with self.subTest(brief=brief), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                raw = brief.encode("utf-8")
                with TestClient(create_app(workspace, workspace / "state.db"), base_url="http://localhost") as client:
                    result = client.post("/api/backlog/analyze-upload", files={"upload": ("brief.txt", raw)})
                self.assertEqual(result.status_code, 200)
                payload = result.json()
                self.assertEqual(payload["analysis_method"], "deterministic_import")
                self.assertEqual(payload["original_text"], brief)
                self.assertEqual((workspace / payload["original_path"]).read_bytes(), raw)
                self.assertEqual(payload["original_sha256"], hashlib.sha256(raw).hexdigest())
                leaves = [item for item in payload["items"] if item["kind"] == "task"]
                self.assertTrue(leaves)
                self.assertIn(brief, leaves[0]["description"])
                self.assertIn(brief, " ".join(leaves[0]["acceptance_criteria"]))
                self.assertTrue(any(payload["original_sha256"] in ref for ref in leaves[0]["source_references"]))

    def test_markdown_section_body_and_intro_are_retained(self):
        from agent_factory.backlog_analyzer import analyze_specification
        text = "An original game idea.\n# Game\nA cat collects coins.\n## Lives\nThe cat has three lives."
        proposal = analyze_specification(text.encode(), "game.md")
        self.assertEqual(proposal.source_metadata["original_text"], text)
        descriptions = " ".join(item.description for item in proposal.items if item.executable)
        for requirement in ("An original game idea.", "A cat collects coins.", "The cat has three lives."):
            self.assertIn(requirement, descriptions)

    def test_pdf_text_and_original_bytes_are_preserved(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 200 Td (A cat collects coins and has three lives.) Tj ET")
        page[NameObject("/Contents")] = stream
        output = io.BytesIO(); writer.write(output)
        raw = output.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db"), base_url="http://localhost") as client:
                result = client.post("/api/backlog/analyze-upload", files={"upload": ("game.pdf", raw)})
            self.assertEqual(result.status_code, 200)
            payload = result.json()
            self.assertEqual((workspace / payload["original_path"]).read_bytes(), raw)
            tasks = [item for item in payload["items"] if item["kind"] == "task"]
            self.assertIn("three lives", tasks[0]["description"])
            self.assertIn("collects coins", " ".join(tasks[0]["acceptance_criteria"]))

    def test_failed_extraction_still_preserves_original(self):
        raw = b"%PDF-this-is-not-a-valid-document"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db"), base_url="http://localhost") as client:
                result = client.post("/api/backlog/analyze-upload", files={"upload": ("bad.pdf", raw)})
            self.assertEqual(result.status_code, 400)
            originals = list((workspace / ".agent-factory/uploads").glob("*.original"))
            self.assertEqual(len(originals), 1)
            self.assertEqual(originals[0].read_bytes(), raw)
            self.assertFalse(list((workspace / ".agent-factory/uploads").glob("*.json")))

    def test_edited_preview_validates_and_imports_without_overwriting_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with TestClient(create_app(workspace, workspace / "state.db"), base_url="http://localhost") as client:
                payload = client.post("/api/backlog/analyze-upload", files={"upload": ("brief.txt", b"A cat collects coins and has three lives.")}).json()
                manifest = workspace / payload["source_path"]
                before = manifest.read_bytes()
                edits = [{key: item[key] for key in ("stable_id", "title", "description", "acceptance_criteria")} for item in payload["items"]]
                edits[-1].update(title="Cat gameplay", description="Cat collects coins and has five lives.", acceptance_criteria=["Collect a coin", "Start with five lives"])
                command = {"project_name": "Cat game", "backlog_path": payload["source_path"], "reviewed_items": edits, "confirmed": True}
                self.assertEqual(client.post("/api/backlog/import", json=command).status_code, 400)
                headers = {"X-Agent-Factory-Confirm": "true"}
                invalid = {**command, "reviewed_items": [edits[0], edits[0]]}
                self.assertEqual(client.post("/api/backlog/import", json=invalid, headers=headers).status_code, 400)
                invalid = {**command, "reviewed_items": [{**item, "acceptance_criteria": []} for item in edits]}
                self.assertEqual(client.post("/api/backlog/import", json=invalid, headers=headers).status_code, 400)
                self.assertFalse(list(manifest.parent.glob("*.reviewed.json")))
                result = client.post("/api/backlog/import", json=command, headers=headers)
                self.assertEqual(result.status_code, 200, result.text)
                saved = json.loads((workspace / result.json()["source_path"]).read_text(encoding="utf-8"))
                self.assertEqual(saved["items"][-1]["description"], edits[-1]["description"])
                self.assertEqual(saved["source"]["review_status"], "user_confirmed")
                self.assertEqual(saved["source"]["original_text"], payload["original_text"])
                self.assertEqual(saved["items"][-1]["source_references"], payload["items"][-1]["source_references"])
                self.assertEqual(manifest.read_bytes(), before)
                rows = client.get("/api/work-items").json()["items"]
                self.assertTrue(any(row["description"] == edits[-1]["description"] for row in rows))


if __name__ == "__main__":
    unittest.main()
