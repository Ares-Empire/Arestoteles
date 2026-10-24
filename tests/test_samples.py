"""The made-up fixture vault builds exactly docs/samples (except the commit, the build time and each version), and the
samples match the contract's types."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from arestoteles.api import create_app
from arestoteles.models import EditResult, NoteSource, Vault

from conftest import APP, SAMPLES, edit


def load(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def comparable(vault: dict) -> dict:
    vault = json.loads(json.dumps(vault))
    vault["commit"] = vault["built"] = "-"
    for n in vault["notes"]:
        n["version"] = "-"
    return vault


def test_samples_follow_the_contract():
    Vault.model_validate(load("vault.json"))
    NoteSource.model_validate(load("note-source.json"))
    EditResult.model_validate(load("edit-result.json"))


def test_fixture_builds_the_sample_vault(service):
    built = service.current()
    assert comparable(built.vault) == comparable(load("vault.json"))
    Vault.model_validate(built.vault)
    assert built.unresolved == {"How literacy grew after 1500": ["Home"], "Paper mills in the 15th century": ["Home"]}


def test_served_vault_is_the_built_one(client, service):
    answer = client.get("/api/arestoteles/vault", headers=APP)
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/json"
    assert answer.json() == service.current().vault
    assert answer.json()["commit"] == service.repo.head(short=True)


def test_note_source_sample(client, service):
    answer = client.get("/api/arestoteles/notes/Spread%20of%20print/source", headers=APP)
    assert answer.status_code == 200
    sample = load("note-source.json")
    assert {**answer.json(), "version": "-"} == {**sample, "version": "-"}
    assert answer.json()["version"] == next(n["version"] for n in service.current().vault["notes"]
                                            if n["id"] == "Spread of print")


def test_edit_result_sample(world):
    client = TestClient(create_app(world.service()))
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 200
    sample = load("edit-result.json")
    got = answer.json()
    assert {k: v for k, v in got.items() if k != "vault"} == {k: v for k, v in sample.items() if k != "vault"}
    assert comparable(got["vault"]) == comparable(sample["vault"])
    EditResult.model_validate(got)
