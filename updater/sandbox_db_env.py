"""Pure, offline environment builder for FieldWork's isolated test containers.

It does not run pytest, create containers, open a database, alter the process
environment or bypass the application's database safety guard. A future
sandbox runner can use this to avoid injecting DATABASE_URL incorrectly.
"""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit, unquote


class TestEnvironmentDenied(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise TestEnvironmentDenied(code)


def build_isolated_test_env(source: Mapping[str, str]) -> dict[str, str]:
    """Return a *copy* with a dedicated test URL and no generic DB URL.

    The existing FieldWork configure_test_database() must still validate the
    result. Never use this for production, host execution, or a general shell.
    """
    require(source.get("FIELDWORK_TESTING") == "1", "TEST_MODE_REQUIRED")
    url = source.get("TEST_DATABASE_URL")
    require(type(url) is str and 0 < len(url) <= 2048, "TEST_URL_REQUIRED")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        db_name = unquote(parsed.path)
    except (ValueError, AttributeError) as exc:
        raise TestEnvironmentDenied("TEST_URL_INVALID") from exc
    require(parsed.scheme in ("postgresql", "postgresql+psycopg",
                              "postgresql+psycopg2", "postgres"),
            "TEST_DRIVER_DENIED")
    require(parsed.hostname == "test-db" and port in (None, 5432)
            and db_name == "/fieldwork_test" and not parsed.fragment,
            "TEST_DATABASE_TARGET_DENIED")
    # Keep credentials opaque. Do not log, print or interpolate the URL.
    result = dict(source)
    result.pop("DATABASE_URL", None)
    result["FIELDWORK_TEST_DATABASE_URL"] = url
    return result
