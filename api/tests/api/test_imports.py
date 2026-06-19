from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api import deps
from app.api.v1 import imports as imports_api


def _fake_parse_artifact(institution: str, filename: str):
    return SimpleNamespace(
        id=17,
        institution=institution,
        filename=filename,
        status="reviewed",
        parse_preview={"total_parsed": 1},
        error_msg=None,
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.fixture
def dummy_user():
    return SimpleNamespace(
        id=1,
        username="tester",
        totp_enabled=False,
        telegram_chat_id=None,
    )


@pytest.fixture
def override_auth(app, dummy_user):
    async def _override_user():
        return dummy_user

    app.dependency_overrides[deps.get_current_user] = _override_user
    yield
    app.dependency_overrides.pop(deps.get_current_user, None)
    app.dependency_overrides.pop(deps.get_db, None)


@pytest.mark.parametrize(
    "filename",
    [
        "statement.xlsx",
        "statement.html",
        "statement.mhtml",
        "statement.mht",
    ],
)
async def test_upload_accepts_supported_xtb_statement_extensions(
    async_client,
    app,
    monkeypatch,
    override_auth,
    filename,
):
    async def _override_db():
        yield SimpleNamespace()

    async def _fake_parse(file_bytes, uploaded_filename, session):
        assert file_bytes == b"fixture-bytes"
        assert uploaded_filename == filename
        assert session is not None
        return SimpleNamespace(
            id=17,
            status="reviewed",
            parse_preview={"total_parsed": 1},
            error_msg=None,
        )

    app.dependency_overrides[deps.get_db] = _override_db
    monkeypatch.setattr(imports_api, "parse_xtb_file", _fake_parse)

    response = await async_client.post(
        "/v1/imports/xtb",
        files={"file": (filename, b"fixture-bytes", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "artifact_id": 17,
        "status": "reviewed",
        "preview": {"total_parsed": 1},
        "error": None,
    }


async def test_upload_rejects_unsupported_xtb_statement_extensions(
    async_client,
    override_auth,
):
    response = await async_client.post(
        "/v1/imports/xtb",
        files={"file": ("statement.csv", b"id,type", "text/csv")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Only .xlsx, .html, .mhtml, and .mht files are supported"
    }


async def test_upload_rejects_oversized_xtb_statements(
    async_client,
    override_auth,
):
    response = await async_client.post(
        "/v1/imports/xtb",
        files={
            "file": (
                "statement.xlsx",
                b"x" * (imports_api.MAX_FILE_SIZE + 1),
                "application/octet-stream",
            )
        },
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "File too large (max 20 MB)"}


async def test_get_import_returns_ingestion_status(async_client, app, override_auth):
    artifact = SimpleNamespace(
        id=7,
        institution="xtb",
        filename="statement.mhtml",
        status="reviewed",
        parsed_count=292,
        committed_count=0,
        duplicate_count=4,
        parse_preview={"total_parsed": 292},
        error_msg=None,
        created_at=datetime(2026, 2, 3, 5, 24, 54, tzinfo=UTC),
        committed_at=None,
    )

    class _FakeSession:
        async def execute(self, _statement):
            return _ScalarResult(artifact)

    async def _override_db():
        yield _FakeSession()

    app.dependency_overrides[deps.get_db] = _override_db

    response = await async_client.get("/v1/imports/7")

    assert response.status_code == 200
    assert response.json() == {
        "id": 7,
        "institution": "xtb",
        "filename": "statement.mhtml",
        "status": "reviewed",
        "parsed_count": 292,
        "committed_count": 0,
        "duplicate_count": 4,
        "preview": {"total_parsed": 292},
        "error": None,
        "created_at": "2026-02-03T05:24:54+00:00",
        "committed_at": None,
    }


async def test_upload_accepts_binance_zip_exports(
    async_client, app, monkeypatch, override_auth
):
    async def _override_db():
        yield SimpleNamespace()

    async def _fake_parse(file_bytes, uploaded_filename, session):
        assert file_bytes == b"binance-zip"
        assert uploaded_filename == "binance-export.zip"
        assert session is not None
        return _fake_parse_artifact("binance", uploaded_filename)

    app.dependency_overrides[deps.get_db] = _override_db
    monkeypatch.setattr(imports_api, "parse_binance_file", _fake_parse)

    response = await async_client.post(
        "/v1/imports/binance",
        files={"file": ("binance-export.zip", b"binance-zip", "application/zip")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "artifact_id": 17,
        "status": "reviewed",
        "preview": {"total_parsed": 1},
        "error": None,
    }


async def test_upload_rejects_unsupported_binance_extensions(
    async_client, override_auth
):
    response = await async_client.post(
        "/v1/imports/binance",
        files={"file": ("binance-export.txt", b"bad", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Only .zip and .csv Binance exports are supported"
    }


async def test_upload_surfaces_binance_parser_errors_as_bad_request(
    async_client, app, monkeypatch, override_auth
):
    async def _override_db():
        yield SimpleNamespace()

    async def _fake_parse(_file_bytes, _uploaded_filename, _session):
        raise ValueError("No supported Binance export rows found")

    app.dependency_overrides[deps.get_db] = _override_db
    monkeypatch.setattr(imports_api, "parse_binance_file", _fake_parse)

    response = await async_client.post(
        "/v1/imports/binance",
        files={"file": ("binance-export.csv", b"foo,bar\n1,2\n", "text/csv")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "No supported Binance export rows found"}


async def test_upload_surfaces_empty_supported_binance_exports_as_bad_request(
    async_client, app, monkeypatch, override_auth
):
    async def _override_db():
        yield SimpleNamespace()

    async def _fake_parse(_file_bytes, _uploaded_filename, _session):
        raise ValueError("Binance export contained no importable rows")

    app.dependency_overrides[deps.get_db] = _override_db
    monkeypatch.setattr(imports_api, "parse_binance_file", _fake_parse)

    response = await async_client.post(
        "/v1/imports/binance",
        files={
            "file": (
                "binance-export.zip",
                b"empty-binance-zip",
                "application/zip",
            )
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Binance export contained no importable rows"}


async def test_upload_rejects_direct_binance_csv_without_timezone_marker(
    async_client, app, monkeypatch, override_auth
):
    async def _override_db():
        yield SimpleNamespace()

    async def _fake_parse(_file_bytes, _uploaded_filename, _session):
        raise ValueError(
            "Direct Binance CSV uploads must use the original Binance filename with timezone marker"
        )

    app.dependency_overrides[deps.get_db] = _override_db
    monkeypatch.setattr(imports_api, "parse_binance_file", _fake_parse)

    response = await async_client.post(
        "/v1/imports/binance",
        files={"file": ("export.csv", b"Time,Coin\n", "text/csv")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Direct Binance CSV uploads must use the original Binance filename with timezone marker"
    }
