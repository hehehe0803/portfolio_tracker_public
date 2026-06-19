"""Read-only Gmail discovery for XTB PDF statements.

The ingestion entrypoint accepts an injected Gmail client so tests and operators can
control the OAuth scope outside this module. This service only searches and
downloads PDF attachments into the existing XTB import preview flow.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ImportArtifact
from app.services.xtb_ingest import parse_xtb_file

XTB_DAILY_STATEMENT_SENDER = "dailystatements@mail.xtb.com"
DEFAULT_GMAIL_QUERY = (
    f"from:{XTB_DAILY_STATEMENT_SENDER} has:attachment filename:pdf newer_than:1y"
)
DEFAULT_GMAIL_LABEL = "serious"


@dataclass(frozen=True)
class GmailAttachment:
    id: str
    filename: str
    mime_type: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str
    from_email: str
    subject: str
    internal_date_ms: int | None = None
    attachments: list[GmailAttachment] = field(default_factory=list)


@dataclass(frozen=True)
class XtbGmailIngestionConfig:
    query: str = DEFAULT_GMAIL_QUERY
    label_ids: tuple[str, ...] = (DEFAULT_GMAIL_LABEL,)
    max_results: int = 10


class XtbGmailClient(Protocol):
    async def search_messages(
        self, *, query: str, label_ids: list[str], max_results: int
    ) -> list[GmailMessage]:
        """Return message metadata from a read-only Gmail search."""

    async def download_attachment(
        self, *, message_id: str, attachment_id: str
    ) -> bytes:
        """Return attachment bytes without mutating the mailbox."""


def xtb_gmail_attachment_filename(
    message_id: str, attachment_id: str, pdf_sha256: str
) -> str:
    """Create a deterministic import filename for Gmail attachment dedupe."""
    return f"xtb-gmail-{message_id}-{attachment_id}-{pdf_sha256[:12]}.pdf"


async def ingest_xtb_gmail_attachments(
    client: XtbGmailClient,
    session: AsyncSession,
    *,
    password_provider: Callable[[], str | None],
    config: XtbGmailIngestionConfig | None = None,
) -> dict:
    """Download XTB PDF attachments and create reviewed import previews.

    This function does not confirm imports or create canonical transactions.
    """
    config = config or XtbGmailIngestionConfig()
    messages = await client.search_messages(
        query=config.query,
        label_ids=list(config.label_ids),
        max_results=config.max_results,
    )

    result = {"searched": len(messages), "created": 0, "skipped": 0, "items": []}

    for message in messages:
        if message.from_email.lower() != XTB_DAILY_STATEMENT_SENDER:
            continue

        for attachment in _pdf_attachments(message.attachments):
            existing = await _find_existing_gmail_artifact(
                session,
                message_id=message.id,
                attachment_id=attachment.id,
            )
            if existing is not None:
                result["skipped"] += 1
                result["items"].append(
                    {
                        "message_id": message.id,
                        "attachment_id": attachment.id,
                        "status": "duplicate",
                        "artifact_id": existing.id,
                        "filename": existing.filename,
                    }
                )
                continue

            password = password_provider()
            if not password:
                result["skipped"] += 1
                result["items"].append(
                    {
                        "message_id": message.id,
                        "attachment_id": attachment.id,
                        "status": "password_missing",
                        "reason": "XTB PDF password is not configured",
                    }
                )
                continue

            payload = await client.download_attachment(
                message_id=message.id,
                attachment_id=attachment.id,
            )
            pdf_sha256 = hashlib.sha256(payload).hexdigest()
            filename = xtb_gmail_attachment_filename(
                message.id, attachment.id, pdf_sha256
            )
            try:
                artifact = await parse_xtb_file(
                    payload,
                    filename,
                    session,
                    pdf_password=password,
                )
            except Exception as exc:
                result["skipped"] += 1
                result["items"].append(
                    {
                        "message_id": message.id,
                        "attachment_id": attachment.id,
                        "status": "parse_failed",
                        "reason": str(exc),
                    }
                )
                continue
            if artifact.status != "reviewed":
                result["skipped"] += 1
                result["items"].append(
                    {
                        "message_id": message.id,
                        "attachment_id": attachment.id,
                        "status": "low_parse_confidence",
                        "artifact_id": artifact.id,
                        "reason": artifact.error_msg
                        or f"Unexpected import preview status: {artifact.status}",
                    }
                )
                continue
            preview = dict(artifact.parse_preview or {})
            preview["source"] = {
                "type": "gmail_attachment",
                "gmail_message_id": message.id,
                "gmail_thread_id": message.thread_id,
                "gmail_attachment_id": attachment.id,
                "gmail_attachment_filename": attachment.filename,
                "pdf_sha256": pdf_sha256,
                "statement_order_ids": _sample_values(preview, "id"),
                "statement_dates": _sample_values(preview, "date"),
            }
            artifact.parse_preview = preview
            await session.commit()

            result["created"] += 1
            result["items"].append(
                {
                    "message_id": message.id,
                    "attachment_id": attachment.id,
                    "status": artifact.status,
                    "artifact_id": artifact.id,
                    "filename": filename,
                }
            )

    return result


def _pdf_attachments(
    attachments: Sequence[GmailAttachment],
) -> list[GmailAttachment]:
    return [
        attachment
        for attachment in attachments
        if attachment.filename.lower().endswith(".pdf")
        and (attachment.mime_type in {None, "application/pdf"})
    ]


async def _find_existing_gmail_artifact(
    session: AsyncSession, *, message_id: str, attachment_id: str
) -> ImportArtifact | None:
    filename_prefix = f"xtb-gmail-{message_id}-{attachment_id}-"
    result = await session.execute(
        select(ImportArtifact).where(
            ImportArtifact.institution == "xtb",
            ImportArtifact.filename.like(f"{filename_prefix}%"),
        )
    )
    return result.scalar_one_or_none()


def _sample_values(preview: dict, key: str) -> list[str]:
    values: list[str] = []
    for item in preview.get("sample", []):
        value = item.get(key)
        if value is not None:
            values.append(str(value))
    return values
