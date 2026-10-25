"""Login, languages, ETag/304, health and the plain route errors."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arestoteles.api import INDEX_SHAPE, create_app
from arestoteles.texts import TEXTS, language, text

from conftest import APP

BASE = "/api/arestoteles"


@pytest.mark.parametrize("header,expected", [
    (None, "en"), ("", "en"), ("fr", "en"), ("unreadable !", "en"),
    ("de", "de"), ("de-DE", "de"), ("de-DE,de;q=0.9,en;q=0.8", "de"),
    ("en", "en"), ("en-GB,de;q=0.5", "en"), ("de;q=0.5,en;q=0.9", "en"),
    ("fr;q=1,de;q=0.8,en;q=0.7", "de"), ("de;q=0.8,en;q=0.8", "de"), ("en;q=0.8,de;q=0.8", "en"),
    ("de;q=0,en;q=0.1", "en"), ("de;q=nope", "en"), ("de;q=1.1", "en"), ("DE-de; Q=0.9,en;q=0.1", "de"),
])
def test_request_language(client, header, expected):
    assert language(header) == expected
    headers = {} if header is None else {"Accept-Language": header}
    answer = client.get(BASE + "/vault", headers=headers)
    assert answer.status_code == 401
    assert answer.headers["Content-Language"] == expected
    assert "Accept-Language" in answer.headers["Vary"]
    assert answer.json() == {"error": text("unauthenticated").get(expected)}


@pytest.mark.parametrize("language_", ["en", "de"])
@pytest.mark.parametrize("path,token,status,key", [
    ("/vault", None, 401, "unauthenticated"),
    ("/vault", "unknown-token", 401, "unauthenticated"),
    ("/vault", "other-token", 403, "forbidden"),
    ("/vault", "stranger-token", 403, "forbidden"),
    ("/notes/Nowhere/source", "patrik-token", 404, "unknown_note"),
    ("/missing", None, 404, "unknown_route"),
])
def test_errors_in_both_languages(client, path, token, status, key, language_):
    headers = {"Accept-Language": language_, **({"Authorization": f"Bearer {token}"} if token else {})}
    answer = client.get(BASE + path, headers=headers)
    assert answer.status_code == status
    assert answer.headers["Content-Language"] == language_
    assert answer.json() == {"error": text(key).get(language_)}


ROUTES = [("GET", "/vault", None), ("GET", "/notes/Printing press/source", None), ("GET", "/search?q=print", None),
          ("POST", "/edits", {"op": "quick_note", "text": "Fictional note.", "kind": "discuss"})]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_only_the_owner_gets_in(world, method, path, body):
    """Every route with a login: an approved account with the service is still refused unless it is an owner, and no
    owners means nobody (EMPIRE_ALLOWED_USERS, fail closed)."""
    client = TestClient(create_app(world.service()))
    stranger = client.request(method, BASE + path, json=body, headers={"Authorization": "Bearer stranger-token"})
    assert (stranger.status_code, stranger.json()) == (403, {"error": text("forbidden").en})
    world.owners.clear()
    nobody = TestClient(create_app(world.service()))
    patrik = nobody.request(method, BASE + path, json=body, headers=APP)
    assert (patrik.status_code, patrik.json()) == (403, {"error": text("forbidden").en})


def test_the_owner_list_comes_from_the_environment():
    from arestoteles.config import Settings
    assert Settings.from_env({}).allowed_users == frozenset()
    assert Settings.from_env({"EMPIRE_ALLOWED_USERS": ""}).allowed_users == frozenset()
    assert Settings.from_env({"EMPIRE_ALLOWED_USERS": " a1, ,b2 ,"}).allowed_users == {"a1", "b2"}


@pytest.mark.parametrize("language_,expected", [
    ("en", "Login service unavailable, try again in a minute."),
    ("de", "Anmeldedienst nicht erreichbar, versuch es in einer Minute noch einmal.")])
def test_login_outage_is_never_cached(client, world, language_, expected):
    world.pb_down = True
    answer = client.get(BASE + "/vault", headers={**APP, "Accept-Language": language_})
    assert (answer.status_code, answer.json()) == (503, {"error": expected})
    world.pb_down = False
    assert client.get(BASE + "/vault", headers=APP).status_code == 200


def test_login_answers_are_cached_per_token(client, world):
    for _ in range(3):
        assert client.get(BASE + "/vault", headers=APP).status_code == 200
    assert world.pb_calls == 1
    world.clock.advance(seconds=61)
    client.get(BASE + "/vault", headers=APP)
    assert world.pb_calls == 2


def test_bad_request_in_both_languages(client):
    for language_, expected in (("en", "Bad request."), ("de", "Ungültige Anfrage.")):
        answer = client.post(BASE + "/edits", content=b"{not json", headers={**APP, "Accept-Language": language_,
                                                                             "Content-Type": "application/json"})
        assert (answer.status_code, answer.json()) == (400, {"error": expected})


@pytest.mark.parametrize("body,key", [
    ({"op": "confirm_position", "position": "Printing press#9"}, "position_gone"),
    ({"op": "confirm_position", "position": "Nowhere#1"}, "unknown_position"),
    ({"op": "add_position", "note": "Spread of print", "text": "X.", "evidence": []}, "not_position_note"),
    ({"op": "add_position", "note": "Printing press", "text": "X.", "evidence": ["Nowhere"]}, "unknown_evidence"),
    ({"op": "reword_position", "position": "Printing press#1", "text": ""}, "empty_text"),
    ({"op": "reword_position", "position": "Printing press#1", "text": "a\nb"}, "position_one_line"),
    ({"op": "drop_position", "position": "Printing press#1", "why": ""}, "empty_why"),
    ({"op": "set_confidence", "note": "Martin Luther", "confidence": "solid"}, "no_confidence"),
    ({"op": "dismiss_callout", "note": "Printing press", "callout": 0, "version": "x"}, "note_changed"),
])
def test_edit_errors_in_german(client, body, key):
    answer = client.post(BASE + "/edits", json=body, headers={**APP, "Accept-Language": "de"})
    values = {"note": "Nowhere"} if key == "unknown_evidence" else {}
    assert answer.json()["error"] == text(key, **values).de
    assert answer.headers["Content-Language"] == "de"


def test_every_text_has_both_languages():
    for key, (en, de) in TEXTS.items():
        assert en.strip() and de.strip() and en != de, key


def test_etag_and_304(client, service):
    first = client.get(BASE + "/vault", headers=APP)
    etag = first.headers["ETag"]
    assert etag == f'"{service.repo.head(short=True)}-{INDEX_SHAPE}"'
    for header in (etag, f"W/{etag}", f'"other", {etag}', "*"):
        again = client.get(BASE + "/vault", headers={**APP, "If-None-Match": header})
        assert (again.status_code, again.content, again.headers["ETag"]) == (304, b"", etag)
    assert client.get(BASE + "/vault", headers={**APP, "If-None-Match": '"old"'}).status_code == 200
    edited = client.post(BASE + "/edits", json={"op": "confirm_position", "position": "Printing press#2"}, headers=APP)
    assert client.get(BASE + "/vault", headers={**APP, "If-None-Match": etag}).status_code == 200
    assert client.get(BASE + "/vault", headers=APP).headers["ETag"] == f'"{edited.json()["vault"]["commit"]}-{INDEX_SHAPE}"'


def test_health_needs_no_login(client, service):
    service.sync()
    health = client.get(BASE + "/health").json()
    assert health == {"ok": True, "commit": service.repo.head(short=True), "pulled": "2026-10-24T16:05:00Z",
                      "pushed": True, "notes": 13}


def test_health_turns_false_when_pulls_fail_for_ten_minutes(client, world, service):
    service.sync()
    world.remote.rename(world.remote.with_name("away.git"))
    service.sync()
    assert client.get(BASE + "/health").json()["ok"] is True
    world.clock.advance(minutes=11)
    service.sync()
    health = client.get(BASE + "/health").json()
    assert (health["ok"], health["pulled"]) == (False, "2026-10-24T16:05:00Z")


def test_not_ready_without_a_vault(world):
    import shutil
    shutil.rmtree(world.vault)
    client = TestClient(create_app(world.service()))
    for language_ in ("en", "de"):
        answer = client.get(BASE + "/vault", headers={**APP, "Accept-Language": language_})
        assert (answer.status_code, answer.json()) == (503, {"error": text("not_ready").get(language_)})
    assert client.get(BASE + "/health").json() == {"ok": False, "commit": "", "pulled": None, "pushed": True,
                                                   "notes": 0}
