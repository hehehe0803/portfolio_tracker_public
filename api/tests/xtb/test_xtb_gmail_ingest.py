from types import SimpleNamespace

import pytest
from app.services.xtb_gmail_ingest import (
    GmailAttachment,
    GmailMessage,
    XtbGmailIngestionConfig,
    ingest_xtb_gmail_attachments,
    xtb_gmail_attachment_filename,
)


class FakeGmailClient:
    def __init__(
        self,
        messages: list[GmailMessage],
        payloads: dict[tuple[str, str], bytes],
    ):
        self.messages = messages
        self.payloads = payloads
        self.searches: list[tuple[str, tuple[str, ...], int]] = []
        self.downloads: list[tuple[str, str]] = []

    async def search_messages(
        self, *, query: str, label_ids: list[str], max_results: int
    ) -> list[GmailMessage]:
        self.searches.append((query, tuple(label_ids), max_results))
        return self.messages

    async def download_attachment(
        self, *, message_id: str, attachment_id: str
    ) -> bytes:
        self.downloads.append((message_id, attachment_id))
        return self.payloads[(message_id, attachment_id)]


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, existing_artifact=None):
        self.existing_artifact = existing_artifact
        self.commits = 0

    async def execute(self, _statement):
        return ScalarResult(self.existing_artifact)

    async def commit(self):
        self.commits += 1


def xtb_message() -> GmailMessage:
    return GmailMessage(
        id="msg-1",
        thread_id="thread-1",
        from_email="dailystatements@mail.xtb.com",
        subject="Daily statement",
        internal_date_ms=1778544000000,
        attachments=[
            GmailAttachment(
                id="att-1",
                filename="statement.pdf",
                mime_type="application/pdf",
                size=1234,
            ),
            GmailAttachment(
                id="att-html",
                filename="tracking.html",
                mime_type="text/html",
                size=20,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_ingest_searches_serious_label_and_previews_xtb_pdf_attachment(
    monkeypatch,
):
    parsed_artifact = SimpleNamespace(
        id=77,
        status="reviewed",
        parse_preview={
            "total_parsed": 6,
            "sample": [
                {
                    "id": "2565559355",
                    "date": "2026-05-12 09:03:54",
                }
            ],
        },
        error_msg=None,
    )
    parse_calls = []

    async def fake_parse_xtb_file(file_bytes, filename, session, *, pdf_password=None):
        parse_calls.append((file_bytes, filename, session, pdf_password))
        return parsed_artifact

    monkeypatch.setattr(
        "app.services.xtb_gmail_ingest.parse_xtb_file",
        fake_parse_xtb_file,
    )
    client = FakeGmailClient([xtb_message()], {("msg-1", "att-1"): b"%PDF-fixture"})
    session = FakeSession()

    result = await ingest_xtb_gmail_attachments(
        client,
        session,
        password_provider=lambda: "pdf-password",
    )

    assert client.searches == [
        (
            (
                "from:dailystatements@mail.xtb.com has:attachment "
                "filename:pdf newer_than:1y"
            ),
            ("serious",),
            10,
        )
    ]
    assert client.downloads == [("msg-1", "att-1")]
    assert parse_calls == [
        (
            b"%PDF-fixture",
            "xtb-gmail-msg-1-att-1-ed41915c0959.pdf",
            session,
            "pdf-password",
        )
    ]
    assert result["searched"] == 1
    assert result["created"] == 1
    assert result["skipped"] == 0
    assert parsed_artifact.parse_preview["source"]["gmail_message_id"] == "msg-1"
    assert parsed_artifact.parse_preview["source"]["gmail_attachment_id"] == "att-1"
    assert parsed_artifact.parse_preview["source"]["pdf_sha256"].startswith("ed41915")
    assert parsed_artifact.parse_preview["source"]["statement_order_ids"] == [
        "2565559355"
    ]
    assert parsed_artifact.parse_preview["source"]["statement_dates"] == [
        "2026-05-12 09:03:54"
    ]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_ingest_skips_existing_gmail_attachment_without_download(monkeypatch):
    existing = SimpleNamespace(
        id=12,
        status="reviewed",
        filename=xtb_gmail_attachment_filename("msg-1", "att-1", "already-known"),
    )

    async def forbidden_parse(*_args, **_kwargs):
        raise AssertionError("duplicate attachments should not be parsed")

    monkeypatch.setattr(
        "app.services.xtb_gmail_ingest.parse_xtb_file",
        forbidden_parse,
    )
    client = FakeGmailClient([xtb_message()], {("msg-1", "att-1"): b"%PDF-fixture"})

    result = await ingest_xtb_gmail_attachments(
        client,
        FakeSession(existing_artifact=existing),
        password_provider=lambda: "pdf-password",
    )

    assert client.downloads == []
    assert result["created"] == 0
    assert result["skipped"] == 1
    assert result["items"] == [
        {
            "message_id": "msg-1",
            "attachment_id": "att-1",
            "status": "duplicate",
            "artifact_id": 12,
            "filename": existing.filename,
        }
    ]


@pytest.mark.asyncio
async def test_ingest_blocks_safely_when_pdf_password_is_missing(monkeypatch):
    async def forbidden_parse(*_args, **_kwargs):
        raise AssertionError("missing password should block before parsing")

    monkeypatch.setattr(
        "app.services.xtb_gmail_ingest.parse_xtb_file",
        forbidden_parse,
    )
    client = FakeGmailClient([xtb_message()], {("msg-1", "att-1"): b"%PDF-fixture"})

    result = await ingest_xtb_gmail_attachments(
        client,
        FakeSession(),
        password_provider=lambda: None,
    )

    assert client.downloads == []
    assert result["created"] == 0
    assert result["skipped"] == 1
    assert result["items"] == [
        {
            "message_id": "msg-1",
            "attachment_id": "att-1",
            "status": "password_missing",
            "reason": "XTB PDF password is not configured",
        }
    ]


@pytest.mark.asyncio
async def test_ingest_skips_attachment_when_preview_parse_fails(monkeypatch):
    async def failing_parse(*_args, **_kwargs):
        raise ValueError("unsupported XTB PDF format")

    monkeypatch.setattr(
        "app.services.xtb_gmail_ingest.parse_xtb_file",
        failing_parse,
    )
    client = FakeGmailClient([xtb_message()], {("msg-1", "att-1"): b"%PDF-fixture"})

    result = await ingest_xtb_gmail_attachments(
        client,
        FakeSession(),
        password_provider=lambda: "pdf-password",
    )

    assert client.downloads == [("msg-1", "att-1")]
    assert result["created"] == 0
    assert result["skipped"] == 1
    assert result["items"] == [
        {
            "message_id": "msg-1",
            "attachment_id": "att-1",
            "status": "parse_failed",
            "reason": "unsupported XTB PDF format",
        }
    ]


@pytest.mark.asyncio
async def test_ingest_skips_attachment_when_preview_is_not_reviewed(monkeypatch):
    parsed_artifact = SimpleNamespace(
        id=78,
        status="failed",
        parse_preview={"total_parsed": 0},
        error_msg="low parse confidence",
    )

    async def fake_parse_xtb_file(*_args, **_kwargs):
        return parsed_artifact

    monkeypatch.setattr(
        "app.services.xtb_gmail_ingest.parse_xtb_file",
        fake_parse_xtb_file,
    )
    client = FakeGmailClient([xtb_message()], {("msg-1", "att-1"): b"%PDF-fixture"})
    session = FakeSession()

    result = await ingest_xtb_gmail_attachments(
        client,
        session,
        password_provider=lambda: "pdf-password",
    )

    assert result["created"] == 0
    assert result["skipped"] == 1
    assert result["items"] == [
        {
            "message_id": "msg-1",
            "attachment_id": "att-1",
            "status": "low_parse_confidence",
            "artifact_id": 78,
            "reason": "low parse confidence",
        }
    ]
    assert session.commits == 0


@pytest.mark.asyncio
async def test_ingest_ignores_non_xtb_messages_and_non_pdf_attachments(monkeypatch):
    async def forbidden_parse(*_args, **_kwargs):
        raise AssertionError("irrelevant messages should not be parsed")

    monkeypatch.setattr(
        "app.services.xtb_gmail_ingest.parse_xtb_file",
        forbidden_parse,
    )
    client = FakeGmailClient(
        [
            GmailMessage(
                id="msg-2",
                thread_id="thread-2",
                from_email="newsletter@example.com",
                subject="not xtb",
                internal_date_ms=1778544000000,
                attachments=[
                    GmailAttachment(
                        id="att-2",
                        filename="statement.pdf",
                        mime_type="application/pdf",
                        size=100,
                    )
                ],
            ),
            GmailMessage(
                id="msg-3",
                thread_id="thread-3",
                from_email="dailystatements@mail.xtb.com",
                subject="Daily statement",
                internal_date_ms=1778544000000,
                attachments=[
                    GmailAttachment(
                        id="att-3",
                        filename="statement.txt",
                        mime_type="text/plain",
                        size=100,
                    )
                ],
            ),
        ],
        {},
    )

    result = await ingest_xtb_gmail_attachments(
        client,
        FakeSession(),
        password_provider=lambda: "pdf-password",
        config=XtbGmailIngestionConfig(max_results=2),
    )

    assert client.downloads == []
    assert result["searched"] == 2
    assert result["created"] == 0
    assert result["skipped"] == 0
    assert result["items"] == []
