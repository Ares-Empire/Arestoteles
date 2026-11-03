"""Body routes share the login check and byte limit."""

import asyncio
import json
from collections import deque

import pytest
from fastapi import APIRouter, Body
from fastapi.routing import APIRoute

from arestoteles.api import BODY_LIMIT, PREFIX, create_app
from arestoteles.texts import text


def body_routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute) and route.body_field is not None:
            yield route
        elif hasattr(route, "original_router"):
            yield from body_routes(route.original_router)


def request_chunks(app, chunks, headers=(), path=PREFIX + "/edits"):
    pending = deque(chunks)
    received = []
    sent = []

    async def receive():
        if not pending:
            await asyncio.Event().wait()
        chunk = pending.popleft()
        received.append(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(pending)}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "headers": [(b"content-type", b"application/json"), *headers],
             "client": ("192.0.2.1", 1234), "server": ("test", 80)}
    asyncio.run(app(scope, receive, send))
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), json.loads(body), received


@pytest.mark.parametrize("token,status,key", [
    (b"", 401, "unauthenticated"), (b"unknown-token", 401, "unauthenticated"),
    (b"stranger-token", 403, "forbidden"), (b"patrik-token", 503, "login_unavailable"),
])
@pytest.mark.parametrize("length", [b"1", str(BODY_LIMIT + 1).encode()])
def test_login_precedes_any_body_read(service, world, token, status, key, length):
    world.pb_down = status == 503
    app = create_app(service)
    routes = list(body_routes(app))
    assert routes
    for route in routes:
        answer, headers, data, received = request_chunks(
            app, [b"{invalid", b"x" * (BODY_LIMIT + 1)],
            [(b"authorization", b"Bearer " + token), (b"accept-language", b"de"),
             (b"content-length", length)], path=route.path)
        assert answer == status
        assert data == {"error": text(key).de}
        assert headers[b"content-language"] == b"de"
        assert received == []


@pytest.mark.parametrize("length", [None, b"1", str(BODY_LIMIT + 1).encode(), b"9" * 5000])
@pytest.mark.parametrize("language", [b"en", b"de"])
def test_oversized_body_is_refused_before_parsing(service, monkeypatch, length, language):
    def unexpected_edit(payload):
        pytest.fail("An oversized request reached the edit service")

    monkeypatch.setattr(service, "edit", unexpected_edit)
    headers = [(b"authorization", b"Bearer patrik-token"), (b"accept-language", language)]
    if length is not None:
        headers.append((b"content-length", length))
    status, response_headers, body, received = request_chunks(
        create_app(service), [b"x" * BODY_LIMIT, b"x", b"unread"], headers)
    assert status == 413
    assert body == {"error": text("body_too_large").get(language.decode())}
    assert response_headers[b"content-language"] == language
    assert len(received) == (2 if length in (None, b"1") else 0)


@pytest.mark.parametrize("length", [None, b"1"])
def test_owner_can_send_a_whole_note_at_the_byte_limit(client, service, length):
    source = client.get(PREFIX + "/notes/Spread of print/source",
                        headers={"Authorization": "Bearer patrik-token"}).json()
    payload = {"op": "edit_note", "note": source["id"], "version": source["version"], "markdown": source["markdown"]}
    body = json.dumps(payload).encode()
    body += b" " * (BODY_LIMIT - len(body))
    headers = [(b"authorization", b"Bearer patrik-token")]
    if length is not None:
        headers.append((b"content-length", length))
    status, _, data, received = request_chunks(create_app(service), [body[:100], body[100:]], headers)
    assert status == 200
    assert data["changed"] == []
    assert sum(map(len, received)) == BODY_LIMIT


def test_another_body_route_inherits_the_checks(service):
    app = create_app(service)
    route_type = type(next(body_routes(app)))
    router = APIRouter(route_class=route_type)

    @router.post("/another-body")
    def another_body(payload: dict = Body(...)):
        return payload

    app.include_router(router)
    status, _, _, received = request_chunks(app, [b"{}"], path="/another-body")
    assert (status, received) == (401, [])
    status, _, _, _ = request_chunks(app, [b"x" * (BODY_LIMIT + 1)],
                                     [(b"authorization", b"Bearer patrik-token")], path="/another-body")
    assert status == 413
