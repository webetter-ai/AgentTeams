import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from qwenpaw_worker.sync import FileSync, push_local, push_loop


def _sync(tmp_path: Path) -> FileSync:
    return FileSync(
        endpoint="http://minio:9000",
        access_key="minio",
        secret_key="password",
        bucket="agentteams-storage",
        worker_name="worker-a",
        local_dir=tmp_path / "agents" / "worker-a",
        shared_dir=tmp_path / "shared",
        remote_prefix="agents/worker-a",
        shared_prefix="shared",
    )


def test_mirror_all_restores_worker_and_shared_storage(tmp_path: Path, monkeypatch) -> None:
    sync = _sync(tmp_path)
    commands = []

    monkeypatch.setattr(sync, "ensure_alias", lambda: None)

    def fake_mc(*args, **_kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    sync.mirror_all()

    assert commands == [
        (
            "mirror",
            "agentteams/agentteams-storage/agents/worker-a/",
            f"{sync.local_dir}/",
            "--overwrite",
            "--exclude",
            "credentials/**",
        ),
        (
            "mirror",
            "agentteams/agentteams-storage/shared/",
            f"{sync.shared_dir}/",
            "--overwrite",
            "--exclude",
            "credentials/**",
        ),
    ]


def test_pull_runtime_config_downloads_controller_projection(tmp_path: Path, monkeypatch) -> None:
    sync = _sync(tmp_path)
    commands = []
    target = sync.local_dir / "runtime" / "runtime.yaml"

    monkeypatch.setattr(sync, "ensure_alias", lambda: None)

    def fake_mc(*args, **kwargs):
        commands.append((args, kwargs))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("member:\n  runtime: qwenpaw\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    assert sync.pull_runtime_config(target) is True

    assert target.read_text(encoding="utf-8").startswith("member:")
    assert commands == [
        (
            (
                "cp",
                "agentteams/agentteams-storage/agents/worker-a/runtime/runtime.yaml",
                str(target),
            ),
            {"check": False},
        )
    ]


def test_ensure_alias_skips_static_alias_in_k8s_mode(tmp_path: Path, monkeypatch) -> None:
    sync = FileSync(
        endpoint="https://oss.example.test",
        access_key="access-key",
        secret_key="secret-key",
        bucket="agentteams-storage",
        worker_name="worker-a",
        local_dir=tmp_path / "agents" / "worker-a",
        shared_dir=tmp_path / "shared",
    )
    commands = []
    monkeypatch.setenv("AGENTTEAMS_RUNTIME", "k8s")

    def fake_mc(*args, **_kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    sync.ensure_alias()

    assert sync._alias_set is True
    assert commands == []


def test_storage_alias_derives_from_agentteams_storage_prefix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTTEAMS_STORAGE_PREFIX", "agentteams/agentteams-storage")

    sync = _sync(tmp_path)

    assert sync.mc_alias == "agentteams"
    assert sync._object_path("agents/worker-a/file.txt") == "agentteams/agentteams-storage/agents/worker-a/file.txt"


def test_push_local_uploads_worker_files_but_skips_controller_owned_state(tmp_path: Path, monkeypatch) -> None:
    sync = _sync(tmp_path)
    uploads = []

    files = {
        "SOUL.md": "worker soul",
        ".qwenpaw/workspaces/default/AGENTS.md": "runtime prompt",
        ".qwenpaw/workspaces/default/TEAMS.md": "team prompt",
        ".qwenpaw/workspaces/default/config/mcporter.json": '{"mcpServers":{}}',
        ".qwenpaw/plugins/teamharness/plugin.py": "installed plugin",
        ".qwenpaw/skill_pool/teamharness-communication/SKILL.md": "skill",
        ".qwenpaw/workspaces/default/skills/custom/SKILL.md": "workspace skill",
        ".qwenpaw/agent-packages/current/AGENTS.md": "agent package",
        ".qwenpaw/qwenpaw.log": "log",
        ".qwenpaw/logs/qwenpaw-worker.log": "worker log",
        ".qwenpaw/workspaces/default/tool_result/result.json": "{}",
        ".qwenpaw/workspaces/default/file_store/a.bin": "file",
        "runtime/runtime.yaml": "controller owned runtime config",
        "credentials/token": "secret",
        "shared/tasks/t-1/result.md": "team shared",
        "global-shared/reference.md": "global shared",
        "inbox/memory-edits/e-1.json": '{"edit_id":"e-1"}',
    }
    for rel, content in files.items():
        path = sync.local_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(sync, "ensure_alias", lambda: None)
    monkeypatch.setattr(sync, "_cat_bytes", lambda _key: None)

    def fake_mc(*args, **_kwargs):
        if args[0] == "cp":
            uploads.append(args[2])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    pushed = push_local(sync, since=0)

    assert set(pushed) == {
        "SOUL.md",
        ".qwenpaw/workspaces/default/AGENTS.md",
        ".qwenpaw/workspaces/default/TEAMS.md",
        ".qwenpaw/workspaces/default/config/mcporter.json",
        ".qwenpaw/plugins/teamharness/plugin.py",
        ".qwenpaw/skill_pool/teamharness-communication/SKILL.md",
        ".qwenpaw/workspaces/default/skills/custom/SKILL.md",
        ".qwenpaw/agent-packages/current/AGENTS.md",
    }
    assert "runtime/runtime.yaml" not in pushed
    assert not any("credentials" in item for item in pushed)
    assert not any("logs/" in item for item in pushed)
    assert not any("shared/" in item for item in pushed)
    assert not any(item.startswith("inbox/") for item in pushed)
    assert set(uploads) == {
        "agentteams/agentteams-storage/agents/worker-a/SOUL.md",
        "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/workspaces/default/AGENTS.md",
        "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/workspaces/default/TEAMS.md",
        "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/workspaces/default/config/mcporter.json",
        "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/plugins/teamharness/plugin.py",
        "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/skill_pool/teamharness-communication/SKILL.md",
        "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/workspaces/default/skills/custom/SKILL.md",
        "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/agent-packages/current/AGENTS.md",
    }


def test_push_paths_persists_selected_migration_files_in_order(tmp_path: Path, monkeypatch) -> None:
    sync = _sync(tmp_path)
    session = sync.local_dir / ".qwenpaw" / "workspaces" / "default" / "chats.json"
    marker = sync.local_dir / ".qwenpaw" / ".copaw-migrated"
    session.parent.mkdir(parents=True)
    session.write_text("legacy-session", encoding="utf-8")
    marker.write_text("copaw-to-qwenpaw\n", encoding="utf-8")
    uploads = []

    monkeypatch.setattr(sync, "ensure_alias", lambda: None)
    monkeypatch.setattr(sync, "_cat_bytes", lambda _key: None)

    def fake_mc(*args, **_kwargs):
        uploads.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    assert sync.push_paths([session, marker]) == [
        ".qwenpaw/workspaces/default/chats.json",
        ".qwenpaw/.copaw-migrated",
    ]
    assert [args[2] for args in uploads] == [
        "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/workspaces/default/chats.json",
        "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/.copaw-migrated",
    ]


def test_push_directories_mirrors_migration_roots(tmp_path: Path, monkeypatch) -> None:
    sync = _sync(tmp_path)
    working_dir = sync.local_dir / ".qwenpaw"
    secret_dir = sync.local_dir / ".qwenpaw.secret"
    working_dir.mkdir(parents=True)
    secret_dir.mkdir()
    commands = []

    monkeypatch.setattr(sync, "ensure_alias", lambda: None)

    def fake_mc(*args, **_kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    assert sync.push_directories([working_dir, secret_dir]) == [".qwenpaw", ".qwenpaw.secret"]
    assert commands == [
        (
            "mirror",
            f"{working_dir}/",
            "agentteams/agentteams-storage/agents/worker-a/.qwenpaw/",
            "--overwrite",
        ),
        (
            "mirror",
            f"{secret_dir}/",
            "agentteams/agentteams-storage/agents/worker-a/.qwenpaw.secret/",
            "--overwrite",
        ),
    ]


def test_push_local_does_not_remove_remote_files_missing_from_local_state(tmp_path: Path, monkeypatch) -> None:
    sync = _sync(tmp_path)
    commands = []

    current = sync.local_dir / ".qwenpaw" / "workspaces" / "default" / "AGENTS.md"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text("runtime prompt", encoding="utf-8")

    monkeypatch.setattr(sync, "ensure_alias", lambda: None)
    monkeypatch.setattr(sync, "_cat_bytes", lambda key: b"runtime prompt" if key.endswith("/AGENTS.md") else None)

    def fake_mc(*args, **_kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    assert push_local(sync, since=0) == []
    assert not any(args[0] == "rm" for args in commands)
    assert not any(args[0] == "find" for args in commands)


def test_push_local_skips_older_and_unchanged_files(tmp_path: Path, monkeypatch) -> None:
    sync = _sync(tmp_path)
    uploads = []

    old_file = sync.local_dir / "old.txt"
    old_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.write_text("old", encoding="utf-8")
    os.utime(old_file, (1, 1))

    same_file = sync.local_dir / "same.txt"
    same_file.write_text("same", encoding="utf-8")

    changed_file = sync.local_dir / "changed.txt"
    changed_file.write_text("changed", encoding="utf-8")

    monkeypatch.setattr(sync, "ensure_alias", lambda: None)
    monkeypatch.setattr(sync, "_cat_bytes", lambda key: b"same" if key.endswith("/same.txt") else None)

    def fake_mc(*args, **_kwargs):
        if args[0] == "cp":
            uploads.append(args[2])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    assert push_local(sync, since=100) == ["changed.txt"]
    assert uploads == ["agentteams/agentteams-storage/agents/worker-a/changed.txt"]


def test_push_local_compares_small_binary_files_as_bytes(tmp_path: Path, monkeypatch) -> None:
    sync = _sync(tmp_path)
    uploads = []

    same_file = sync.local_dir / "same.bin"
    same_file.parent.mkdir(parents=True, exist_ok=True)
    same_file.write_bytes(b"\xff\x00same")

    changed_file = sync.local_dir / "changed.bin"
    changed_file.write_bytes(b"\xff\x00changed")

    monkeypatch.setattr(sync, "ensure_alias", lambda: None)

    def fake_cat_bytes(key):
        if key.endswith("/same.bin"):
            return b"\xff\x00same"
        if key.endswith("/changed.bin"):
            return b"\xff\x00old"
        return None

    monkeypatch.setattr(sync, "_cat_bytes", fake_cat_bytes)

    def fake_mc(*args, **_kwargs):
        if args[0] == "cp":
            uploads.append(args[2])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    assert push_local(sync, since=0) == ["changed.bin"]
    assert uploads == ["agentteams/agentteams-storage/agents/worker-a/changed.bin"]


def test_push_local_uploads_large_files_without_remote_content_compare(tmp_path: Path, monkeypatch) -> None:
    sync = _sync(tmp_path)
    uploads = []

    large_file = sync.local_dir / "large.zip"
    large_file.parent.mkdir(parents=True, exist_ok=True)
    large_file.write_bytes(b"0" * (21 * 1024 * 1024))

    monkeypatch.setattr(sync, "ensure_alias", lambda: None)

    def fail_cat_bytes(_key):
        raise AssertionError("large files should not download remote content for comparison")

    monkeypatch.setattr(sync, "_cat_bytes", fail_cat_bytes)

    def fake_mc(*args, **_kwargs):
        if args[0] == "cp":
            uploads.append(args[2])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_mc", fake_mc)

    assert push_local(sync, since=0) == ["large.zip"]
    assert uploads == ["agentteams/agentteams-storage/agents/worker-a/large.zip"]


@pytest.mark.anyio
async def test_push_loop_starts_from_current_time_instead_of_full_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync = _sync(tmp_path)
    since_values: list[float] = []
    sleeps = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    async def fake_to_thread(_function, _sync, since):
        since_values.append(since)
        return []

    monkeypatch.setattr("qwenpaw_worker.sync.time.time", lambda: 123.0)
    monkeypatch.setattr("qwenpaw_worker.sync.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("qwenpaw_worker.sync.asyncio.to_thread", fake_to_thread)

    await push_loop(sync, check_interval=0)

    assert since_values == [123.0]


INBOX_REMOTE = "agentteams/agentteams-storage/agents/worker-a/inbox"


class FakeInboxStore:
    """Fake ``mc`` for inbox tests: ``ls --recursive --json`` and ``cp`` only."""

    def __init__(self, objects: dict[str, tuple[str, bytes]]) -> None:
        self.objects = dict(objects)  # key relative to inbox/ -> (etag, content)
        self.commands: list[tuple] = []
        self.ls_result: subprocess.CompletedProcess | None = None
        self.cp_failures: dict[str, int] = {}

    def __call__(self, *args, **_kwargs):
        self.commands.append(args)
        if args[0] == "ls":
            assert args[1:] == ("--recursive", "--json", f"{INBOX_REMOTE}/")
            if self.ls_result is not None:
                return self.ls_result
            lines = [
                json.dumps(
                    {
                        "status": "success",
                        "type": "file",
                        "lastModified": "2026-10-08T00:00:00Z",
                        "size": len(content),
                        "key": key,
                        "etag": etag,
                    }
                )
                for key, (etag, content) in sorted(self.objects.items())
            ]
            return subprocess.CompletedProcess(args, 0, stdout="\n".join(lines), stderr="")
        if args[0] == "cp":
            key = args[1][len(INBOX_REMOTE) + 1 :]
            if self.cp_failures.get(key):
                self.cp_failures[key] -= 1
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="connection reset")
            if key not in self.objects:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="Object does not exist")
            Path(args[2]).write_bytes(self.objects[key][1])
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected mc command: {args}")

    def downloads(self) -> list[str]:
        return [args[1][len(INBOX_REMOTE) + 1 :] for args in self.commands if args[0] == "cp"]


def _inbox_sync(tmp_path: Path, monkeypatch, store: FakeInboxStore) -> FileSync:
    sync = _sync(tmp_path)
    monkeypatch.setattr(sync, "ensure_alias", lambda: None)
    monkeypatch.setattr(sync, "_mc", store)
    return sync


def test_pull_inbox_downloads_new_and_changed_objects_only(tmp_path: Path, monkeypatch) -> None:
    store = FakeInboxStore(
        {
            "forget.json": ("etag-1", b'{"items":[]}'),
            "memory-edits/e-1.json": ("etag-2", b'{"edit_id":"e-1"}'),
        }
    )
    sync = _inbox_sync(tmp_path, monkeypatch, store)
    inbox = sync.local_dir / "inbox"

    first = sync.pull_inbox()

    assert first.downloaded == ["forget.json", "memory-edits/e-1.json"]
    assert first.removed == []
    assert (inbox / "forget.json").read_bytes() == b'{"items":[]}'
    assert (inbox / "memory-edits" / "e-1.json").read_bytes() == b'{"edit_id":"e-1"}'
    assert not [p for p in inbox.rglob("*") if p.name.endswith(".inbox-partial")]

    # Unchanged listing: only the ls call, no downloads.
    store.commands.clear()
    second = sync.pull_inbox()
    assert second.changed is False
    assert store.downloads() == []

    # Changed etag: only that object is downloaded again.
    store.objects["forget.json"] = ("etag-3", b'{"items":["x"]}')
    store.commands.clear()
    third = sync.pull_inbox()
    assert third.downloaded == ["forget.json"]
    assert store.downloads() == ["forget.json"]
    assert (inbox / "forget.json").read_bytes() == b'{"items":["x"]}'


def test_pull_inbox_removes_local_files_deleted_remotely_only_inside_inbox(tmp_path: Path, monkeypatch) -> None:
    store = FakeInboxStore(
        {
            "memory-edits/e-1.json": ("etag-1", b"one"),
            "memory-edits/e-2.json": ("etag-2", b"two"),
            "cards/7/brief.pdf.v1": ("etag-3", b"pdf"),
        }
    )
    sync = _inbox_sync(tmp_path, monkeypatch, store)
    inbox = sync.local_dir / "inbox"
    outside = sync.local_dir / "memory-edits" / "e-1.json"
    outside.parent.mkdir(parents=True)
    outside.write_text("worker-owned file outside inbox", encoding="utf-8")
    sync.pull_inbox()

    # The control plane deletes acknowledged objects.
    del store.objects["memory-edits/e-1.json"]
    del store.objects["cards/7/brief.pdf.v1"]
    result = sync.pull_inbox()

    assert result.downloaded == []
    assert sorted(result.removed) == ["cards/7/brief.pdf.v1", "memory-edits/e-1.json"]
    assert not (inbox / "memory-edits" / "e-1.json").exists()
    assert (inbox / "memory-edits" / "e-2.json").read_bytes() == b"two"
    assert not (inbox / "cards").exists()
    assert inbox.is_dir()
    assert outside.read_text(encoding="utf-8") == "worker-owned file outside inbox"


def test_pull_inbox_treats_missing_prefix_as_empty_inbox(tmp_path: Path, monkeypatch) -> None:
    store = FakeInboxStore({})
    sync = _inbox_sync(tmp_path, monkeypatch, store)
    stale = sync.local_dir / "inbox" / "forget.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    store.ls_result = subprocess.CompletedProcess(
        ("ls",),
        1,
        stdout=json.dumps({"status": "error", "error": {"message": "Object does not exist"}}),
        stderr="",
    )

    result = sync.pull_inbox()

    assert result.removed == ["forget.json"]
    assert not stale.exists()


def test_pull_inbox_keeps_local_files_when_listing_fails(tmp_path: Path, monkeypatch) -> None:
    store = FakeInboxStore({})
    sync = _inbox_sync(tmp_path, monkeypatch, store)
    kept = sync.local_dir / "inbox" / "forget.json"
    kept.parent.mkdir(parents=True)
    kept.write_text("{}", encoding="utf-8")
    store.ls_result = subprocess.CompletedProcess(
        ("ls",),
        1,
        stdout=json.dumps({"status": "error", "error": {"message": "Access Denied."}}),
        stderr="",
    )

    with pytest.raises(RuntimeError, match="list inbox failed"):
        sync.pull_inbox()
    assert kept.read_text(encoding="utf-8") == "{}"

    store.ls_result = subprocess.CompletedProcess(("ls",), 0, stdout="not-json", stderr="")
    with pytest.raises(RuntimeError, match="unparseable"):
        sync.pull_inbox()
    assert kept.exists()


def test_pull_inbox_skips_unsafe_keys_and_retries_failed_downloads(tmp_path: Path, monkeypatch) -> None:
    store = FakeInboxStore(
        {
            "../escape.json": ("etag-1", b"escape"),
            "ok.json": ("etag-2", b"ok"),
        }
    )
    store.cp_failures["ok.json"] = 1
    sync = _inbox_sync(tmp_path, monkeypatch, store)

    first = sync.pull_inbox()
    assert first.failed == ["ok.json"]
    assert first.downloaded == []
    assert not (sync.local_dir / "escape.json").exists()
    assert not [p for p in (sync.local_dir / "inbox").rglob("*") if p.is_file()]

    second = sync.pull_inbox()
    assert second.downloaded == ["ok.json"]
    assert (sync.local_dir / "inbox" / "ok.json").read_bytes() == b"ok"
