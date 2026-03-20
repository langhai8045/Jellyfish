"""统一实体 CRUD：actor/character/scene/prop/costume。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import apply_keyword_filter, apply_order, paginate
from app.dependencies import get_db
from app.models.studio import (
    Actor,
    ActorImage,
    AssetViewAngle,
    Character,
    CharacterImage,
    Costume,
    CostumeImage,
    Project,
    Prop,
    PropImage,
    Scene,
    SceneImage,
)
from app.schemas.common import ApiResponse, PaginatedData, paginated_response, success_response
from app.schemas.studio.assets import (
    AssetCreate,
    AssetImageCreate,
    AssetImageUpdate,
    AssetUpdate,
    CharacterImageRead,
    CostumeImageRead,
    PropImageRead,
    SceneImageRead,
)
from app.schemas.studio.cast import ActorCreate, ActorRead, ActorUpdate, CharacterCreate, CharacterRead, CharacterUpdate
from app.schemas.studio.cast_images import ActorImageRead

router = APIRouter()

ENTITY_ORDER_FIELDS = {"name", "created_at", "updated_at"}
IMAGE_ORDER_FIELDS = {"id", "quality_level", "view_angle", "created_at", "updated_at"}
DOWNLOAD_URL_TEMPLATE = "/api/v1/studio/files/{file_id}/download"
DEFAULT_VIEW_ANGLES: tuple[AssetViewAngle, ...] = (
    AssetViewAngle.front,
    AssetViewAngle.left,
    AssetViewAngle.right,
    AssetViewAngle.back,
)


def _download_url(file_id: str) -> str:
    return DOWNLOAD_URL_TEMPLATE.format(file_id=file_id)


def _normalize_entity_type(entity_type: str) -> str:
    t = entity_type.strip().lower()
    if t not in {"actor", "character", "scene", "prop", "costume"}:
        raise HTTPException(status_code=400, detail="entity_type must be one of: actor/character/scene/prop/costume")
    return t


def _entity_spec(entity_type: str) -> dict[str, Any]:
    t = _normalize_entity_type(entity_type)
    if t == "actor":
        return {
            "model": Actor,
            "image_model": ActorImage,
            "id_field": "actor_id",
            "read_model": ActorRead,
            "create_model": ActorCreate,
            "update_model": ActorUpdate,
            "image_read_model": ActorImageRead,
            "image_create_model": AssetImageCreate,
            "image_update_model": AssetImageUpdate,
        }
    if t == "character":
        return {
            "model": Character,
            "image_model": CharacterImage,
            "id_field": "character_id",
            "read_model": CharacterRead,
            "create_model": CharacterCreate,
            "update_model": CharacterUpdate,
            "image_read_model": CharacterImageRead,
            "image_create_model": AssetImageCreate,
            "image_update_model": AssetImageUpdate,
        }
    if t == "scene":
        return {
            "model": Scene,
            "image_model": SceneImage,
            "id_field": "scene_id",
            "read_model": None,
            "create_model": AssetCreate,
            "update_model": AssetUpdate,
            "image_read_model": SceneImageRead,
            "image_create_model": AssetImageCreate,
            "image_update_model": AssetImageUpdate,
        }
    if t == "prop":
        return {
            "model": Prop,
            "image_model": PropImage,
            "id_field": "prop_id",
            "read_model": None,
            "create_model": AssetCreate,
            "update_model": AssetUpdate,
            "image_read_model": PropImageRead,
            "image_create_model": AssetImageCreate,
            "image_update_model": AssetImageUpdate,
        }
    return {
        "model": Costume,
        "image_model": CostumeImage,
        "id_field": "costume_id",
        "read_model": None,
        "create_model": AssetCreate,
        "update_model": AssetUpdate,
        "image_read_model": CostumeImageRead,
        "image_create_model": AssetImageCreate,
        "image_update_model": AssetImageUpdate,
    }


async def _resolve_thumbnails(db: AsyncSession, *, image_model: type, parent_field_name: str, parent_ids: list[str]) -> dict[str, str]:
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
    return {parent_id: _download_url(score[3]) for parent_id, score in best.items()}


def _asset_read_payload(entity_type: str, obj: Any, thumbnail: str) -> dict[str, Any]:
    base = {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "tags": obj.tags or [],
        "prompt_template_id": obj.prompt_template_id,
        "view_count": obj.view_count,
        "thumbnail": thumbnail,
    }
    return base


@router.get("/{entity_type}", response_model=ApiResponse[PaginatedData[dict[str, Any]]], summary="统一实体列表（分页）")
async def list_entities(
    entity_type: str,
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="关键字，过滤 name/description"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    spec = _entity_spec(entity_type)
    model = spec["model"]
    stmt = select(model)
    stmt = apply_keyword_filter(stmt, q=q, fields=[model.name, model.description])
    stmt = apply_order(stmt, model=model, order=order, is_desc=is_desc, allow_fields=ENTITY_ORDER_FIELDS, default="created_at")
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)

    thumbnails = await _resolve_thumbnails(
        db,
        image_model=spec["image_model"],
        parent_field_name=spec["id_field"],
        parent_ids=[x.id for x in items],
    )
    payload: list[dict[str, Any]] = []
    for x in items:
        thumbnail = thumbnails.get(x.id, "")
        if entity_type in {"actor", "character"}:
            read_model = spec["read_model"]
            payload.append(read_model.model_validate(x).model_copy(update={"thumbnail": thumbnail}).model_dump())
        else:
            payload.append(_asset_read_payload(entity_type, x, thumbnail))
    return paginated_response(payload, page=page, page_size=page_size, total=total)


@router.post("/{entity_type}", response_model=ApiResponse[dict[str, Any]], status_code=status.HTTP_201_CREATED, summary="统一创建实体")
async def create_entity(
    entity_type: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    spec = _entity_spec(entity_type)
    model = spec["model"]
    create_model = spec["create_model"]
    parsed = create_model.model_validate(body)
    data = parsed.model_dump()

    exists = await db.get(model, data["id"])
    if exists is not None:
        raise HTTPException(status_code=400, detail=f"{model.__name__} with id={data['id']} already exists")

    if entity_type == "character":
        if await db.get(Project, data["project_id"]) is None:
            raise HTTPException(status_code=400, detail="Project not found")
        if data.get("actor_id"):
            if await db.get(Actor, data["actor_id"]) is None:
                raise HTTPException(status_code=400, detail="Actor not found")
        if data.get("costume_id") and await db.get(Costume, data["costume_id"]) is None:
            raise HTTPException(status_code=400, detail="Costume not found")

    obj = model(**data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)

    # actor/scene/prop/costume 按 view_count 自动创建图片槽位
    if entity_type in {"actor", "scene", "prop", "costume"}:
        count = int(getattr(obj, "view_count", 1) or 1)
        angles = list(DEFAULT_VIEW_ANGLES[: min(max(count, 0), len(DEFAULT_VIEW_ANGLES))])
        image_model = spec["image_model"]
        id_field = spec["id_field"]
        for angle in angles:
            db.add(image_model(**{id_field: obj.id, "view_angle": angle}))
        if angles:
            await db.flush()

    if entity_type in {"actor", "character"}:
        read_model = spec["read_model"]
        payload = read_model.model_validate(obj).model_dump()
        payload["thumbnail"] = ""
    else:
        payload = _asset_read_payload(entity_type, obj, "")
    return success_response(payload, code=201)


@router.get("/{entity_type}/{entity_id}", response_model=ApiResponse[dict[str, Any]], summary="统一获取实体")
async def get_entity(entity_type: str, entity_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[dict[str, Any]]:
    spec = _entity_spec(entity_type)
    model = spec["model"]
    obj = await db.get(model, entity_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    thumbnails = await _resolve_thumbnails(
        db,
        image_model=spec["image_model"],
        parent_field_name=spec["id_field"],
        parent_ids=[entity_id],
    )
    thumbnail = thumbnails.get(entity_id, "")
    if entity_type in {"actor", "character"}:
        read_model = spec["read_model"]
        payload = read_model.model_validate(obj).model_copy(update={"thumbnail": thumbnail}).model_dump()
    else:
        payload = _asset_read_payload(entity_type, obj, thumbnail)
    return success_response(payload)


@router.patch("/{entity_type}/{entity_id}", response_model=ApiResponse[dict[str, Any]], summary="统一更新实体")
async def update_entity(
    entity_type: str,
    entity_id: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    spec = _entity_spec(entity_type)
    model = spec["model"]
    update_model = spec["update_model"]
    obj = await db.get(model, entity_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    update_data = update_model.model_validate(body).model_dump(exclude_unset=True)

    if entity_type == "character":
        if "project_id" in update_data and await db.get(Project, update_data["project_id"]) is None:
            raise HTTPException(status_code=400, detail="Project not found")
        if "actor_id" in update_data and update_data["actor_id"] is not None and await db.get(Actor, update_data["actor_id"]) is None:
            raise HTTPException(status_code=400, detail="Actor not found")
        if "costume_id" in update_data and update_data["costume_id"] is not None and await db.get(Costume, update_data["costume_id"]) is None:
            raise HTTPException(status_code=400, detail="Costume not found")

    for k, v in update_data.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    if entity_type in {"actor", "character"}:
        read_model = spec["read_model"]
        payload = read_model.model_validate(obj).model_dump()
        payload["thumbnail"] = ""
    else:
        payload = _asset_read_payload(entity_type, obj, "")
    return success_response(payload)


@router.delete("/{entity_type}/{entity_id}", response_model=ApiResponse[None], summary="统一删除实体")
async def delete_entity(entity_type: str, entity_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[None]:
    spec = _entity_spec(entity_type)
    model = spec["model"]
    obj = await db.get(model, entity_id)
    if obj is None:
        return success_response(None)
    await db.delete(obj)
    await db.flush()
    return success_response(None)


@router.get(
    "/{entity_type}/{entity_id}/images",
    response_model=ApiResponse[PaginatedData[dict[str, Any]]],
    summary="统一实体图片列表（分页）",
)
async def list_entity_images(
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    spec = _entity_spec(entity_type)
    parent = await db.get(spec["model"], entity_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"{spec['model'].__name__} not found")
    image_model = spec["image_model"]
    id_field = getattr(image_model, spec["id_field"])
    stmt = select(image_model).where(id_field == entity_id)
    stmt = apply_order(stmt, model=image_model, order=order, is_desc=is_desc, allow_fields=IMAGE_ORDER_FIELDS, default="id")
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)
    read_model = spec["image_read_model"]
    payload = [read_model.model_validate(x).model_dump() for x in items]
    return paginated_response(payload, page=page, page_size=page_size, total=total)


@router.post(
    "/{entity_type}/{entity_id}/images",
    response_model=ApiResponse[dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
    summary="统一创建实体图片",
)
async def create_entity_image(
    entity_type: str,
    entity_id: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    spec = _entity_spec(entity_type)
    parent = await db.get(spec["model"], entity_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"{spec['model'].__name__} not found")
    parsed = spec["image_create_model"].model_validate(body).model_dump()
    image_model = spec["image_model"]
    id_field_name = spec["id_field"]
    obj = image_model(**{id_field_name: entity_id, **parsed})
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    if entity_type == "character" and getattr(obj, "is_primary", False):
        stmt = CharacterImage.__table__.update().where(CharacterImage.character_id == entity_id, CharacterImage.id != obj.id).values(is_primary=False)
        await db.execute(stmt)
        await db.refresh(obj)
    return success_response(spec["image_read_model"].model_validate(obj).model_dump(), code=201)


@router.patch(
    "/{entity_type}/{entity_id}/images/{image_id}",
    response_model=ApiResponse[dict[str, Any]],
    summary="统一更新实体图片",
)
async def update_entity_image(
    entity_type: str,
    entity_id: str,
    image_id: int,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    spec = _entity_spec(entity_type)
    image_model = spec["image_model"]
    obj = await db.get(image_model, image_id)
    if obj is None or getattr(obj, spec["id_field"]) != entity_id:
        raise HTTPException(status_code=404, detail=f"{image_model.__name__} not found")
    update_data = spec["image_update_model"].model_validate(body).model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    if entity_type == "character" and update_data.get("is_primary") is True:
        stmt = CharacterImage.__table__.update().where(CharacterImage.character_id == entity_id, CharacterImage.id != obj.id).values(is_primary=False)
        await db.execute(stmt)
        await db.refresh(obj)
    return success_response(spec["image_read_model"].model_validate(obj).model_dump())


@router.delete(
    "/{entity_type}/{entity_id}/images/{image_id}",
    response_model=ApiResponse[None],
    summary="统一删除实体图片",
)
async def delete_entity_image(
    entity_type: str,
    entity_id: str,
    image_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    spec = _entity_spec(entity_type)
    image_model = spec["image_model"]
    obj = await db.get(image_model, image_id)
    if obj is None or getattr(obj, spec["id_field"]) != entity_id:
        return success_response(None)
    await db.delete(obj)
    await db.flush()
    return success_response(None)

