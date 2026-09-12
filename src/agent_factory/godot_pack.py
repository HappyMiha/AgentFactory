"""Project-neutral Godot 2D game pack with reviewable template materialisation.

The factory core stays engine-neutral: this module owns the engine-specific
template payload, the supported engine range, and the rule that an upgrade
never silently overwrites a file the creator authored. Materialisation is a
two-step contract - ``plan`` produces a reviewable preview, ``apply`` writes
only what that preview declared and only what a human approved.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


GODOT_PACK_KEY = "godot-2d"
GODOT_PACK_VERSION = "1.1.0"
INSTALLATION_CATALOGUE = Path(__file__).resolve().parent / "defaults" / "installation-catalog.json"
# Extra 4.x series this pack still accepts for an already-installed editor. The
# baseline always comes from the installation catalogue, so a project is created
# for the editor the factory actually installs.
ADDITIONAL_ENGINE_VERSIONS = ("4.3", "4.4")
BASELINE_RENDERER = "gl_compatibility"
PACK_LANGUAGE = "gdscript"
PACK_STATE_PATH = ".lokvetia/godot-pack.json"
PLAN_ACTIONS = ("create", "update", "keep", "conflict")
MAX_TEMPLATE_FILES = 64


class PackConflict(PermissionError):
    """Raised when an upgrade would overwrite unapproved authored files."""


def _catalogue_engine_series(path: Path = INSTALLATION_CATALOGUE) -> str:
    """The editor series the installation catalogue actually installs.

    Hard-coding a supported range in this module let it drift from the catalogue
    that installs the editor, which made the pack refuse the only editor the
    factory ships. The catalogue is the single source of truth; the constant
    below is derived from it.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = str(payload["packages"]["godot-editor"]["version"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return ADDITIONAL_ENGINE_VERSIONS[-1]
    parts = version.split(".")
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else version


BASELINE_ENGINE_VERSION = _catalogue_engine_series()
SUPPORTED_ENGINE_VERSIONS = tuple(sorted(
    {BASELINE_ENGINE_VERSION, *ADDITIONAL_ENGINE_VERSIONS},
    key=lambda value: tuple(int(part) for part in value.split(".")),
))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _relative(path: str) -> str:
    cleaned = str(path).replace("\\", "/").strip()
    if (
        not cleaned
        or cleaned.startswith("/")
        or cleaned.endswith("/")
        or ":" in cleaned
        or "\x00" in cleaned
        or any(part in {"", ".", ".."} for part in cleaned.split("/"))
    ):
        raise ValueError(f"Template path must be a relative project path: {path!r}")
    return cleaned


@dataclass(frozen=True)
class TemplateFile:
    """One pack-owned file. ``creator_owned`` files are written once, never upgraded."""

    path: str
    content: str
    creator_owned: bool = False

    @classmethod
    def create(cls, path: str, content: str, *, creator_owned: bool = False) -> "TemplateFile":
        if not isinstance(content, str):
            raise ValueError("Template content must be text")
        return cls(_relative(path), content, bool(creator_owned))

    @property
    def digest(self) -> str:
        return _digest(self.content)


@dataclass(frozen=True)
class GameTemplate:
    template_id: str
    title: str
    summary: str
    version: str
    engine_version: str
    renderer: str
    main_scene: str
    files: tuple[TemplateFile, ...]

    @classmethod
    def create(
        cls,
        template_id: str,
        *,
        title: str,
        summary: str,
        version: str,
        main_scene: str,
        files: Sequence[TemplateFile],
        engine_version: str = BASELINE_ENGINE_VERSION,
        renderer: str = BASELINE_RENDERER,
    ) -> "GameTemplate":
        if not template_id.strip() or not title.strip() or not summary.strip():
            raise ValueError("Template requires an identifier, title, and summary")
        if engine_version not in SUPPORTED_ENGINE_VERSIONS:
            raise ValueError(f"Unsupported engine version: {engine_version}")
        if not files or len(files) > MAX_TEMPLATE_FILES:
            raise ValueError("Template requires between one and 64 files")
        paths = [entry.path for entry in files]
        if len(paths) != len(set(paths)):
            raise ValueError("Template paths must be unique")
        if "project.godot" not in paths:
            raise ValueError("A Godot template must ship project.godot")
        scene = _relative(main_scene)
        if scene not in paths:
            raise ValueError("The declared main scene is not part of the template")
        return cls(
            template_id.strip(), title.strip(), summary.strip(), version,
            engine_version, renderer, scene, tuple(files),
        )

    @property
    def digest(self) -> str:
        return _digest(_canonical({
            "template_id": self.template_id,
            "version": self.version,
            "engine_version": self.engine_version,
            "renderer": self.renderer,
            "files": {entry.path: entry.digest for entry in self.files},
        }))

    def file(self, path: str) -> TemplateFile:
        wanted = _relative(path)
        for entry in self.files:
            if entry.path == wanted:
                return entry
        raise KeyError(f"Unknown template file: {path}")

    @property
    def manifest(self) -> dict[str, object]:
        return {
            "pack_key": GODOT_PACK_KEY,
            "pack_version": GODOT_PACK_VERSION,
            "template_id": self.template_id,
            "template_version": self.version,
            "template_digest": self.digest,
            "engine_version": self.engine_version,
            "renderer": self.renderer,
            "language": PACK_LANGUAGE,
            "main_scene": self.main_scene,
            "external_content": False,
            "files": [
                {
                    "path": entry.path,
                    "digest": entry.digest,
                    "creator_owned": entry.creator_owned,
                }
                for entry in sorted(self.files, key=lambda value: value.path)
            ],
        }


@dataclass(frozen=True)
class PlannedChange:
    path: str
    action: str
    pack_digest: str
    disk_digest: str | None
    reason: str


@dataclass(frozen=True)
class MaterialisationPlan:
    template_id: str
    template_version: str
    template_digest: str
    target: str
    installed_version: str | None
    changes: tuple[PlannedChange, ...]

    def _paths(self, action: str) -> tuple[str, ...]:
        return tuple(change.path for change in self.changes if change.action == action)

    @property
    def creations(self) -> tuple[str, ...]:
        return self._paths("create")

    @property
    def updates(self) -> tuple[str, ...]:
        return self._paths("update")

    @property
    def kept(self) -> tuple[str, ...]:
        return self._paths("keep")

    @property
    def conflicts(self) -> tuple[str, ...]:
        return self._paths("conflict")

    @property
    def safe(self) -> bool:
        return not self.conflicts

    @property
    def digest(self) -> str:
        return _digest(_canonical({
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_digest": self.template_digest,
            "target": self.target,
            "installed_version": self.installed_version,
            "changes": [
                {
                    "path": change.path, "action": change.action,
                    "pack_digest": change.pack_digest, "disk_digest": change.disk_digest,
                }
                for change in self.changes
            ],
        }))

    def preview(self) -> dict[str, object]:
        """A reviewable summary: what would change, and what would be refused."""
        return {
            "template_id": self.template_id,
            "template_version": self.template_version,
            "installed_version": self.installed_version,
            "plan_digest": self.digest,
            "create": list(self.creations),
            "update": list(self.updates),
            "keep": list(self.kept),
            "conflict": list(self.conflicts),
            "requires_human_approval": list(self.conflicts),
            "safe": self.safe,
        }


@dataclass(frozen=True)
class MaterialisationReceipt:
    plan_digest: str
    template_id: str
    template_version: str
    target: str
    written: tuple[str, ...]
    kept: tuple[str, ...]
    overwritten: tuple[str, ...]
    project_digest: str
    actor: str
    recorded_at: str


class GodotPack:
    """Materialises engine templates without overwriting authored work."""

    def __init__(self, templates: Iterable[GameTemplate] | None = None):
        catalogue = tuple(templates) if templates is not None else default_templates()
        if not catalogue:
            raise ValueError("A game pack requires at least one template")
        identifiers = [template.template_id for template in catalogue]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Template identifiers must be unique")
        self._templates = {template.template_id: template for template in catalogue}

    @property
    def pack_key(self) -> str:
        return GODOT_PACK_KEY

    @property
    def version(self) -> str:
        return GODOT_PACK_VERSION

    def templates(self) -> tuple[GameTemplate, ...]:
        return tuple(self._templates[key] for key in sorted(self._templates))

    def template(self, template_id: str) -> GameTemplate:
        try:
            return self._templates[str(template_id).strip()]
        except KeyError as exc:
            raise KeyError(f"Unknown Godot template: {template_id}") from exc

    def supports(self, engine_version: str) -> bool:
        return _engine_series(engine_version) in SUPPORTED_ENGINE_VERSIONS

    @staticmethod
    def _state(target: Path) -> dict[str, object]:
        state_file = target / PACK_STATE_PATH
        if not state_file.is_file():
            return {}
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def plan(self, target: Path, template_id: str) -> MaterialisationPlan:
        template = self.template(template_id)
        root = Path(target)
        state = self._state(root)
        installed = state.get("files") if isinstance(state.get("files"), dict) else {}
        installed_template = state.get("template_id")
        installed_version = state.get("template_version")
        if installed_template and installed_template != template.template_id:
            installed, installed_version = {}, None
        changes: list[PlannedChange] = []
        for entry in sorted(template.files, key=lambda value: value.path):
            destination = root / entry.path
            disk_digest: str | None = None
            if destination.is_file():
                try:
                    disk_digest = _digest(destination.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    disk_digest = "unreadable"
            recorded = installed.get(entry.path) if isinstance(installed, dict) else None
            if disk_digest is None:
                action, reason = "create", "absent in the project"
            elif disk_digest == entry.digest:
                action, reason = "keep", "already identical to the pack"
            elif entry.creator_owned:
                action, reason = "keep", "creator-owned file is never upgraded"
            elif recorded is not None and recorded == disk_digest:
                action, reason = "update", "unmodified since the last pack install"
            else:
                action, reason = "conflict", "authored locally after the last pack install"
            changes.append(PlannedChange(
                entry.path, action, entry.digest, disk_digest, reason,
            ))
        return MaterialisationPlan(
            template.template_id, template.version, template.digest,
            str(root), str(installed_version) if installed_version else None,
            tuple(changes),
        )

    def apply(
        self,
        plan: MaterialisationPlan,
        *,
        approved_overwrites: Sequence[str] = (),
        actor: str = "",
    ) -> MaterialisationReceipt:
        template = self.template(plan.template_id)
        if template.digest != plan.template_digest:
            raise ValueError("The plan was produced for a different template revision")
        root = Path(plan.target)
        approved = {_relative(value) for value in approved_overwrites}
        unknown = approved - set(plan.conflicts)
        if unknown:
            raise ValueError(
                "Approved overwrites must be conflicts from this plan: "
                + ", ".join(sorted(unknown))
            )
        refused = [path for path in plan.conflicts if path not in approved]
        if refused:
            raise PackConflict(
                "The pack refuses to overwrite authored files without approval: "
                + ", ".join(sorted(refused))
            )
        if approved and not actor.strip():
            raise ValueError("Overwriting authored files requires a named human approver")
        current = self.plan(root, plan.template_id)
        if current.digest != plan.digest:
            raise PackConflict("The project changed after the plan was reviewed")
        written: list[str] = []
        overwritten: list[str] = []
        for change in plan.changes:
            if change.action == "keep":
                continue
            if change.action == "conflict" and change.path not in approved:
                continue
            entry = template.file(change.path)
            _write(root / entry.path, entry.content)
            written.append(entry.path)
            if change.action == "conflict":
                overwritten.append(entry.path)
        recorded_at = _stamp()
        installed = {
            entry.path: _installed_digest(root / entry.path, entry)
            for entry in sorted(template.files, key=lambda value: value.path)
        }
        project_digest = _digest(_canonical(installed))
        state = {
            "pack_key": GODOT_PACK_KEY,
            "pack_version": GODOT_PACK_VERSION,
            "template_id": template.template_id,
            "template_version": template.version,
            "template_digest": template.digest,
            "engine_version": template.engine_version,
            "renderer": template.renderer,
            "main_scene": template.main_scene,
            "project_digest": project_digest,
            "recorded_at": recorded_at,
            "approved_overwrites": sorted(overwritten),
            "actor": actor.strip(),
            "files": installed,
        }
        _write(root / PACK_STATE_PATH, json.dumps(state, indent=2, sort_keys=True) + "\n")
        return MaterialisationReceipt(
            plan.digest, template.template_id, template.version, str(root),
            tuple(written), plan.kept, tuple(overwritten), project_digest,
            actor.strip(), recorded_at,
        )

    def project_digest(self, target: Path, template_id: str) -> str:
        """Digest of the pack-owned files as they exist on disk right now."""
        template = self.template(template_id)
        root = Path(target)
        return _digest(_canonical({
            entry.path: _installed_digest(root / entry.path, entry)
            for entry in sorted(template.files, key=lambda value: value.path)
        }))


def _installed_digest(path: Path, entry: TemplateFile) -> str:
    if not path.is_file():
        return "absent"
    try:
        return _digest(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return "unreadable"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".lokvetia-tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _engine_series(version: str) -> str:
    parts = str(version).strip().split(".")
    if len(parts) < 2:
        return str(version).strip()
    return f"{parts[0]}.{parts[1]}"


def export_presets(target: Path) -> tuple[str, ...]:
    """Preset names declared by the project, without invoking the engine."""
    presets_file = Path(target) / "export_presets.cfg"
    if not presets_file.is_file():
        return ()
    names: list[str] = []
    try:
        text = presets_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("name=") and stripped.count('"') >= 2:
            names.append(stripped.split('"')[1])
    return tuple(names)


def default_templates() -> tuple[GameTemplate, ...]:
    return (_collector_template(), _platformer_template())


_PROJECT_GODOT = """; Lokvetia Core Godot 2D pack. Regenerate through the pack, not by hand.
config_version=5

[application]

config/name="{name}"
config/description="{summary}"
run/main_scene="res://scenes/main.tscn"
config/features=PackedStringArray("{engine}", "GL Compatibility")

[display]

window/size/viewport_width=1152
window/size/viewport_height=648

[physics]

2d/default_gravity=980.0

[rendering]

renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
textures/canvas_textures/default_texture_filter=0
"""


_MAIN_SCENE = """[gd_scene load_steps=4 format=3]

[ext_resource type="Script" path="res://scripts/main.gd" id="1_main"]
[ext_resource type="Script" path="res://scripts/player.gd" id="2_player"]

[sub_resource type="RectangleShape2D" id="RectangleShape2D_player"]
size = Vector2(32, 32)

[node name="Main" type="Node2D"]
script = ExtResource("1_main")

[node name="Player" type="CharacterBody2D" parent="."]
position = Vector2({start_x}, {start_y})
script = ExtResource("2_player")

[node name="Shape" type="CollisionShape2D" parent="Player"]
shape = SubResource("RectangleShape2D_player")

[node name="Body" type="ColorRect" parent="Player"]
offset_left = -16.0
offset_top = -16.0
offset_right = 16.0
offset_bottom = 16.0
color = Color(0.35, 0.74, 1, 1)

[node name="HUD" type="CanvasLayer" parent="."]

[node name="Status" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 12.0
offset_right = 1136.0
offset_bottom = 44.0
text = "Loading"
"""


_EXPORT_PRESETS = """[preset.0]

name="linux-x86_64"
platform="Linux/X11"
runnable=true
advanced_options=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/linux/{slug}.x86_64"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.0.options]

binary_format/embed_pck=true
binary_format/architecture="x86_64"
texture_format/s3tc_bptc=true
texture_format/etc2_astc=false

[preset.1]

name="windows-x86_64"
platform="Windows Desktop"
runnable=true
advanced_options=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/windows/{slug}.exe"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.1.options]

binary_format/embed_pck=true
binary_format/architecture="x86_64"
texture_format/s3tc_bptc=true
texture_format/etc2_astc=false
"""


_COLLECTOR_MAIN = '''extends Node2D
## Collector starter round: gather every marker before the clock runs out.

const PICKUP_COUNT := 6
const ROUND_SECONDS := 30.0
const FIELD := Rect2(96.0, 96.0, 960.0, 456.0)

var _collected := 0
var _remaining := ROUND_SECONDS
var _finished := false

@onready var _player: CharacterBody2D = $Player
@onready var _status: Label = $HUD/Status


func _ready() -> void:
    _start_round()


func _start_round() -> void:
    for child in get_children():
        if child.is_in_group("pickup"):
            child.queue_free()
    _collected = 0
    _remaining = ROUND_SECONDS
    _finished = false
    _player.position = FIELD.position + FIELD.size * 0.5
    _player.velocity = Vector2.ZERO
    for index in PICKUP_COUNT:
        _spawn_pickup(index)
    _update_status()


func _spawn_pickup(index: int) -> void:
    var pickup := Area2D.new()
    pickup.name = "Pickup%d" % index
    pickup.add_to_group("pickup")
    pickup.position = Vector2(
        randf_range(FIELD.position.x, FIELD.end.x),
        randf_range(FIELD.position.y, FIELD.end.y)
    )
    var collision := CollisionShape2D.new()
    var circle := CircleShape2D.new()
    circle.radius = 16.0
    collision.shape = circle
    pickup.add_child(collision)
    var marker := ColorRect.new()
    marker.offset_left = -14.0
    marker.offset_top = -14.0
    marker.offset_right = 14.0
    marker.offset_bottom = 14.0
    marker.color = Color(1.0, 0.81, 0.33, 1.0)
    pickup.add_child(marker)
    pickup.body_entered.connect(_on_pickup_entered.bind(pickup))
    add_child(pickup)


func _on_pickup_entered(body: Node, pickup: Area2D) -> void:
    if _finished or body != _player or not is_instance_valid(pickup):
        return
    pickup.queue_free()
    _collected += 1
    if _collected >= PICKUP_COUNT:
        _finish("You collected everything. Press Enter to play again.")
    else:
        _update_status()


func _process(delta: float) -> void:
    if _finished:
        if Input.is_action_just_pressed("ui_accept"):
            _start_round()
        return
    _remaining -= delta
    if _remaining <= 0.0:
        _remaining = 0.0
        _finish("Time is up. Press Enter to try again.")
        return
    _update_status()


func _finish(message: String) -> void:
    _finished = true
    _status.text = message


func _update_status() -> void:
    _status.text = "Collected %d of %d    Time left %.1f s" % [
        _collected, PICKUP_COUNT, _remaining
    ]
'''


_COLLECTOR_PLAYER = '''extends CharacterBody2D
## Eight-direction movement with the built-in ui_* actions.

const SPEED := 320.0


func _physics_process(_delta: float) -> void:
    var direction := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
    velocity = direction * SPEED
    move_and_slide()
'''


_PLATFORMER_MAIN = '''extends Node2D
## Platformer starter round: reach the goal marker without falling off the map.

const FALL_LIMIT := 900.0
const PLATFORMS := [
    Rect2(0.0, 600.0, 1152.0, 48.0),
    Rect2(220.0, 470.0, 200.0, 24.0),
    Rect2(520.0, 360.0, 200.0, 24.0),
    Rect2(830.0, 250.0, 200.0, 24.0),
]
const GOAL := Vector2(930.0, 200.0)
const START := Vector2(96.0, 520.0)

var _finished := false

@onready var _player: CharacterBody2D = $Player
@onready var _status: Label = $HUD/Status


func _ready() -> void:
    for platform in PLATFORMS:
        _spawn_platform(platform)
    _spawn_goal()
    _start_round()


func _spawn_platform(rectangle: Rect2) -> void:
    var body := StaticBody2D.new()
    body.position = rectangle.position + rectangle.size * 0.5
    var collision := CollisionShape2D.new()
    var shape := RectangleShape2D.new()
    shape.size = rectangle.size
    collision.shape = shape
    body.add_child(collision)
    var surface := ColorRect.new()
    surface.offset_left = -rectangle.size.x * 0.5
    surface.offset_top = -rectangle.size.y * 0.5
    surface.offset_right = rectangle.size.x * 0.5
    surface.offset_bottom = rectangle.size.y * 0.5
    surface.color = Color(0.24, 0.31, 0.39, 1.0)
    body.add_child(surface)
    add_child(body)


func _spawn_goal() -> void:
    var goal := Area2D.new()
    goal.name = "Goal"
    goal.position = GOAL
    var collision := CollisionShape2D.new()
    var shape := RectangleShape2D.new()
    shape.size = Vector2(40.0, 40.0)
    collision.shape = shape
    goal.add_child(collision)
    var marker := ColorRect.new()
    marker.offset_left = -20.0
    marker.offset_top = -20.0
    marker.offset_right = 20.0
    marker.offset_bottom = 20.0
    marker.color = Color(0.42, 0.89, 0.51, 1.0)
    goal.add_child(marker)
    goal.body_entered.connect(_on_goal_entered)
    add_child(goal)


func _start_round() -> void:
    _finished = false
    _player.position = START
    _player.velocity = Vector2.ZERO
    _status.text = "Arrow keys to move, Enter to jump. Reach the green marker."


func _on_goal_entered(body: Node) -> void:
    if _finished or body != _player:
        return
    _finish("You reached the goal. Press Enter to play again.")


func _process(_delta: float) -> void:
    if _finished:
        if Input.is_action_just_pressed("ui_accept"):
            _start_round()
        return
    if _player.position.y > FALL_LIMIT:
        _finish("You fell off the map. Press Enter to try again.")


func _finish(message: String) -> void:
    _finished = true
    _status.text = message
'''


_PLATFORMER_PLAYER = '''extends CharacterBody2D
## Run and jump with the built-in ui_* actions and the project gravity setting.

const SPEED := 260.0
const JUMP_VELOCITY := -520.0

var _gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity", 980.0)


func _physics_process(delta: float) -> void:
    if not is_on_floor():
        velocity.y += _gravity * delta
    elif Input.is_action_just_pressed("ui_accept"):
        velocity.y = JUMP_VELOCITY
    velocity.x = Input.get_axis("ui_left", "ui_right") * SPEED
    move_and_slide()
'''


_README = """# {name}

{summary}

This project was created from the Lokvetia Core `{pack}` pack, template
`{template}` version {version}, for Godot {engine} with the
`{renderer}` renderer.

## Play it

1. Open the folder in the Godot editor and press Play, or run
   `godot --path . ` from this directory.
2. Arrow keys move. Enter restarts a finished round.

## Keep your own work

`{state}` records the digest of every pack-owned file at install time. A pack
upgrade previews its changes first and refuses to overwrite a file you edited
unless you approve that exact file. This README is yours: the pack writes it
once and never replaces it.
"""


def _template_files(
    *,
    name: str,
    slug: str,
    summary: str,
    template_id: str,
    version: str,
    engine: str,
    main_script: str,
    player_script: str,
    start: tuple[float, float],
) -> tuple[TemplateFile, ...]:
    return (
        TemplateFile.create("project.godot", _PROJECT_GODOT.format(
            name=name, summary=summary, engine=engine,
        )),
        TemplateFile.create("scenes/main.tscn", _MAIN_SCENE.format(
            start_x=start[0], start_y=start[1],
        )),
        TemplateFile.create("scripts/main.gd", main_script),
        TemplateFile.create("scripts/player.gd", player_script),
        TemplateFile.create("export_presets.cfg", _EXPORT_PRESETS.format(slug=slug)),
        TemplateFile.create(
            "README.md",
            _README.format(
                name=name, summary=summary, pack=GODOT_PACK_KEY,
                template=template_id, version=version, engine=engine,
                renderer=BASELINE_RENDERER, state=PACK_STATE_PATH,
            ),
            creator_owned=True,
        ),
    )


def _collector_template() -> GameTemplate:
    return GameTemplate.create(
        "collector-2d",
        title="Collector starter",
        summary="Collect every marker on an open field before the round timer ends.",
        version="1.1.0",
        main_scene="scenes/main.tscn",
        files=_template_files(
            name="Collector Starter", slug="collector-starter",
            summary="Collect every marker before the timer ends.",
            template_id="collector-2d", version="1.1.0",
            engine=BASELINE_ENGINE_VERSION,
            main_script=_COLLECTOR_MAIN, player_script=_COLLECTOR_PLAYER,
            start=(576.0, 324.0),
        ),
    )


def _platformer_template() -> GameTemplate:
    return GameTemplate.create(
        "platformer-2d",
        title="Platformer starter",
        summary="Run and jump across four platforms to reach the goal marker.",
        version="1.1.0",
        main_scene="scenes/main.tscn",
        files=_template_files(
            name="Platformer Starter", slug="platformer-starter",
            summary="Reach the goal marker without falling off the map.",
            template_id="platformer-2d", version="1.1.0",
            engine=BASELINE_ENGINE_VERSION,
            main_script=_PLATFORMER_MAIN, player_script=_PLATFORMER_PLAYER,
            start=(96.0, 520.0),
        ),
    )
