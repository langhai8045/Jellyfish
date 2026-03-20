"""Studio 实体与缩略图通用辅助。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import (
    Actor,
    ActorImage,
    AssetViewAngle,
    Character,
    CharacterImage,
    Costume,
    CostumeImage,
    Prop,
    PropImage,
    Scene,
    SceneImage,
)
from app.schemas.studio.assets import CharacterImageRead, CostumeImageRead, PropImageRead, SceneImageRead
from app.schemas.studio.cast import ActorCreate, ActorRead, ActorUpdate, CharacterCreate, CharacterRead, CharacterUpdate
from app.schemas.studio.cast_images import ActorImageRead

DOWNLOAD_URL_TEMPLATE = "/api/v1/studio/files/{file_id}/download"


def download_url(file_id: str) -> str:
    return DOWNLOAD_URL_TEMPLATE.format(file_id=file_id)


def normalize_entity_type(entity_type: str) -> str:
    t = entity_type.strip().lower()
    if t not in {"actor", "character", "scene", "prop", "costume"}:
        raise HTTPException(status_code=400, detail="entity_type must be one of: actor/character/scene/prop/costume")
    return t


def entity_spec(entity_type: str) -> dict[str, Any]:
    t = normalize_entity_type(entity_type)
    if t == "actor":
        return {
            "model": Actor,
            "image_model": ActorImage,
            "id_field": "actor_id",
            "entity_id_field": "actor_id",
            "read_model": ActorRead,
            "create_model": ActorCreate,
            "update_model": ActorUpdate,
            "image_read_model": ActorImageRead,
        }
    if t == "character":
        return {
            "model": Character,
            "image_model": CharacterImage,
            "id_field": "character_id",
            "entity_id_field": "character_id",
            "read_model": CharacterRead,
            "create_model": CharacterCreate,
            "update_model": CharacterUpdate,
            "image_read_model": CharacterImageRead,
        }
    if t == "scene":
        return {
            "model": Scene,
            "image_model": SceneImage,
            "id_field": "scene_id",
            "entity_id_field": "scene_id",
            "read_model": None,
            "create_model": None,
            "update_model": None,
            "image_read_model": SceneImageRead,
        }
    if t == "prop":
        return {
            "model": Prop,
            "image_model": PropImage,
            "id_field": "prop_id",
            "entity_id_field": "prop_id",
            "read_model": None,
            "create_model": None,
            "update_model": None,
            "image_read_model": PropImageRead,
        }
    return {
        "model": Costume,
        "image_model": CostumeImage,
        "id_field": "costume_id",
        "entity_id_field": "costume_id",
        "read_model": None,
        "create_model": None,
        "update_model": None,
        "image_read_model": CostumeImageRead,
    }


async def resolve_thumbnails(db: AsyncSession, *, image_model: type, parent_field_name: str, parent_ids: list[str]) -> dict[str, str]:
    if not parent_ids:
        return {}
    parent_field = getattr(image_model, parent_field_name)
    stmt = select(image_model).where(parent_field.in_(parent_ids), image_model.file_id.is_not(None))
    rows = (await db.execute(stmt)).scalars().all()
    best: dict[str, tuple[int, int, int, str]] = {}
    for row in rows:
        file_id = row.file_id
        if not file_id:
            continue
        parent_id = getattr(row, parent_field_name)
        created_ts = int(row.created_at.timestamp()) if row.created_at else -1
        score = (1 if row.view_angle == AssetViewAngle.front else 0, created_ts, row.id)
        current = best.get(parent_id)
        if current is None or score > current[:3]:
            best[parent_id] = (*score, file_id)
    return {parent_id: download_url(score[3]) for parent_id, score in best.items()}

