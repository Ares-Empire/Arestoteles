"""The website's login, using in-memory HTTP connections."""

import hashlib
import importlib.util
import io
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.client import parse_headers
from pathlib import Path
from threading import Event, Lock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("webauth_server", ROOT / "webauth" / "server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class MemoryConnection:
    def __init__(self, chunks, clock=None, interval=0):
        self.chunks = deque(chunks)
        self.output = bytearray()
        self.timeout = None
        self.clock = clock
        self.interval = interval
        self.reads = 0

    def makefile(self, mode, buffering):
        return io.BytesIO()

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv_into(self, buffer):
        self.reads += 1
        if self.clock is not None:
            if self.interval >= self.timeout:
                self.clock.now += self.timeout
                raise TimeoutError()
            self.clock.now += self.interval
        if not self.chunks:
            return 0
        chunk = self.chunks.popleft()
        size = min(len(chunk), len(buffer))
        buffer[:size] = chunk[:size]
        if size < len(chunk):
            self.chunks.appendleft(chunk[size:])
        return size

    def sendall(self, data):
        self.output.extend(data)


def request(web, password="wrong", peer="192.0.2.1", headers=(), length=None, chunks=None, clock=None, interval=0):
    body = f"password={password}".encode()
    fields = [("Content-Length", str(len(body)) if length is None else length), *headers]
    head = b"POST /login HTTP/1.1\r\nHost: test\r\n"
    head += b"".join(f"{name}: {value}\r\n".encode() for name, value in fields if value is not False)
    head += b"\r\n"
    connection = MemoryConnection([head, *(chunks if chunks is not None else [body])], clock, interval)
    server.Handler(connection, (peer, 1234), web)
    response_head, response_body = bytes(connection.output).split(b"\r\n\r\n", 1)
    status_line, header_lines = response_head.split(b"\r\n", 1)
    response_headers = parse_headers(io.BytesIO(header_lines + b"\r\n\r\n"))
    return int(status_line.split()[1]), response_headers, response_body, connection


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setattr(server, "HASH", "scrypt:00:00")
    monkeypatch.setattr(server, "SECRET", b"made-up-session-secret")
    monkeypatch.setattr(server, "TRUSTED_PROXY", "172.18.0.1")
    monkeypatch.setattr(server.Handler, "log_message", lambda *args: None)
    with server.WebServer(("127.0.0.1", 0), server.Handler, bind_and_activate=False) as instance:
        yield instance


def test_owner_can_log_in_after_three_typos(web, monkeypatch):
    salt = b"made-up-test-salt"
    hashed = hashlib.scrypt(b"correct", salt=salt, n=server.SCRYPT_N, r=server.SCRYPT_R,
                            p=server.SCRYPT_P, dklen=server.SCRYPT_DKLEN, maxmem=server.SCRYPT_MAXMEM)
    monkeypatch.setattr(server, "HASH", f"scrypt:{salt.hex()}:{hashed.hex()}")
    for _ in range(3):
        status, _, body, _ = request(web)
        assert status == 401
        assert b"Incorrect access key." in body
    status, headers, _, _ = request(web, password="correct")
    assert status == 302
    assert headers["Location"] == "/"
    assert server.has_valid_session(headers["Set-Cookie"])


def test_address_limit_precedes_password_and_body(web, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "verify_password", lambda password: calls.append(password) or False)
    for _ in range(server.LOGIN_PER_ADDRESS):
        assert request(web)[0] == 401
    status, headers, body, connection = request(web, password="correct")
    assert status == 429
    assert headers["Retry-After"] == str(server.LOGIN_WINDOW)
    assert headers["Content-Language"] == "en"
    assert b"Too many sign-in attempts. Please try again shortly." in body
    assert len(calls) == server.LOGIN_PER_ADDRESS
    assert connection.reads == 1
    assert request(web, peer="192.0.2.2")[0] == 401


def test_global_limit_across_addresses_and_recovery(web, monkeypatch):
    clock = Clock()
    web.login_limits = server.LoginLimits(clock)
    calls = []
    monkeypatch.setattr(server, "verify_password", lambda password: calls.append(password) or password == "correct")
    for index in range(server.LOGIN_TOTAL):
        assert request(web, peer=f"192.0.2.{index + 1}")[0] == 401
    status, _, _, connection = request(web, password="correct", peer="198.51.100.1")
    assert status == 429
    assert len(calls) == server.LOGIN_TOTAL
    assert connection.reads == 1
    clock.now = server.LOGIN_WINDOW
    assert request(web, password="correct", peer="198.51.100.1")[0] == 302


def test_per_address_limit_expires(web, monkeypatch):
    clock = Clock()
    web.login_limits = server.LoginLimits(clock)
    monkeypatch.setattr(server, "verify_password", lambda password: password == "correct")
    for _ in range(server.LOGIN_PER_ADDRESS):
        assert request(web)[0] == 401
    clock.now = server.LOGIN_WINDOW - 0.1
    assert request(web, password="correct")[0] == 429
    clock.now = server.LOGIN_WINDOW
    assert request(web, password="correct")[0] == 302


def test_rate_reservations_are_atomic_and_bounded():
    clock = Clock()
    limits = server.LoginLimits(clock)
    with ThreadPoolExecutor(max_workers=16) as pool:
        allowed = list(pool.map(lambda _: limits.allow("192.0.2.1"), range(100)))
    assert sum(allowed) == server.LOGIN_PER_ADDRESS
    for index in range(1000):
        limits.allow(str(index))
    assert len(limits.attempts) == server.LOGIN_TOTAL
    clock.now = server.LOGIN_WINDOW
    assert limits.allow("owner")
    assert len(limits.attempts) == 1


def test_only_two_password_checks_can_run_and_slots_recover(web, monkeypatch):
    entered = Event()
    release = Event()
    lock = Lock()
    calls = []

    def verify(password):
        with lock:
            calls.append(password)
            if len(calls) == server.PASSWORD_CHECKS:
                entered.set()
        assert release.wait(timeout=5)
        return True

    monkeypatch.setattr(server, "verify_password", verify)
    with ThreadPoolExecutor(max_workers=server.PASSWORD_CHECKS) as pool:
        pending = [pool.submit(request, web, peer=f"192.0.2.{index}") for index in range(server.PASSWORD_CHECKS)]
        try:
            assert entered.wait(timeout=5)
            status, headers, _, _ = request(web, peer="198.51.100.1")
            assert status == 429
            assert headers["Retry-After"] == "1"
            assert len(calls) == server.PASSWORD_CHECKS
        finally:
            release.set()
        assert all(result.result()[0] == 302 for result in pending)
    assert request(web, password="correct")[0] == 302


def test_password_slot_is_released_on_error(web, monkeypatch):
    def broken(password):
        raise RuntimeError("test password checker")

    monkeypatch.setattr(server, "verify_password", broken)
    with pytest.raises(RuntimeError):
        request(web)
    assert web.password_slots.acquire(blocking=False)
    assert web.password_slots.acquire(blocking=False)
    assert not web.password_slots.acquire(blocking=False)
    web.password_slots.release()
    web.password_slots.release()


@pytest.mark.parametrize("peer,forwarded,expected", [
    ("172.18.0.1", "192.0.2.1", "192.0.2.1"),
    ("172.18.0.1", "203.0.113.1, 192.0.2.1", "192.0.2.1"),
    ("172.18.0.1", "2001:0db8::1", "2001:db8::1"),
    ("172.18.0.1", "invalid", "172.18.0.1"),
    ("172.18.0.1", "", "172.18.0.1"),
    ("192.0.2.2", "203.0.113.1", "192.0.2.2"),
])
def test_forwarded_address_is_trusted_only_from_the_proxy(web, monkeypatch, peer, forwarded, expected):
    monkeypatch.setattr(server, "verify_password", lambda password: False)
    request(web, peer=peer, headers=[("X-Forwarded-For", forwarded)])
    assert web.login_limits.attempts[-1][1] == expected


def test_proxy_clients_have_separate_budgets(web, monkeypatch):
    monkeypatch.setattr(server, "verify_password", lambda password: password == "correct")
    for _ in range(server.LOGIN_PER_ADDRESS):
        assert request(web, peer="172.18.0.1", headers=[("X-Forwarded-For", "192.0.2.1")])[0] == 401
    assert request(web, peer="172.18.0.1", headers=[("X-Forwarded-For", "192.0.2.1")])[0] == 429
    assert request(web, password="correct", peer="172.18.0.1",
                   headers=[("X-Forwarded-For", "192.0.2.2")])[0] == 302


def test_an_untrusted_peer_cannot_change_its_budget(web, monkeypatch):
    monkeypatch.setattr(server, "verify_password", lambda password: False)
    for index in range(server.LOGIN_PER_ADDRESS):
        assert request(web, headers=[("X-Forwarded-For", f"203.0.113.{index}")])[0] == 401
    assert request(web, headers=[("X-Forwarded-For", "198.51.100.1")])[0] == 429


def test_login_body_at_the_limit_is_allowed(web, monkeypatch):
    monkeypatch.setattr(server, "verify_password", lambda password: password == "correct")
    body = b"password=correct&padding="
    body += b"x" * (server.LOGIN_BODY_LIMIT - len(body))
    assert request(web, length=str(len(body)), chunks=[body])[0] == 302


@pytest.mark.parametrize("length,headers,chunks,status", [
    (False, [], [], 411), ("-1", [], [], 400), ("invalid", [], [], 400),
    (str(server.LOGIN_BODY_LIMIT + 1), [], [], 413), ("9" * 100, [], [], 400),
    ("20", [("Content-Length", "20")], [], 400),
    ("20", [("Transfer-Encoding", "chunked")], [], 400),
    ("20", [], [b"short"], 400),
])
def test_invalid_login_bodies_do_not_check_passwords(web, monkeypatch, length, headers, chunks, status):
    def unexpected(password):
        pytest.fail("An invalid request reached the password checker")

    monkeypatch.setattr(server, "verify_password", unexpected)
    answer, _, _, connection = request(web, length=length, headers=headers, chunks=chunks)
    assert answer == status
    if status != 400 or chunks == []:
        assert connection.reads == 1


def test_slow_body_has_an_absolute_deadline(web, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(server, "monotonic", clock)
    calls = []
    monkeypatch.setattr(server, "verify_password", lambda password: calls.append(password) or False)
    status, _, body, connection = request(web, length="20", chunks=[b"x"] * 20, clock=clock, interval=2)
    assert status == 408
    assert b"Sign-in took too long. Please try again." in body
    assert clock.now == server.REQUEST_SECONDS
    assert connection.chunks
    assert calls == []


def test_headers_share_the_request_deadline(web, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(server, "monotonic", clock)
    connection = MemoryConnection([b"G", b"E", b"T", b" ", b"/"], clock, interval=2)
    server.Handler(connection, ("192.0.2.1", 1234), web)
    assert clock.now == server.REQUEST_SECONDS
    assert connection.chunks
    assert not web.login_limits.attempts


def test_web_container_resource_limits():
    web = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["web"]
    assert web["cpus"] == 0.5
    assert web["mem_limit"] == "128m"
    assert web["memswap_limit"] == "128m"
    assert web["pids_limit"] == 64
    assert web["environment"]["AUTH_TRUSTED_PROXY"] == "172.19.0.1"
