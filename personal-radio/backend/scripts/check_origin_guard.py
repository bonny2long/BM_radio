from __future__ import annotations

from pathlib import Path
import asyncio
import os
import sys
from contextlib import contextmanager
from typing import Iterator

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi import FastAPI
from app.config import Settings
from app.runtime_security import configure_cors, configure_origin_guard

CONFIG_ENV_NAMES = ("BM_RADIO_CORS_ORIGINS",)
LAN_ORIGIN = "http://192.168.1.50:5174"
LISTED = ["http://127.0.0.1:5174", "http://localhost:5174", LAN_ORIGIN]


def request(app: FastAPI, method: str, path: str, headers: dict[str, str] | None = None) -> int:
    async def run_request() -> int:
        sent_request = False
        events: list[dict[str, object]] = []
        raw_headers = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()]
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": raw_headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }

        async def receive() -> dict[str, object]:
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            events.append(message)

        await app(scope, receive, send)
        start = next(event for event in events if event["type"] == "http.response.start")
        return int(start["status"])

    return asyncio.run(run_request())


@contextmanager
def isolated_env() -> Iterator[None]:
    original = {name: os.environ.get(name) for name in CONFIG_ENV_NAMES}
    try:
        for name in CONFIG_ENV_NAMES:
            os.environ.pop(name, None)
        yield
    finally:
        for name in CONFIG_ENV_NAMES:
            os.environ.pop(name, None)
        for name, value in original.items():
            if value is not None:
                os.environ[name] = value


def make_app(origins: list[str]) -> tuple[FastAPI, dict[str, int]]:
    with isolated_env():
        settings = Settings(_env_file=None, BM_RADIO_CORS_ORIGINS=origins)
    hits = {"count": 0}
    app = FastAPI()

    def handler() -> dict[str, str]:
        hits["count"] += 1
        return {"ok": "yes"}

    app.add_api_route("/api/thing", handler, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    configure_origin_guard(app, settings)
    configure_cors(app, settings)
    return app, hits


def case_a_foreign_page_cannot_change_anything() -> None:
    app, hits = make_app(LISTED)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert request(app, method, "/api/thing", {"Origin": "https://evil.example"}) == 403, method
    assert request(app, "POST", "/api/thing", {"Origin": "null"}) == 403
    assert request(app, "POST", "/api/thing", {"Sec-Fetch-Site": "cross-site"}) == 403
    assert hits["count"] == 0, "a refused request must never reach the route"


def case_b_listed_origins_and_plain_clients_work() -> None:
    app, hits = make_app(LISTED)
    for origin in LISTED:
        assert request(app, "POST", "/api/thing", {"Origin": origin}) == 200, origin
    assert request(app, "POST", "/api/thing") == 200
    assert request(app, "POST", "/api/thing", {"Origin": "HTTP://LOCALHOST:5174/"}) == 200
    assert hits["count"] == 5


def case_c_reads_are_never_blocked() -> None:
    app, hits = make_app(LISTED)
    assert request(app, "GET", "/api/thing", {"Origin": "https://evil.example"}) == 200
    assert hits["count"] == 1


def case_d_allowlist_is_exact_not_any_loopback() -> None:
    app, _ = make_app(LISTED)
    assert request(app, "POST", "/api/thing", {"Origin": "http://127.0.0.1:9999"}) == 403
    assert request(app, "POST", "/api/thing", {"Origin": "http://192.168.1.51:5174"}) == 403
    assert request(app, "POST", "/api/thing", {"Origin": "http://127.0.0.1.evil.example:5174"}) == 403


def case_e_no_configured_origins_falls_back_to_loopback() -> None:
    app, _ = make_app([])
    assert request(app, "POST", "/api/thing", {"Origin": "http://127.0.0.1:5174"}) == 200
    assert request(app, "POST", "/api/thing", {"Origin": "https://evil.example"}) == 403


def case_f_real_app_installs_the_guard_before_cors() -> None:
    source = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    guard = source.index("configure_origin_guard(app, settings)")
    cors = source.index("configure_cors(app, settings)")
    assert guard < cors


def main() -> int:
    cases = [
        case_a_foreign_page_cannot_change_anything,
        case_b_listed_origins_and_plain_clients_work,
        case_c_reads_are_never_blocked,
        case_d_allowlist_is_exact_not_any_loopback,
        case_e_no_configured_origins_falls_back_to_loopback,
        case_f_real_app_installs_the_guard_before_cors,
    ]
    for case in cases:
        case()
        print(f"PASS {case.__name__}")
    print("origin guard checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
