import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.application import AgentFactoryService
from agent_factory.autonomous_mission import (
    AutonomousMissionConfiguration,
    AutonomousMissionService,
    MissionPhase,
    MissionVersionConflictError,
)
from agent_factory.backlog import BacklogProposal, ProposedItem
from agent_factory.backlog_revisions import (
    BacklogRevisionOrigin,
    BacklogRevisionService,
)
from agent_factory.mission_intake import (
    AutonomousMissionIntakeResult,
    AutonomousMissionIntakeService,
    SpecificationCommandConflictError,
    UnsafeSpecificationUploadError,
)
from agent_factory.storage import SQLiteStorage


def rich_proposal(source_digest: str, *, title: str = "Build capability") -> BacklogProposal:
    return BacklogProposal(
        source_path="autonomous://specification",
        source_sha256=source_digest,
        source_name="Mission specification",
        schema_version=2,
        items=(
            ProposedItem(
                stable_id="T1",
                kind="task",
                title=title,
                description="Implement and validate the approved capability.",
                acceptance_criteria=("The capability passes validation",),
                priority="P0",
                validation_method=("Run the test suite",),
                required_components=("app.py",),
                required_infrastructure=("Python",),
                expected_artifacts=("Implementation",),
                definition_of_done=("Tests pass",),
                assigned_role="Developer",
            ),
        ),
    )


def text_pdf(content: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    output = io.BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    page[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    escaped = content.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


class AutonomousMissionIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.storage = SQLiteStorage(self.workspace / "state.db")
        self.intake = AutonomousMissionIntakeService(self.storage)
        self.missions = AutonomousMissionService(self.storage)
        self.revisions = BacklogRevisionService(self.storage)
        self.configuration = AutonomousMissionConfiguration(
            repository_path=str(self.workspace),
            default_model="local-model",
            role_models={"Developer": "local-model"},
            local_provider_ids=("local-provider",),
        )

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def create(self, command_id: str = "create-source-mission"):
        content = "  # Exact mission specification\n\nKeep surrounding whitespace.  \n"
        return self.intake.create_from_text(
            name="Source mission",
            mission_owner="Founder",
            specification=content,
            actor="Founder",
            command_id=command_id,
            mission_key="AFM-SOURCE",
            configuration=self.configuration,
            source_name="mission.md",
            provenance="Founder paste",
        )

    def test_text_creation_round_trips_exact_source_without_work_items(self):
        result = self.create()
        self.assertEqual(
            result.source.content,
            "  # Exact mission specification\n\nKeep surrounding whitespace.  \n",
        )
        self.assertEqual(result.mission.phase, MissionPhase.DRAFT)
        self.assertEqual(result.mission.version, 2)
        self.assertEqual(result.source.version, 1)
        self.assertTrue(result.source.current)
        self.assertEqual(result.source.actor, "Founder")
        self.assertEqual(result.source.provenance, "Founder paste")
        self.assertEqual(len(result.source.source_digest), 64)
        self.assertIsNotNone(result.source.intake_source_id)
        self.assertEqual(result.mission.intake_id, 1)
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM work_items WHERE project_id=?",
                (result.mission.project_id,),
            ).fetchone()[0],
            0,
        )
        standard_source = self.storage.db.execute(
            "SELECT * FROM mission_sources WHERE id=?",
            (result.source.intake_source_id,),
        ).fetchone()
        self.assertEqual(standard_source["authority"], "authoritative")
        self.assertEqual(standard_source["content_digest"], result.source.content_digest)

        replay = self.create()
        self.assertEqual(replay.mission.id, result.mission.id)
        self.assertEqual(replay.source.id, result.source.id)
        self.assertEqual(
            self.storage.db.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1
        )
        with self.assertRaises(SpecificationCommandConflictError):
            self.intake.create_from_text(
                name="Different mission",
                mission_owner="Founder",
                specification="Different source",
                actor="Founder",
                command_id="create-source-mission",
                mission_key="AFM-SOURCE",
                configuration=self.configuration,
            )

    def test_json_pdf_and_unsafe_upload_boundaries(self):
        json_result = self.intake.create_from_upload(
            name="JSON mission",
            mission_owner="Founder",
            raw=b'{"goal":"ship","constraints":["local"]}',
            source_name="brief.json",
            media_type="application/json; charset=utf-8",
            actor="Founder",
            command_id="create-json-mission",
            mission_key="AFM-JSON",
            configuration=self.configuration,
        )
        self.assertEqual(json_result.source.media_type, "application/json")
        self.assertEqual(json_result.source.metadata["json_root_type"], "object")

        pdf_result = self.intake.create_from_upload(
            name="PDF mission",
            mission_owner="Founder",
            raw=text_pdf("Build the local mission"),
            source_name="brief.pdf",
            media_type="application/pdf",
            actor="Founder",
            command_id="create-pdf-mission",
            mission_key="AFM-PDF",
            configuration=self.configuration,
        )
        self.assertIn("Build the local mission", pdf_result.source.content)
        self.assertEqual(pdf_result.source.metadata["page_count"], 1)

        before = self.storage.db.execute(
            "SELECT COUNT(*) FROM autonomous_missions"
        ).fetchone()[0]
        unsafe = (
            (b'{"key":1,"key":2}', "duplicate.json", "application/json"),
            (b"\xff\xfe\x00", "binary.txt", "text/plain"),
            (b"MZ executable", "payload.exe", "application/octet-stream"),
            (b"%PDF-1.7\n/JavaScript exploit", "active.pdf", "application/pdf"),
            (b"not a pdf", "fake.pdf", "application/pdf"),
        )
        for index, (raw, name, media_type) in enumerate(unsafe, 1):
            with self.subTest(name=name), self.assertRaises(
                UnsafeSpecificationUploadError
            ):
                self.intake.create_from_upload(
                    name="Unsafe mission",
                    mission_owner="Founder",
                    raw=raw,
                    source_name=name,
                    media_type=media_type,
                    actor="Founder",
                    command_id=f"unsafe-{index}",
                    mission_key=f"AFM-UNSAFE-{index}",
                    configuration=self.configuration,
                )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM autonomous_missions"
            ).fetchone()[0],
            before,
        )

    def test_application_boundary_exposes_typed_upload_create_update_and_query(self):
        service = AgentFactoryService(
            self.storage,
            workspace=self.workspace,
        )
        created = service.create_autonomous_mission_from_upload(
            name="Application upload mission",
            mission_owner="Founder",
            raw=b'{"goal":"preserve the source"}',
            source_name="mission.json",
            media_type="application/json",
            actor="Founder",
            command_id="application-upload-create",
            mission_key="AFM-APPLICATION-UPLOAD",
            configuration=self.configuration,
        )
        self.assertIsInstance(created, AutonomousMissionIntakeResult)
        self.assertEqual(
            service.autonomous_mission_specification(created.mission.id),
            created.source,
        )

        updated = service.update_autonomous_mission_specification_from_upload(
            created.mission.id,
            raw=b"Updated authoritative mission",
            source_name="mission.txt",
            media_type="text/plain",
            actor="Founder",
            command_id="application-upload-update",
            reason="Exercise the public typed upload boundary",
            expected_mission_version=created.mission.version,
            expected_source_version=created.source.version,
        )
        self.assertIsInstance(updated, type(created.source))
        self.assertEqual(updated.version, 2)
        self.assertEqual(
            service.autonomous_mission_specification(created.mission.id).id,
            updated.id,
        )

    def test_source_change_invalidates_proposal_and_resets_planning_phase(self):
        result = self.create()
        mission = result.mission
        mission = self.missions.transition_phase(
            mission.id,
            MissionPhase.SPECIFICATION_ANALYSIS,
            actor="Founder",
            command_id="source-analysis",
            expected_version=mission.version,
            reason="Analyze version one",
        )
        mission = self.missions.transition_phase(
            mission.id,
            MissionPhase.BACKLOG_GENERATION,
            actor="Founder",
            command_id="source-generation",
            expected_version=mission.version,
            reason="Generate version one proposal",
        )
        revision = self.revisions.create_revision(
            mission_id=mission.id,
            proposal=rich_proposal(result.source.raw_digest),
            origin=BacklogRevisionOrigin.HUMAN,
            created_by="Founder",
            command_id="source-revision-v1",
            rationale="Proposal for specification version one",
        )
        updated = self.intake.update_from_text(
            mission.id,
            specification="# Version two\n\nMaterially changed requirements.",
            actor="Founder",
            command_id="update-source-v2",
            reason="Replace the pre-approval specification",
            expected_mission_version=mission.version,
            expected_source_version=1,
            source_name="mission.md",
        )
        current_mission = self.missions.get(mission.id)
        self.assertEqual(updated.version, 2)
        self.assertEqual(current_mission.phase, MissionPhase.SPECIFICATION_ANALYSIS)
        self.assertEqual(current_mission.version, mission.version + 1)
        self.assertEqual(self.intake.current_source(mission.id).id, updated.id)
        first = self.intake.get_source(result.source.id)
        self.assertFalse(first.current)
        self.assertEqual(first.superseded_by_source_id, updated.id)
        invalidations = self.intake.invalidated_revisions(mission.id)
        self.assertEqual(len(invalidations), 1)
        self.assertEqual(invalidations[0]["revision_id"], revision.id)
        with self.assertRaisesRegex(PermissionError, "invalidated"):
            self.revisions.activate_revision(
                revision.id,
                actor="Founder",
                command_id="activate-stale-source-revision",
                expected_mission_version=current_mission.version,
                reason="Attempt to activate a stale proposal",
            )

        identical = self.intake.update_from_text(
            mission.id,
            specification="# Version two\n\nMaterially changed requirements.",
            actor="Founder",
            command_id="repeat-source-v2",
            reason="Confirm the exact source",
            expected_mission_version=current_mission.version,
            expected_source_version=2,
            source_name="mission.md",
        )
        self.assertEqual(identical.id, updated.id)
        self.assertEqual(len(self.intake.sources(mission.id)), 2)
        self.assertEqual(self.missions.get(mission.id).version, current_mission.version)

        with self.assertRaisesRegex(ValueError, "source version conflict"):
            self.intake.update_from_text(
                mission.id,
                specification="# Version three",
                actor="Founder",
                command_id="stale-source-version",
                reason="Stale update",
                expected_mission_version=current_mission.version,
                expected_source_version=1,
            )
        with self.assertRaises(MissionVersionConflictError):
            self.intake.update_from_text(
                mission.id,
                specification="# Version three",
                actor="Founder",
                command_id="stale-mission-version",
                reason="Stale aggregate update",
                expected_mission_version=current_mission.version - 1,
                expected_source_version=2,
            )

    def test_source_records_and_supersessions_are_immutable(self):
        result = self.create()
        updated = self.intake.update_from_text(
            result.mission.id,
            specification="Version two",
            actor="Founder",
            command_id="immutable-source-v2",
            reason="Create immutable version two",
            expected_mission_version=result.mission.version,
            expected_source_version=1,
        )
        supersession = self.storage.db.execute(
            """SELECT id FROM autonomous_specification_supersessions
                WHERE replacement_source_id=?""",
            (updated.id,),
        ).fetchone()
        for table, row_id in (
            ("autonomous_mission_specification_sources", result.source.id),
            ("autonomous_specification_supersessions", supersession["id"]),
        ):
            with self.subTest(table=table, action="update"):
                with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                    self.storage.db.execute(
                        f"UPDATE {table} SET identity=identity || '-x' WHERE id=?",
                        (row_id,),
                    )
            with self.subTest(table=table, action="delete"):
                with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                    self.storage.db.execute(
                        f"DELETE FROM {table} WHERE id=?", (row_id,)
                    )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "durable"):
            self.storage.db.execute(
                "DELETE FROM autonomous_mission_specification_heads WHERE mission_id=?",
                (result.mission.id,),
            )


if __name__ == "__main__":
    unittest.main()
