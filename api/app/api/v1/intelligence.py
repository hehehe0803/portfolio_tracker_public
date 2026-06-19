from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.db.models import ActivityLog, Asset, AssetTheme, Note, NoteVersion, Tag, Theme, asset_tags

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

EntityType = Literal["portfolio", "asset", "watchlist", "system"]
ASSET_TYPES = {"crypto", "equity", "etf", "commodity", "cash", "bond", "fund", "unknown"}
THESIS_STATUSES = {"none", "watching", "building", "core", "trim", "exit", "closed"}


class NoteIn(BaseModel):
    entity_type: EntityType
    entity_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1)


class NoteUpdate(BaseModel):
    content: str = Field(min_length=1)


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: str = Field(default="#64748b", max_length=20)
    icon: str | None = Field(default=None, max_length=50)


class ClassificationIn(BaseModel):
    sector: str | None = Field(default=None, max_length=80)
    asset_type: str = Field(default="unknown", max_length=20)
    themes: list[str] = Field(default_factory=list)
    thesis_status: str = Field(default="none", max_length=30)


def _note_json(note: Note) -> dict:
    return {
        "id": note.id,
        "entity_type": note.entity_type,
        "entity_id": note.entity_id,
        "content": note.content,
        "user_id": note.user_id,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "deleted_at": note.deleted_at.isoformat() if note.deleted_at else None,
    }


def _tag_json(tag: Tag) -> dict:
    return {"id": tag.id, "name": tag.name, "color": tag.color, "icon": tag.icon, "created_at": tag.created_at.isoformat()}


def _activity(source: str, status: str, message: str, user_id: int | None, metadata: dict) -> ActivityLog:
    return ActivityLog(source=source, status=status, message=message, user_id=user_id, event_metadata=metadata)


async def _asset_by_symbol(db: DBSession, symbol: str) -> Asset:
    asset = await db.scalar(select(Asset).where(Asset.symbol == symbol.upper()))
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.post("/notes")
async def create_note(payload: NoteIn, user: CurrentUser, db: DBSession):
    note = Note(entity_type=payload.entity_type, entity_id=payload.entity_id.upper() if payload.entity_type == "asset" else payload.entity_id, content=payload.content, user_id=user.id)
    db.add(note)
    await db.flush()
    db.add(NoteVersion(note_id=note.id, version=1, content=note.content, operation="create", user_id=user.id))
    db.add(_activity("note", "created", f"Note created for {note.entity_type}:{note.entity_id}", user.id, {"entity_type": note.entity_type, "entity_id": note.entity_id, "note_id": note.id}))
    await db.commit()
    await db.refresh(note)
    return _note_json(note)


@router.get("/notes")
async def list_notes(user: CurrentUser, db: DBSession, entity_type: EntityType | None = None, entity_id: str | None = None, include_deleted: bool = False):
    q = select(Note).order_by(Note.created_at.desc(), Note.id.desc())
    if entity_type:
        q = q.where(Note.entity_type == entity_type)
    if entity_id:
        q = q.where(Note.entity_id == (entity_id.upper() if entity_type == "asset" else entity_id))
    if not include_deleted:
        q = q.where(Note.deleted_at.is_(None))
    notes = (await db.execute(q)).scalars().all()
    return [_note_json(n) for n in notes]


@router.patch("/notes/{note_id}")
async def update_note(note_id: int, payload: NoteUpdate, user: CurrentUser, db: DBSession):
    note = await db.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Note not found")
    latest = await db.scalar(select(NoteVersion.version).where(NoteVersion.note_id == note.id).order_by(NoteVersion.version.desc()).limit(1))
    note.content = payload.content
    from app.db.models import utcnow
    note.updated_at = utcnow()
    db.add(NoteVersion(note_id=note.id, version=(latest or 0) + 1, content=payload.content, operation="update", user_id=user.id))
    db.add(_activity("note", "updated", f"Note updated for {note.entity_type}:{note.entity_id}", user.id, {"entity_type": note.entity_type, "entity_id": note.entity_id, "note_id": note.id}))
    await db.commit()
    await db.refresh(note)
    return _note_json(note)


@router.delete("/notes/{note_id}")
async def delete_note(note_id: int, user: CurrentUser, db: DBSession):
    note = await db.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Note not found")
    latest = await db.scalar(select(NoteVersion.version).where(NoteVersion.note_id == note.id).order_by(NoteVersion.version.desc()).limit(1))
    from app.db.models import utcnow
    note.deleted_at = utcnow()
    note.updated_at = note.deleted_at
    db.add(NoteVersion(note_id=note.id, version=(latest or 0) + 1, content=note.content, operation="delete", user_id=user.id))
    db.add(_activity("note", "deleted", f"Note deleted for {note.entity_type}:{note.entity_id}", user.id, {"entity_type": note.entity_type, "entity_id": note.entity_id, "note_id": note.id}))
    await db.commit()
    return {"message": "Deleted"}


@router.get("/notes/{note_id}/versions")
async def note_versions(note_id: int, user: CurrentUser, db: DBSession):
    rows = (await db.execute(select(NoteVersion).where(NoteVersion.note_id == note_id).order_by(NoteVersion.version.asc()))).scalars().all()
    return [{"id": row.id, "note_id": row.note_id, "version": row.version, "content": row.content, "operation": row.operation, "user_id": row.user_id, "created_at": row.created_at.isoformat()} for row in rows]


@router.post("/tags")
async def create_tag(payload: TagIn, user: CurrentUser, db: DBSession):
    tag = Tag(name=payload.name.strip(), color=payload.color, icon=payload.icon)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return _tag_json(tag)


@router.get("/tags")
async def list_tags(user: CurrentUser, db: DBSession):
    return [_tag_json(t) for t in (await db.execute(select(Tag).order_by(Tag.name.asc()))).scalars().all()]


@router.patch("/tags/{tag_id}")
async def update_tag(tag_id: int, payload: TagIn, user: CurrentUser, db: DBSession):
    tag = await db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    tag.name, tag.color, tag.icon = payload.name.strip(), payload.color, payload.icon
    await db.commit(); await db.refresh(tag)
    return _tag_json(tag)


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int, user: CurrentUser, db: DBSession):
    tag = await db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    await db.delete(tag); await db.commit()
    return {"message": "Deleted"}


@router.post("/assets/{symbol}/tags/{tag_id}")
async def assign_asset_tag(symbol: str, tag_id: int, user: CurrentUser, db: DBSession):
    asset = await _asset_by_symbol(db, symbol)
    tag = await db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    exists = await db.execute(select(asset_tags).where(asset_tags.c.asset_id == asset.id, asset_tags.c.tag_id == tag.id))
    if exists.first() is None:
        await db.execute(asset_tags.insert().values(asset_id=asset.id, tag_id=tag.id))
        db.add(_activity("tag", "assigned", f"Tag {tag.name} assigned to {asset.symbol}", user.id, {"entity_type": "asset", "entity_id": asset.symbol, "tag_id": tag.id}))
    await db.commit()
    return {"message": "Assigned"}


@router.delete("/assets/{symbol}/tags/{tag_id}")
async def remove_asset_tag(symbol: str, tag_id: int, user: CurrentUser, db: DBSession):
    asset = await _asset_by_symbol(db, symbol)
    tag = await db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    await db.execute(delete(asset_tags).where(asset_tags.c.asset_id == asset.id, asset_tags.c.tag_id == tag.id))
    db.add(_activity("tag", "removed", f"Tag {tag.name} removed from {asset.symbol}", user.id, {"entity_type": "asset", "entity_id": asset.symbol, "tag_id": tag.id}))
    await db.commit()
    return {"message": "Removed"}


@router.get("/assets/{symbol}/classification")
async def get_classification(symbol: str, user: CurrentUser, db: DBSession):
    asset = await db.scalar(select(Asset).options(selectinload(Asset.themes), selectinload(Asset.tags)).where(Asset.symbol == symbol.upper()))
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"symbol": asset.symbol, "sector": asset.sector, "asset_type": asset.asset_type, "themes": [t.name for t in asset.themes], "thesis_status": asset.thesis_status, "tags": [_tag_json(t) for t in asset.tags]}


@router.put("/assets/{symbol}/classification")
async def put_classification(symbol: str, payload: ClassificationIn, user: CurrentUser, db: DBSession):
    if payload.asset_type not in ASSET_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported asset_type")
    if payload.thesis_status not in THESIS_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported thesis_status")
    asset = await _asset_by_symbol(db, symbol)
    asset.sector = payload.sector
    asset.asset_type = payload.asset_type
    asset.thesis_status = payload.thesis_status
    theme_ids: list[int] = []
    for name in dict.fromkeys([t.strip() for t in payload.themes if t.strip()]):
        theme = await db.scalar(select(Theme).where(Theme.name == name))
        if theme is None:
            theme = Theme(name=name)
            db.add(theme)
            await db.flush()
        theme_ids.append(theme.id)
    await db.execute(delete(AssetTheme).where(AssetTheme.asset_id == asset.id))
    for theme_id in theme_ids:
        db.add(AssetTheme(asset_id=asset.id, theme_id=theme_id))
    db.add(_activity("classification", "changed", f"Classification changed for {asset.symbol}", user.id, {"entity_type": "asset", "entity_id": asset.symbol}))
    await db.commit()
    return await get_classification(asset.symbol, user, db)


@router.get("/activity")
async def activity_timeline(user: CurrentUser, db: DBSession, entity_type: str | None = None, entity_id: str | None = None, limit: int = Query(50, ge=1, le=200)):
    q = select(ActivityLog).order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(limit)
    if entity_type:
        q = q.where(ActivityLog.event_metadata["entity_type"].as_string() == entity_type)
    if entity_id:
        normalized_entity_id = entity_id.upper() if entity_type == "asset" else entity_id
        q = q.where(ActivityLog.event_metadata["entity_id"].as_string() == normalized_entity_id)
    logs = (await db.execute(q)).scalars().all()
    return [{"id": log.id, "source": log.source, "status": log.status, "message": log.message, "entity_type": (log.event_metadata or {}).get("entity_type"), "entity_id": (log.event_metadata or {}).get("entity_id"), "metadata": log.event_metadata or {}, "created_at": log.created_at.isoformat()} for log in logs]
