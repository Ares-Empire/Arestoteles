"""A made-up world for the tests: the fixture vault in a temporary git repo with a bare "GitHub" remote, a second
clone as "the laptop", a fake PocketBase and a fixed clock. Nothing real is contacted."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from arestoteles.api import create_app
from arestoteles.auth import EmpireAuth
from arestoteles.config import Settings
from arestoteles.service import VaultService

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "vault"
SAMPLES = ROOT / "docs" / "samples"
START = datetime(2026, 10, 24, 16, 5, tzinfo=UTC)   # 18:05 in Berlin
APP = {"Authorization": "Bearer patrik-token"}
TEST_IDENTITY = ["-c", "user.name=Test Laptop", "-c", "user.email=laptop@example.com"]


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", *TEST_IDENTITY, "-C", str(cwd), *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr}")
    return done


class Clock:
    def __init__(self, start: datetime = START):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.clock = Clock()
        self.remote = tmp / "github.git"
        self.vault = tmp / "vault"        # the server's clone
        self.laptop = tmp / "laptop"      # another machine pushing to the same remote
        seed = tmp / "seed"
        shutil.copytree(FIXTURE, seed)
        git(tmp, "init", "--quiet", "--bare", "-b", "main", str(self.remote))
        git(seed, "init", "--quiet", "-b", "main")
        git(seed, "add", "-A")
        git(seed, "commit", "--quiet", "-m", "A made-up vault")
        git(seed, "remote", "add", "origin", str(self.remote))
        git(seed, "push", "--quiet", "origin", "main")
        git(tmp, "clone", "--quiet", str(self.remote), str(self.vault))
        git(tmp, "clone", "--quiet", str(self.remote), str(self.laptop))
        self.pb_records: dict[str, dict] = {
            "patrik-token": {"id": "userone00000001", "approved": True, "services": ["empire", "arestoteles"]},
            "other-token": {"id": "usertwo00000002", "approved": True, "services": ["empire"]},
        }
        self.pb_calls = 0
        self.pb_down = False

    def pocketbase(self, request: httpx.Request) -> httpx.Response:
        self.pb_calls += 1
        if self.pb_down:
            raise httpx.ConnectError("refused", request=request)
        record = self.pb_records.get(request.headers.get("Authorization", ""))
        if record is None:
            return httpx.Response(401, json={"message": "invalid token"})
        return httpx.Response(200, json={"token": "renewed", "record": record})

    def settings(self, **overrides) -> Settings:
        return Settings(vault=self.vault, sync_interval=3600, **overrides)

    def service(self, **overrides) -> VaultService:
        auth = EmpireAuth("http://pocketbase.test", httpx.Client(transport=httpx.MockTransport(self.pocketbase)),
                          clock=lambda: self.clock().timestamp())
        service = VaultService(self.settings(**overrides), auth, clock=self.clock)
        service.rebuild()
        return service

    # ── the laptop ──
    def laptop_commit(self, path: str, change, message: str = "Laptop edit") -> None:
        git(self.laptop, "pull", "--quiet", "--rebase")
        file = self.laptop / path
        file.write_text(change(file.read_text(encoding="utf-8")), encoding="utf-8")
        git(self.laptop, "commit", "--quiet", "-am", message)
        git(self.laptop, "push", "--quiet")

    def remote_file(self, path: str) -> str:
        return git(self.remote, "show", f"main:{path}").stdout

    def remote_log(self, n: int = 5) -> list[str]:
        return git(self.remote, "log", f"-{n}", "--format=%an <%ae>|%s", "main").stdout.splitlines()


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


@pytest.fixture
def service(world: World) -> VaultService:
    return world.service()


@pytest.fixture
def client(service: VaultService) -> TestClient:
    return TestClient(create_app(service))


def edit(client: TestClient, language: str = "en", **body) -> httpx.Response:
    return client.post("/api/arestoteles/edits", json=body, headers={**APP, "Accept-Language": language})


def note(vault: dict, note_id: str) -> dict:
    return next(n for n in vault["notes"] if n["id"] == note_id)


def position(vault: dict, position_id: str) -> dict:
    return next(p for g in vault["positions"] for p in g["positions"] if p["id"] == position_id)
