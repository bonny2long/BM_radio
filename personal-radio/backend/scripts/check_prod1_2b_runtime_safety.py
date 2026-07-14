from __future__ import annotations

from pathlib import Path
import asyncio
import os
import sys
from contextlib import contextmanager
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from app.config import Settings
from app.runtime_security import CORS_ALLOWED_HEADERS, CORS_ALLOWED_METHODS, configure_cors, fastapi_docs_config, validate_runtime_safety

class Response:
    def __init__(self, status_code: int, headers: dict[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.body = body


def request(app: FastAPI, method: str, path: str, headers: dict[str, str] | None = None) -> Response:
    async def run_request() -> Response:
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
        body = b"".join(event.get("body", b"") for event in events if event["type"] == "http.response.body")
        response_headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in start.get("headers", [])
        }
        return Response(int(start["status"]), response_headers, body)

    return asyncio.run(run_request())

CONFIG_ENV_NAMES = (
    "BM_RADIO_API_DOCS_ENABLED",
    "BM_RADIO_CORS_ORIGINS",
    "PUBLIC_ACCESS",
    "ALLOW_FILE_MUTATION",
    "ALLOW_DELETE",
    "ALLOW_TAG_WRITES",
    "SCAN_INGEST_FOLDERS",
    "BM_RADIO_API_HOST",
)


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


def make_settings(**values: object) -> Settings:
    with isolated_env():
        return Settings(_env_file=None, **values)


def make_test_app(settings: Settings) -> FastAPI:
    app = FastAPI(**fastapi_docs_config(settings))

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    configure_cors(app, settings)
    return app


def assert_settings_fails(**values: object) -> None:
    try:
        make_settings(**values)
    except ValueError as exc:
        assert str(exc), "validation error should include a message"
        return
    raise AssertionError(f"expected settings failure for {values}")


def case_a_docs_disabled_by_default() -> None:
    app = make_test_app(make_settings())
    assert request(app, "GET", "/docs").status_code == 404
    assert request(app, "GET", "/redoc").status_code == 404
    assert request(app, "GET", "/openapi.json").status_code == 404


def case_b_docs_explicit_opt_in() -> None:
    app = make_test_app(make_settings(BM_RADIO_API_DOCS_ENABLED=True))
    assert request(app, "GET", "/docs").status_code == 200
    assert request(app, "GET", "/openapi.json").status_code == 200


def case_c_configured_origin_allowed() -> None:
    app = make_test_app(make_settings(BM_RADIO_CORS_ORIGINS=["http://localhost:5174"]))
    response = request(
        app,
        "OPTIONS",
        "/ping",
        headers={"Origin": "http://localhost:5174", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5174", response.headers
    assert response.headers.get("access-control-allow-credentials") != "true", response.headers
    methods = response.headers.get("access-control-allow-methods", "")
    for method in CORS_ALLOWED_METHODS:
        assert method in methods, methods
    headers = response.headers.get("access-control-allow-headers", "")
    for header in CORS_ALLOWED_HEADERS:
        assert header.lower() in headers.lower(), headers


def case_d_unconfigured_origin_rejected() -> None:
    app = make_test_app(make_settings(BM_RADIO_CORS_ORIGINS=["http://localhost:5174"]))
    response = request(
        app,
        "OPTIONS",
        "/ping",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") is None, response.headers


def case_e_wildcard_origin_blocked() -> None:
    assert_settings_fails(BM_RADIO_CORS_ORIGINS=["*"])
    assert_settings_fails(BM_RADIO_CORS_ORIGINS=["https://*.example.com"])


def case_f_malformed_origins_blocked() -> None:
    for origin in (
        "null",
        "ftp://example.com",
        "https://example.com/path",
        "https://example.com?x=1",
        "https://example.com#fragment",
        "",
    ):
        assert_settings_fails(BM_RADIO_CORS_ORIGINS=[origin])


def case_g_valid_private_origins_accepted() -> None:
    resolved = make_settings(BM_RADIO_CORS_ORIGINS=["http://127.0.0.1:5174", "http://localhost:5174", "https://example-name.ts.net"])
    assert resolved.BM_RADIO_CORS_ORIGINS == ["http://127.0.0.1:5174", "http://localhost:5174", "https://example-name.ts.net"]


def case_h_unsafe_runtime_flags_fail_closed() -> None:
    expected = {
        "PUBLIC_ACCESS": "PUBLIC_ACCESS",
        "ALLOW_FILE_MUTATION": "ALLOW_FILE_MUTATION",
        "ALLOW_DELETE": "ALLOW_DELETE",
        "ALLOW_TAG_WRITES": "ALLOW_TAG_WRITES",
        "SCAN_INGEST_FOLDERS": "SCAN_INGEST_FOLDERS",
    }
    for name, token in expected.items():
        settings = make_settings(**{name: True})
        try:
            validate_runtime_safety(settings)
        except RuntimeError as exc:
            assert token in str(exc), str(exc)
            continue
        raise AssertionError(f"expected runtime safety failure for {name}")


def case_i_container_bind_allowed_when_private() -> None:
    settings = make_settings(BM_RADIO_API_HOST="0.0.0.0")
    validate_runtime_safety(settings)
    assert settings.BM_RADIO_API_HOST == "0.0.0.0"


def case_j_cors_helper_uses_configured_origins() -> None:
    settings = make_settings(BM_RADIO_CORS_ORIGINS=["https://example-name.ts.net"])
    app = make_test_app(settings)
    allowed = request(
        app,
        "OPTIONS",
        "/ping",
        headers={"Origin": "https://example-name.ts.net", "Access-Control-Request-Method": "GET"},
    )
    blocked = request(
        app,
        "OPTIONS",
        "/ping",
        headers={"Origin": "http://localhost:5174", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "https://example-name.ts.net", allowed.headers
    assert blocked.headers.get("access-control-allow-origin") is None, blocked.headers


def main() -> None:
    case_a_docs_disabled_by_default()
    case_b_docs_explicit_opt_in()
    case_c_configured_origin_allowed()
    case_d_unconfigured_origin_rejected()
    case_e_wildcard_origin_blocked()
    case_f_malformed_origins_blocked()
    case_g_valid_private_origins_accepted()
    case_h_unsafe_runtime_flags_fail_closed()
    case_i_container_bind_allowed_when_private()
    case_j_cors_helper_uses_configured_origins()
    print("PASS: BM-PROD1.2B runtime safety")


if __name__ == "__main__":
    main()