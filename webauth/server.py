#!/usr/bin/env python3
"""Arestoteles web server — static files for the portal, gated by a single-password
login with a stateless, HMAC-signed session cookie.

Ports the Aresium auth scheme (scrypt password hashing + HMAC-SHA256 signed cookie,
docs/09 "own custom login now") to Python with ZERO third-party deps — stdlib
hashlib.scrypt + hmac + http.server only.

Config (env, from .env — never committed):
  AUTH_PASSWORD_HASH   scrypt hash, format `scrypt:<salthex>:<dkhex>` (set via gen_password.py)
  AUTH_SESSION_SECRET  random secret used to sign session cookies

Fail-safe: the gate is ACTIVE only when BOTH are present. If either is unset the
server logs a loud warning and serves the site open — so a bad deploy can't lock
you out before the secrets are in place.

Serves /srv/web on :8080 (behind insureai_nginx, which terminates TLS).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from base64 import urlsafe_b64decode, urlsafe_b64encode
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from time import time
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

WEB_ROOT = os.environ.get("WEB_ROOT", "/srv/web")
PORT = int(os.environ.get("PORT", "8080"))
COOKIE_NAME = "arestoteles_session"
SESSION_SECS = 30 * 24 * 60 * 60  # 30 days

HASH = os.environ.get("AUTH_PASSWORD_HASH", "")
SECRET = os.environ.get("AUTH_SESSION_SECRET", "").encode()

# ── Empire SSO (verifier) ────────────────────────────────────────────────────
# Accept a short-lived, HMAC-signed token minted by the Ares Empire hub (shared SSO_SECRET)
# and bound to this province (audience), and start a normal session from it — no re-login.
SSO_SECRET = os.environ.get("SSO_SECRET", "").encode()
SSO_AUD = "arestoteles"

# scrypt params (must match gen_password.py)
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN, SCRYPT_MAXMEM = 16384, 8, 1, 32, 64 * 1024 * 1024

# Reachable without a session: the login flow and what the login page shows (its image, its fonts, which are served
# from here, not a font service). Exact paths only. Prefix matching ("/brand/") let "/brand/../index.html" past the
# login (2026-10-22).
OPEN_PATHS = frozenset({"/login", "/logout", "/favicon.ico", "/brand/aristotle-bust-login.webp",
                        "/fonts/fonts.css", "/fonts/SpaceGrotesk-Variable.ttf", "/fonts/JetBrainsMono-Variable.ttf"})


def auth_enabled() -> bool:
    return len(HASH) > 0 and len(SECRET) > 0


def verify_password(password: str) -> bool:
    # separator is ":" (not "$") so the hash survives docker-compose env_file,
    # which interpolates "$" sequences
    parts = HASH.split(":")
    if len(parts) != 3 or parts[0] != "scrypt":
        return False
    try:
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
        dk = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=len(expected),
            maxmem=SCRYPT_MAXMEM,
        )
    except Exception:
        return False
    return hmac.compare_digest(dk, expected)


def _sign(data: str) -> str:
    return (
        urlsafe_b64encode(hmac.new(SECRET, data.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )


def make_session_cookie() -> str:
    payload = (
        urlsafe_b64encode(json.dumps({"exp": int(time()) + SESSION_SECS}).encode())
        .decode()
        .rstrip("=")
    )
    token = f"{payload}.{_sign(payload)}"
    return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={SESSION_SECS}"


def clear_cookie() -> str:
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"


def _b64pad(s: str) -> bytes:
    return urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sso_sign(payload: str) -> str:
    return (
        urlsafe_b64encode(hmac.new(SSO_SECRET, payload.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )


def verify_sso(token: str | None) -> bool:
    """True if `token` is a valid, unexpired empire SSO token addressed to this province."""
    if not SSO_SECRET or not token or "." not in token:
        return False
    payload, _, sig = token.rpartition(".")
    if not hmac.compare_digest(sig, _sso_sign(payload)):
        return False
    try:
        data = json.loads(_b64pad(payload).decode())
    except Exception:
        return False
    return data.get("aud") == SSO_AUD and isinstance(data.get("exp"), int) and time() < data["exp"]


def has_valid_session(cookie_header: str | None) -> bool:
    if not auth_enabled():
        return True  # gate disabled → open
    if not cookie_header:
        return False
    entry = next(
        (c.strip() for c in cookie_header.split(";") if c.strip().startswith(COOKIE_NAME + "=")),
        None,
    )
    if not entry:
        return False
    token = entry[len(COOKIE_NAME) + 1 :]
    dot = token.rfind(".")
    if dot < 1:
        return False
    payload, sig = token[:dot], token[dot + 1 :]
    if not hmac.compare_digest(sig, _sign(payload)):
        return False
    try:
        exp = json.loads(_b64pad(payload).decode()).get("exp")
        return isinstance(exp, int) and time() < exp
    except Exception:
        return False


def login_page(error: str = "") -> bytes:
    err = f'<p class="err">{error}</p>' if error else ""
    html = f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<title>Arestoteles — Sign in</title>
<link rel="stylesheet" href="/fonts/fonts.css" />
<style>
  :root {{ color-scheme: dark; --mono: "JetBrains Mono", ui-monospace, monospace; --sans: "Space Grotesk", system-ui, sans-serif; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; min-height: 100dvh; display: grid; place-items: center;
    font-family: var(--sans); color: #f6f7fb; background: #050507; overflow: hidden;
  }}
  body::before {{ content:""; position: fixed; inset: 0; pointer-events: none;
    background: radial-gradient(60% 42% at 50% 16%, rgba(255,255,255,0.05), transparent 60%); }}
  .card {{
    position: relative; width: min(92vw, 372px); padding: 38px 32px 30px; text-align: center;
    border: 1px solid transparent; border-radius: 18px;
    background: linear-gradient(rgba(15,16,21,0.62), rgba(15,16,21,0.62)) padding-box,
      linear-gradient(135deg, rgba(255,255,255,0.24), rgba(255,255,255,0.04) 36%, rgba(255,255,255,0.03)) border-box;
    backdrop-filter: blur(26px) saturate(150%); -webkit-backdrop-filter: blur(26px) saturate(150%);
    box-shadow: 0 30px 70px -26px rgba(0,0,0,0.92), inset 0 1px 0 rgba(255,255,255,0.10);
  }}
  .bust {{ width: 92px; height: 92px; object-fit: contain; margin: 0 auto 14px; display: block;
    filter: drop-shadow(0 14px 30px rgba(0,0,0,0.6)); }}
  .word {{ font-weight: 700; font-size: 15px; letter-spacing: 0.34em; text-indent: 0.34em;
    color: #f4f5f9; margin: 0 0 4px; }}
  .sub {{ margin: 0 0 24px; font-size: 12.5px; color: #6b7280; font-family: var(--mono); letter-spacing: -0.01em; }}
  form {{ display: flex; flex-direction: column; gap: 11px; }}
  input[type=password] {{
    height: 48px; padding: 0 16px; font-size: 15px; color: #f6f7fb; font-family: var(--mono);
    letter-spacing: 0.04em; text-align: center;
    border: 1px solid rgba(255,255,255,0.12); border-radius: 12px;
    background: rgba(255,255,255,0.04); outline: none; transition: border-color .18s, background .18s;
  }}
  input[type=password]:focus {{ border-color: rgba(244,245,249,0.5); background: rgba(255,255,255,0.06); }}
  button {{
    height: 48px; font-size: 14px; font-weight: 650; letter-spacing: 0.02em; color: #07080a; cursor: pointer;
    border: none; border-radius: 12px; font-family: var(--sans);
    background: linear-gradient(180deg, #fbfbfd, #cfd2da);
    box-shadow: 0 10px 26px -8px rgba(255,255,255,0.18); transition: filter .18s, transform .06s;
  }}
  button:hover {{ filter: brightness(1.04); }}
  button:active {{ transform: translateY(1px); }}
  .err {{ margin: 0 0 14px; padding: 9px 12px; font-size: 12.5px; color: #ffd7dc; font-family: var(--mono);
    border-radius: 11px; background: rgba(255,45,75,0.14); border: 1px solid rgba(255,45,75,0.4); }}
  .foot {{ margin: 20px 0 0; font-size: 11px; color: #4b515c; font-family: var(--mono); letter-spacing: 0.02em; }}
</style>
</head>
<body>
  <main class="card">
    <img class="bust" src="/brand/aristotle-bust-login.webp" alt="Arestoteles" />
    <p class="word">ARESTOTELES</p>
    <p class="sub">Enter the access key to continue</p>
    {err}
    <form method="POST" action="/login" autocomplete="off">
      <input type="password" name="password" placeholder="Access key" aria-label="Access key" autofocus required />
      <button type="submit">Enter</button>
    </form>
    <p class="foot">Paper portfolio</p>
  </main>
</body>
</html>"""
    return html.encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    # the slim container has no system MIME table, so name the types the site uses
    extensions_map: ClassVar[dict[str, str]] = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".ttf": "font/ttf",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_ROOT, **kwargs)

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    # --- helpers ---
    def _redirect(self, location: str, cookie: str | None = None) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_html(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authed(self) -> bool:
        return has_valid_session(self.headers.get("Cookie"))

    def _is_open(self, path: str) -> bool:
        return path in OPEN_PATHS

    # --- routes ---
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/login":
            if self._authed():
                return self._redirect("/")
            return self._send_html(login_page())
        if path == "/logout":
            return self._redirect("/login", cookie=clear_cookie())
        if path == "/sso":
            # empire hand-off: a valid token starts a session without a second login
            token = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
            if verify_sso(token):
                return self._redirect("/", cookie=make_session_cookie())
            return self._redirect("/login")
        if not self._authed() and not self._is_open(path):
            return self._redirect("/login")
        return super().do_GET()

    def do_HEAD(self):
        path = urlparse(self.path).path
        if not self._authed() and not self._is_open(path) and path not in ("/login", "/logout"):
            return self._redirect("/login")
        return super().do_HEAD()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/login":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        password = (parse_qs(body).get("password") or [""])[0]
        if auth_enabled() and verify_password(password):
            return self._redirect("/", cookie=make_session_cookie())
        return self._send_html(login_page("Incorrect access key."), status=HTTPStatus.UNAUTHORIZED)


def main() -> None:
    if not auth_enabled():
        sys.stderr.write(
            "!! WARNING: AUTH_PASSWORD_HASH / AUTH_SESSION_SECRET not set — serving OPEN (no login gate)\n"
        )
    else:
        sys.stderr.write("Arestoteles web: login gate ACTIVE\n")
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    sys.stderr.write(f"Arestoteles web serving {WEB_ROOT} on :{PORT}\n")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
