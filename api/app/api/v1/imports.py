"""
Import endpoints: upload XTB/Binance statements, preview, confirm.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.db.models import ImportArtifact
from app.services.binance_ingest import confirm_binance_import, parse_binance_file
from app.services.xtb_ingest import confirm_import, parse_xtb_file

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
SUPPORTED_XTB_SUFFIXES = {".xlsx", ".html", ".mhtml", ".mht"}
SUPPORTED_BINANCE_SUFFIXES = {".zip", ".csv"}


def _artifact_response(artifact: ImportArtifact) -> dict:
    return {
        "artifact_id": artifact.id,
        "status": artifact.status,
        "preview": artifact.parse_preview,
        "error": artifact.error_msg,
    }


def _validate_file_suffix(
    filename: str | None, allowed_suffixes: set[str], detail: str
) -> str:
    suffix = Path(filename or "").suffix.lower()
    if not filename or suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail=detail)
    return suffix


@router.post("/xtb")
async def upload_xtb(file: UploadFile, user: CurrentUser, db: DBSession):
    """Upload an XTB statement. Returns artifact ID + parse preview."""
    _validate_file_suffix(
        file.filename,
        SUPPORTED_XTB_SUFFIXES,
        "Only .xlsx, .html, .mhtml, and .mht files are supported",
    )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")

    artifact = await parse_xtb_file(file_bytes, file.filename, db)
    return _artifact_response(artifact)


@router.post("/binance")
async def upload_binance(file: UploadFile, user: CurrentUser, db: DBSession):
    """Upload a Binance export archive and return an import preview."""
    _validate_file_suffix(
        file.filename,
        SUPPORTED_BINANCE_SUFFIXES,
        "Only .zip and .csv Binance exports are supported",
    )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")

    try:
        artifact = await parse_binance_file(file_bytes, file.filename, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _artifact_response(artifact)


@router.post("/{artifact_id}/confirm")
async def confirm(artifact_id: int, user: CurrentUser, db: DBSession):
    """Confirm a parsed import: commits transactions to DB."""
    artifact = (
        await db.execute(select(ImportArtifact).where(ImportArtifact.id == artifact_id))
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Import not found")

    try:
        if artifact.institution == "binance":
            return await confirm_binance_import(artifact_id, db)
        return await confirm_import(artifact_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/")
async def list_imports(user: CurrentUser, db: DBSession):
    result = await db.execute(
        select(ImportArtifact).order_by(ImportArtifact.created_at.desc()).limit(50)
    )
    artifacts = result.scalars().all()
    return [
        {
            "id": a.id,
            "institution": a.institution,
            "filename": a.filename,
            "status": a.status,
            "parsed_count": a.parsed_count,
            "committed_count": a.committed_count,
            "duplicate_count": a.duplicate_count,
            "created_at": a.created_at.isoformat(),
            "committed_at": a.committed_at.isoformat() if a.committed_at else None,
        }
        for a in artifacts
    ]


@router.get("/{artifact_id}")
async def get_import(artifact_id: int, user: CurrentUser, db: DBSession):
    result = await db.execute(
        select(ImportArtifact).where(ImportArtifact.id == artifact_id)
    )
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="Import not found")
    return {
        "id": artifact.id,
        "institution": artifact.institution,
        "filename": artifact.filename,
        "status": artifact.status,
        "parsed_count": artifact.parsed_count,
        "committed_count": artifact.committed_count,
        "duplicate_count": artifact.duplicate_count,
        "preview": artifact.parse_preview,
        "error": artifact.error_msg,
        "created_at": artifact.created_at.isoformat(),
        "committed_at": artifact.committed_at.isoformat()
        if artifact.committed_at
        else None,
    }
