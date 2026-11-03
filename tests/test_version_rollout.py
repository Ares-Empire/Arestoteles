"""Version enforcement can be enabled after both old and new phone clients can use the updated server."""

import pytest
from fastapi.testclient import TestClient

from arestoteles.api import create_app
from arestoteles.config import Settings
from conftest import APP, edit


def test_version_enforcement_setting_defaults_off():
    assert Settings().require_versions is False
    assert Settings.from_env({}).require_versions is False
    assert Settings.from_env({"ARESTOTELES_REQUIRE_VERSIONS": "0"}).require_versions is False
    assert Settings.from_env({"ARESTOTELES_REQUIRE_VERSIONS": "1"}).require_versions is True


def test_unversioned_edits_are_logged_once_per_kind(client, caplog):
    # No helper: these are the exact old-client bodies, without an automatically added version.
    for _ in range(2):
        for body in ({"op": "reword_position", "position": "Printing press#2", "text": "An old client's wording."},
                     {"op": "set_confidence", "note": "Printing press", "confidence": "solid"}):
            answer = client.post("/api/arestoteles/edits", headers=APP, json=body)
            assert answer.status_code == 200
    assert [r.getMessage() for r in caplog.records] == [
        "unversioned reword_position edit allowed (ARESTOTELES_REQUIRE_VERSIONS=0)",
        "unversioned set_confidence edit allowed (ARESTOTELES_REQUIRE_VERSIONS=0)",
    ]   # no note name, body, version or token is logged


@pytest.mark.parametrize("require_versions", [False, True])
def test_an_actual_stale_version_cannot_overwrite_a_newer_edit(world, require_versions, caplog):
    service = world.service(require_versions=require_versions)
    client = TestClient(create_app(service))
    old = service.source("Printing press")["version"]
    body = {"op": "reword_position", "position": "Printing press#2", "version": old, "text": "The newer wording."}
    assert client.post("/api/arestoteles/edits", headers=APP, json=body).status_code == 200
    before = service.repo.head()
    answer = client.post("/api/arestoteles/edits", headers=APP, json={**body, "text": "The stale wording."})
    assert answer.status_code == 409
    assert answer.json()["current"]["version"] != old
    assert service.repo.head() == before
    assert "The newer wording." in service.source("Printing press")["markdown"]
    assert not caplog.records


@pytest.mark.parametrize("require_versions", [False, True])
def test_plain_quick_notes_and_versioned_edits_do_not_log_legacy_use(world, require_versions, caplog):
    client = TestClient(create_app(world.service(require_versions=require_versions)))
    assert edit(client, op="quick_note", text="A plain quick note.").status_code == 200
    assert edit(client, op="confirm_position", position="Printing press#2").status_code == 200
    assert not caplog.records


@pytest.mark.parametrize("require_versions", [False, True])
@pytest.mark.parametrize("body", [
    {"op": "edit_note", "note": "Printing press", "markdown": "A replacement."},
    {"op": "adopt_callout", "note": "Printing press", "callout": 0},
    {"op": "dismiss_callout", "note": "Printing press", "callout": 0},
])
def test_preexisting_version_requirements_are_not_relaxed(world, require_versions, body, caplog):
    service = world.service(require_versions=require_versions)
    client = TestClient(create_app(service))
    before = service.repo.head()
    answer = client.post("/api/arestoteles/edits", headers=APP, json=body)
    assert answer.status_code == 400
    assert service.repo.head() == before
    assert not caplog.records
