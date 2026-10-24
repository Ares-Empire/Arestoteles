"""The sync loop: pulls rebuild the index, unpushed app commits are replayed and pushed, and a local commit that
conflicts with GitHub is never lost."""

from __future__ import annotations

import time

from conftest import APP, git, edit, note, position

PRESS = "Topics/Printing press/Printing press.md"


def test_pull_fast_forwards_and_rebuilds(client, world, service):
    old = service.current().commit
    world.laptop_commit("Library/Actors/Martin Luther.md", lambda t: t.replace("Monk", "Monk, preacher"))
    assert note(service.current().vault, "Martin Luther")["blocks"][0]["text"].startswith("Monk and")
    service.sync()
    assert service.current().commit != old
    vault = client.get("/api/arestoteles/vault", headers=APP).json()
    assert note(vault, "Martin Luther")["blocks"][0]["text"].startswith("Monk, preacher")


def test_sync_without_changes_keeps_the_index(service):
    built = service.current()
    service.sync()
    assert service.current() is built


def test_unpushed_commit_is_replayed_on_a_pull(client, world, service):
    away = world.remote.with_name("away.git")
    world.remote.rename(away)
    assert edit(client, op="confirm_position", position="Printing press#2").json()["pushed"] is False
    away.rename(world.remote)
    world.laptop_commit("Glossary.md", lambda t: t + "| copy | Abschrift | [[Spread of print]] |\n", "Glossary term")
    service.sync()
    assert world.remote_log(2)[0].endswith("|App: confirm position 2 (Printing press)")
    assert world.remote_log(2)[1].endswith("|Glossary term")
    vault = service.current().vault
    assert position(vault, "Printing press#2")["draft"] is False
    assert len(vault["glossary"]) == 3
    assert service.health()["pushed"] is True


def test_conflicting_local_commit_is_kept_on_a_branch(client, world, service):
    away = world.remote.with_name("away.git")
    world.remote.rename(away)
    assert edit(client, op="confirm_position", position="Printing press#2").json()["pushed"] is False
    away.rename(world.remote)
    world.laptop_commit(PRESS, lambda t: t.replace("what sold.** *(draft)*", "what sold, nothing more.**"))
    service.sync()
    assert git(world.vault, "rev-parse", "HEAD").stdout == git(world.remote, "rev-parse", "main").stdout
    branches = git(world.remote, "branch", "--list", "arestoteles-app/*").stdout.split()
    assert branches == ["arestoteles-app/conflict-20261024-160500"]
    kept = git(world.remote, "log", "-1", "--format=%s", branches[0]).stdout.strip()
    assert kept == "App: confirm position 2 (Printing press)"
    assert position(service.current().vault, "Printing press#2")["text"].endswith("nothing more.")
    assert service.health()["pushed"] is True


def test_the_loop_runs_in_the_background(world):
    service = world.service()
    world.laptop_commit("Library/Actors/Martin Luther.md", lambda t: t + "\nOne more line.\n")
    loop = service.start_loop()
    deadline = time.monotonic() + 10
    while service.pulled is None and time.monotonic() < deadline:
        time.sleep(0.05)
    loop.stop()
    assert service.pulled is not None
    assert "One more line." in note(service.current().vault, "Martin Luther")["blocks"][-1]["text"]
