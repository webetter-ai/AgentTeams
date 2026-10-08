"""Tests for Hermes worker file sync behavior."""

from __future__ import annotations

import json
import subprocess

from hermes_worker import sync as sync_module
from hermes_worker.sync import FileSync


def test_mirror_all_falls_back_to_startup_files_when_prefix_missing(
    tmp_path, monkeypatch
) -> None:
    sync = FileSync(
        endpoint="http://minio:9000",
        access_key="minio",
        secret_key="password",
        bucket="agentteams-storage",
        worker_name="dag-team-dev",
        local_dir=tmp_path / "worker",
    )
    commands = []

    monkeypatch.setattr(sync, "_ensure_alias", lambda: None)

    def fake_mc(*args, **_kwargs):
        commands.append(args)
        if args[0] == "mirror" and args[1].endswith("/agents/dag-team-dev/"):
            raise subprocess.CalledProcessError(
                1,
                args,
                output="",
                stderr="mc.bin: <ERROR> Object does not exist.",
            )
        if args[0] == "cat" and args[1].endswith(
            "/agents/dag-team-dev/openclaw.json"
        ):
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"team_id":"dag-team"}',
                stderr="",
            )
        if args[0] == "cat":
            raise subprocess.CalledProcessError(
                1,
                args,
                output="",
                stderr="mc.bin: <ERROR> Object does not exist.",
            )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync_module, "_mc", fake_mc)

    sync.mirror_all()

    assert json.loads((sync.local_dir / "openclaw.json").read_text()) == {
        "team_id": "dag-team"
    }
    assert (
        "mirror",
        "agentteams/agentteams-storage/teams/dag-team/shared/",
        f"{sync.local_dir / 'shared'}/",
        "--overwrite",
    ) in commands


def test_push_local_never_pushes_inbox(tmp_path, monkeypatch) -> None:
    sync = FileSync(
        endpoint="http://minio:9000",
        access_key="minio",
        secret_key="password",
        bucket="agentteams-storage",
        worker_name="dag-team-dev",
        local_dir=tmp_path / "worker",
    )
    for rel in ("inbox/memory-edits/e-1.json", "memory/inbox/note.md", "AGENTS.md"):
        path = sync.local_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content")
    uploads = []

    monkeypatch.setattr(sync, "_ensure_alias", lambda: None)
    monkeypatch.setattr(sync, "_cat", lambda _key: None)

    def fake_mc(*args, **_kwargs):
        if args[0] == "cp":
            uploads.append(args[2])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync_module, "_mc", fake_mc)

    pushed = sync_module.push_local(sync, since=0)

    assert sorted(pushed) == ["AGENTS.md", "memory/inbox/note.md"]
    assert not any("/agents/dag-team-dev/inbox/" in dest for dest in uploads)
