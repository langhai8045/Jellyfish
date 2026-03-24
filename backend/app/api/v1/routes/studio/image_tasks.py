from __future__ import annotations

"""资产与镜头相关的图片生成任务 API。

通过 TaskManager 调用 `ImageGenerationTask`，并使用 `GenerationTaskLink`
将任务与上层业务实体（演员形象/道具/场景/服装/角色/镜头分镜帧）建立关联。
"""

import base64
import mimetypes

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.prompts import PromptTemplate as LcPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import storage
from app.core.db import async_session_maker
from app.core.task_manager import DeliveryMode, SqlAlchemyTaskStore, TaskManager
from app.core.task_manager.types import TaskStatus
from app.core.tasks import ImageGenerationInput, ImageGenerationResult, ImageGenerationTask, ProviderConfig
from app.dependencies import get_db
from app.utils.files import create_file_from_url_or_b64
from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider
from app.models.studio import (
    Actor,
    ActorImage,
    AssetViewAngle,
    AssetQualityLevel,
    Character,
    CharacterImage,
    Costume,
    CostumeImage,
    PromptCategory,
    PromptTemplate,
    Prop,
    PropImage,
    Scene,
    SceneImage,
    ShotDetail,
    ShotCharacterLink,
    FileItem,
    ShotFrameType,
    ShotFrameImage,
)
from app.models.task_links import GenerationTaskLink
from app.schemas.common import ApiResponse, success_response
from app.api.v1.routes.film.common import TaskCreated, _CreateOnlyTask


router = APIRouter()


class StudioImageTaskRequest(BaseModel):
    """Studio 专用图片任务请求体：可选模型 ID，不传则用默认图片模型；供应商由模型反查。

    image_id 表示具体的图片模型 ID，例如：
    - 演员图片：ActorImage.id
    - 场景图片：SceneImage.id
    - 道具图片：PropImage.id
    - 服装图片：CostumeImage.id
    - 角色图片：CharacterImage.id
    - 分镜帧图片：ShotFrameImage.id
    """

    model_id: str | None = Field(
        None,
        description="可选模型 ID（models.id）；不传则使用 ModelSettings.default_image_model_id；Provider 由模型关联反查",
    )
    image_id: int | None = Field(
        None,
        description="图片模型 ID，如 ActorImage.id / SceneImage.id / PropImage.id 等；必须与路径主体 ID 匹配",
    )


class ShotFrameImageTaskRequest(BaseModel):
    """镜头分镜帧图片生成请求体：只根据 `shot_id + frame_type` 定位 ShotFrameImage。

    用于替代旧接口中通过 `image_id` 直接传入 ShotFrameImage.id 的方式。
    """

    model_id: str | None = Field(
        None,
        description="可选模型 ID（models.id）；不传则使用 ModelSettings.default_image_model_id；Provider 由模型关联反查",
    )
    frame_type: ShotFrameType = Field(..., description="first | last | key")


def _provider_key_from_db_name(name: str) -> str:
    """将 Provider.name 映射为任务层 ProviderKey（openai | volcengine）。
    规范名称：openai、火山引擎；兼容旧命名（volc/doubao/bytedance）映射为 volcengine。
    无法映射时抛出 503。
    """
    n = (name or "").strip()
    n_lower = n.lower()
    if n_lower == "openai":
        return "openai"
    if n == "火山引擎" or "volc" in n_lower or "doubao" in n_lower or "bytedance" in n_lower:
        return "volcengine"
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Unsupported provider name: {name!r}. Expected: openai, 火山引擎.",
    )


async def _resolve_image_model(db: AsyncSession, model_id: str | None) -> Model:
    """根据显式 model_id 或默认图片模型解析 Model。"""
    effective_model_id = model_id
    if not effective_model_id:
        settings_row = await db.get(ModelSettings, 1)
        effective_model_id = settings_row.default_image_model_id if settings_row else None

    if not effective_model_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No image model configured in DB (missing explicit model_id and ModelSettings.default_image_model_id)",
        )

    model = await db.get(Model, effective_model_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Configured model_id not found in DB: {effective_model_id}",
        )
    if model.category != ModelCategoryKey.image:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Configured model is not an image model: {effective_model_id} (category={model.category})",
        )
    return model


async def _load_provider_config(db: AsyncSession, provider_id: str) -> ProviderConfig:
    """根据 provider_id 从 DB 解析 ProviderConfig；仅允许适用于图片生成的供应商（openai、火山引擎）。"""
    provider = await db.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Provider not found for provider_id={provider_id}",
        )
    try:
        provider_key = _provider_key_from_db_name(provider.name)
    except HTTPException as e:
        if e.status_code == status.HTTP_503_SERVICE_UNAVAILABLE and (provider.name or "").strip() == "阿里百炼":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该供应商仅适用于文本生成，不支持图片生成（name=阿里百炼）",
            ) from e
        raise
    api_key = (provider.api_key or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Provider api_key is empty for provider_id={provider.id}",
        )
    base_url = (provider.base_url or "").strip() or None
    return ProviderConfig(provider=provider_key, api_key=api_key, base_url=base_url)  # type: ignore[arg-type]


def _prompt_from_description(description: str, *, not_found_msg: str) -> str:
    prompt = (description or "").strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=not_found_msg)
    return prompt


def _is_front_view(view_angle: AssetViewAngle | str | None) -> bool:
    if view_angle is None:
        return False
    value = view_angle.value if isinstance(view_angle, AssetViewAngle) else str(view_angle)
    return value == AssetViewAngle.front.value


def _map_view_angle_for_prompt(view_angle: AssetViewAngle | str | None) -> str:
    if view_angle is None:
        return ""
    raw = view_angle.value if isinstance(view_angle, AssetViewAngle) else str(view_angle)
    view_angle_map = {
        "RIGH": "纯右側面,严格右侧面，90度纯侧面轮廓，耳朵清晰可见",
        "RIGHT": "纯右側面,严格右侧面，90度纯侧面轮廓，耳朵清晰可见",
        "LEFT": "纯左侧面,严格左侧面，90度纯侧面轮廓，耳朵清晰可见",
        "BACK": "正后方,正后方视角，完全背对镜头，只能看到后脑勺和后背",
    }
    return view_angle_map.get(raw, raw)


async def _resolve_prompt_template(
    db: AsyncSession,
    *,
    category: PromptCategory,
) -> PromptTemplate | None:
    stmt = (
        select(PromptTemplate)
        .where(PromptTemplate.category == category)
        .order_by(PromptTemplate.is_default.desc(), PromptTemplate.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


def _render_prompt_template_content(
    content: str,
    *,
    variables: dict[str, object],
) -> str:
    tmpl = LcPromptTemplate.from_template(content)
    render_vars = {k: str(variables.get(k, "")) for k in tmpl.input_variables}
    return tmpl.format(**render_vars).strip()


async def _build_prompt_with_template(
    db: AsyncSession,
    *,
    category: PromptCategory,
    variables: dict[str, object],
    fallback_prompt: str,
    not_found_msg: str,
) -> str:
    template = await _resolve_prompt_template(db, category=category)
    if template is not None and template.content:
        rendered = _render_prompt_template_content(template.content, variables=variables)
        if rendered:
            return rendered
    return _prompt_from_description(fallback_prompt, not_found_msg=not_found_msg)


async def _resolve_front_image_ref(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_id: str,
    preferred_quality_level: object | None,
) -> dict[str, str] | None:
    parent_field = getattr(image_model, parent_field_name)
    stmt = (
        select(image_model)
        .where(
            parent_field == parent_id,
            image_model.view_angle == AssetViewAngle.front,
            image_model.file_id.is_not(None),
        )
        .order_by(image_model.created_at.desc(), image_model.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return None

    target = rows[0]
    if preferred_quality_level is not None:
        for row in rows:
            if row.quality_level == preferred_quality_level:
                target = row
                break

    if not target.file_id:
        return None

    file_obj = await db.get(FileItem, target.file_id)
    if file_obj is None or not file_obj.storage_key:
        return None

    try:
        content = await storage.download_file(key=file_obj.storage_key)
    except Exception:  # noqa: BLE001
        return None
    if not content:
        return None

    content_type: str | None = None
    try:
        info = await storage.get_file_info(key=file_obj.storage_key)
        content_type = (info.content_type or "").strip().lower() or None
    except Exception:  # noqa: BLE001
        content_type = None

    if not content_type:
        guessed_type, _ = mimetypes.guess_type(file_obj.storage_key)
        content_type = (guessed_type or "").strip().lower() or None

    if not content_type or not content_type.startswith("image/"):
        content_type = "image/png"

    image_format = content_type.split("/", 1)[1].split(";", 1)[0].strip().lower() or "png"
    encoded = base64.b64encode(content).decode("ascii")
    data_url = f"data:image/{image_format};base64,{encoded}"
    return {"image_url": data_url}


async def _resolve_ordered_image_refs(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_id: str,
    view_angles: tuple[AssetViewAngle, ...],
) -> list[dict[str, str]]:
    """按指定 view_angles 顺序，解析参考图（data url）。

    - 仅取 file_id 不为空的记录；
    - 同一 view_angle 取最新的一张（created_at desc, id desc）；
    - 解析失败的角度会被跳过（不中断整体任务创建）。
    """
    parent_field = getattr(image_model, parent_field_name)
    stmt = (
        select(image_model)
        .where(
            parent_field == parent_id,
            image_model.file_id.is_not(None),
        )
        .order_by(image_model.created_at.desc(), image_model.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return []

    # 先按 view_angle 选“最新一张”
    best_by_angle: dict[str, object] = {}
    for row in rows:
        angle = getattr(row, "view_angle", None)
        # 显式 isinstance 以便静态类型检查器正确收窄类型。
        key = angle.value if isinstance(angle, AssetViewAngle) else str(angle)
        if key and key not in best_by_angle:
            best_by_angle[key] = row

    out: list[dict[str, str]] = []
    for angle in view_angles:
        row = best_by_angle.get(angle.value)
        if row is None:
            continue
        file_id = getattr(row, "file_id", None)
        if not file_id:
            continue
        file_obj = await db.get(FileItem, str(file_id))
        if file_obj is None or not file_obj.storage_key:
            continue
        try:
            content = await storage.download_file(key=file_obj.storage_key)
        except Exception:  # noqa: BLE001
            continue
        if not content:
            continue

        content_type: str | None = None
        try:
            info = await storage.get_file_info(key=file_obj.storage_key)
            content_type = (info.content_type or "").strip().lower() or None
        except Exception:  # noqa: BLE001
            content_type = None
        if not content_type:
            guessed_type, _ = mimetypes.guess_type(file_obj.storage_key)
            content_type = (guessed_type or "").strip().lower() or None
        if not content_type or not content_type.startswith("image/"):
            content_type = "image/png"

        image_format = content_type.split("/", 1)[1].split(";", 1)[0].strip().lower() or "png"
        encoded = base64.b64encode(content).decode("ascii")
        data_url = f"data:image/{image_format};base64,{encoded}"
        out.append({"image_url": data_url})
    return out


def _asset_prompt_category(
    *,
    relation_type: str,
    is_front_view: bool,
) -> PromptCategory:
    mapping = {
        "actor_image": (PromptCategory.actor_image_front, PromptCategory.actor_image_other),
        "prop_image": (PromptCategory.prop_front, PromptCategory.prop_other),
        "scene_image": (PromptCategory.scene_front, PromptCategory.scene_other),
        "costume_image": (PromptCategory.costume_front, PromptCategory.costume_other),
    }
    front_category, other_category = mapping[relation_type]
    return front_category if is_front_view else other_category


def _shot_frame_prompt_category(frame_type: ShotFrameType | str) -> PromptCategory:
    value = frame_type.value if isinstance(frame_type, ShotFrameType) else str(frame_type)
    if value == ShotFrameType.first.value:
        return PromptCategory.frame_head
    if value == ShotFrameType.last.value:
        return PromptCategory.frame_tail
    return PromptCategory.frame_key


async def _create_image_task_and_link(
    *,
    db: AsyncSession,
    model_id: str | None,
    relation_type: str,
    relation_entity_id: str,
    prompt: str,
    images: list[dict[str, str]] | None = None,
) -> TaskCreated:
    """创建图片生成任务，并在 `GenerationTaskLink` 中建立关联；Provider 由解析出的 Model 反查。"""
    store = SqlAlchemyTaskStore(db)
    tm = TaskManager(store=store, strategies={})

    model = await _resolve_image_model(db, model_id)
    provider_cfg = await _load_provider_config(db, model.provider_id)

    run_args: dict = {
        "provider": provider_cfg.provider,
        "api_key": provider_cfg.api_key,
        "base_url": provider_cfg.base_url,
        "input": {
            "prompt": prompt,
            # 生成参数与参考图统一从 DB 侧控制；此接口不接收覆盖参数。
            "model": model.name,
        },
    }
    if images:
        run_args["input"]["images"] = images

    task_record = await tm.create(
        task=_CreateOnlyTask(),
        mode=DeliveryMode.async_polling,
        run_args=run_args,
    )

    link = GenerationTaskLink(
        task_id=task_record.id,
        resource_type="image",
        relation_type=relation_type,
        relation_entity_id=relation_entity_id,
    )
    db.add(link)
    await db.commit()

    async def _persist_images_to_assets(
        session: AsyncSession,
        *,
        task_id: str,
        relation_type: str,
        relation_entity_id: str,
        result: ImageGenerationResult,
    ) -> None:
        """根据 relation_type 将生成的图片落库为 FileItem + 具体资产图片表。

        - 先将图片内容上传到 S3，创建 FileItem 记录；
        - 再根据 relation_type 写入 ActorImage / SceneImage 等业务图片表；
        - 当前实现先支持 actor_image / scene_image / prop_image / costume_image，其他类型可按需扩展。
        """
        from sqlalchemy import select

        from app.models.studio import (
            ActorImage,
            CharacterImage,
            CostumeImage,
            PropImage,
            SceneImage,
            ShotFrameImage,
        )

        # 目前 ImageGenerationResult.images 优先使用 url；若仅有 b64，可在此扩展为下载/解码再上传。
        images = result.images or []
        if not images:
            return

        # 简化起见：仅处理第一张图片
        item = images[0]
        if not item.url:
            # 暂不支持纯 base64 输出的自动落库
            return

        # 使用通用工具方法：从 URL 创建 FileItem 并上传到对象存储
        file_obj = await create_file_from_url_or_b64(
            session,
            url=item.url,
            name=f"{relation_type}-{relation_entity_id}",
            prefix=f"generated-images/{relation_type}/{relation_entity_id}",
        )
        file_id = file_obj.id

        link_stmt = (
            select(GenerationTaskLink)
            .where(
                GenerationTaskLink.task_id == task_id,
                GenerationTaskLink.relation_type == relation_type,
                GenerationTaskLink.relation_entity_id == relation_entity_id,
            )
            .limit(1)
        )
        link_result = await session.execute(link_stmt)
        link_row = link_result.scalars().first()
        if link_row is not None and not link_row.file_id:
            link_row.file_id = file_id

        # 根据 relation_type 将生成文件填充到已有 image 槽位的 file_id（仅首张生效）
        if relation_type == "actor_image":
            image_row = await session.get(ActorImage, int(relation_entity_id))
            if image_row is not None and not image_row.file_id:
                image_row.file_id = file_id
        elif relation_type == "scene_image":
            image_row = await session.get(SceneImage, int(relation_entity_id))
            if image_row is not None and not image_row.file_id:
                image_row.file_id = file_id
        elif relation_type == "prop_image":
            image_row = await session.get(PropImage, int(relation_entity_id))
            if image_row is not None and not image_row.file_id:
                image_row.file_id = file_id
        elif relation_type == "costume_image":
            image_row = await session.get(CostumeImage, int(relation_entity_id))
            if image_row is not None and not image_row.file_id:
                image_row.file_id = file_id
        elif relation_type == "character_image":
            image_row = await session.get(CharacterImage, int(relation_entity_id))
            if image_row is not None and not image_row.file_id:
                image_row.file_id = file_id
        elif relation_type == "character":
            # 角色生成（任务版）：落库为 CharacterImage（优先填充 front+low 槽位；没有则创建）
            character_id = relation_entity_id
            stmt_ci = (
                select(CharacterImage)
                .where(
                    CharacterImage.character_id == character_id,
                    CharacterImage.quality_level == AssetQualityLevel.low,
                    CharacterImage.view_angle == AssetViewAngle.front,
                )
                .order_by(CharacterImage.id.asc())
                .limit(1)
            )
            ci_res = await session.execute(stmt_ci)
            ci = ci_res.scalars().first()
            if ci is not None:
                if not ci.file_id:
                    ci.file_id = file_id
                    ci.format = getattr(ci, "format", "") or "png"
            else:
                # 创建一个 front+low 的槽位，并设为主图（同一角色只允许一张主图，下面会清理其他主图）
                ci = CharacterImage(
                    character_id=character_id,
                    file_id=file_id,
                    quality_level=AssetQualityLevel.low,
                    view_angle=AssetViewAngle.front,
                    width=None,
                    height=None,
                    format="png",
                    is_primary=True,
                )
                session.add(ci)

            # 如果本次落库的行是主图，确保同一角色只有一个主图
            if ci is not None and getattr(ci, "is_primary", False) is True and getattr(ci, "id", None) is not None:
                stmt_clear = (
                    CharacterImage.__table__.update()  # type: ignore[attr-defined]
                    .where(CharacterImage.character_id == character_id, CharacterImage.id != ci.id)
                    .values(is_primary=False)
                )
                await session.execute(stmt_clear)
        elif relation_type == "shot_frame_image":
            image_row = await session.get(ShotFrameImage, int(relation_entity_id))
            if image_row is not None:
                # 无条件覆盖：如果该 ShotFrameImage 是占位记录，也需要在生成完成后写入新图片。
                image_row.file_id = file_id

    async def _runner(task_id: str, args: dict) -> None:
        async with async_session_maker() as session:
            try:
                store2 = SqlAlchemyTaskStore(session)
                await store2.set_status(task_id, TaskStatus.running)
                await store2.set_progress(task_id, 10)

                provider = str(args.get("provider") or "")
                api_key = str(args.get("api_key") or "")
                base_url = args.get("base_url")
                input_dict = dict(args.get("input") or {})

                task = ImageGenerationTask(
                    provider_config=ProviderConfig(
                        provider=provider,  # type: ignore[arg-type]
                        api_key=api_key,
                        base_url=base_url,
                    ),
                    input_=ImageGenerationInput.model_validate(input_dict),
                )
                await task.run()
                result = await task.get_result()
                if result is None:
                    raise RuntimeError("Image generation task returned no result")

                await store2.set_result(task_id, result.model_dump())
                # 任务成功后，自动将生成图片上传到 S3 并落库到资产图片表
                await _persist_images_to_assets(
                    session,
                    task_id=task_id,
                    relation_type=relation_type,
                    relation_entity_id=relation_entity_id,
                    result=result,
                )
                await store2.set_progress(task_id, 100)
                await store2.set_status(task_id, TaskStatus.succeeded)
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                async with async_session_maker() as s2:
                    store3 = SqlAlchemyTaskStore(s2)
                    await store3.set_error(task_id, str(exc))
                    await store3.set_status(task_id, TaskStatus.failed)
                    await s2.commit()

    import asyncio

    asyncio.create_task(_runner(task_record.id, run_args))
    return TaskCreated(task_id=task_record.id)


@router.post(
    "/actors/{actor_id}/image-tasks",
    response_model=ApiResponse[TaskCreated],
    status_code=status.HTTP_201_CREATED,
    summary="演员图片生成（任务版）",
)
async def create_actor_image_generation_task(
    actor_id: str,
    body: StudioImageTaskRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskCreated]:
    """为指定演员创建图片生成任务，并通过 `GenerationTaskLink` 关联。"""
    actor = await db.get(Actor, actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Actor not found")
    if body.image_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image_id is required for actor generation",
        )
    image_row = await db.get(ActorImage, body.image_id)
    if image_row is None or image_row.actor_id != actor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image_id does not belong to given actor_id",
        )
    is_front_view = _is_front_view(image_row.view_angle)
    category = _asset_prompt_category(
        relation_type="actor_image",
        is_front_view=is_front_view,
    )
    prompt = await _build_prompt_with_template(
        db,
        category=category,
        variables={
            "name": actor.name,
            "description": actor.description,
            "tags": ", ".join(actor.tags or []),
            "view_angle": _map_view_angle_for_prompt(image_row.view_angle),
            "quality_level": image_row.quality_level,
            "format": image_row.format,
        },
        fallback_prompt=actor.description,
        not_found_msg="Actor.description is empty",
    )

    created = await _create_image_task_and_link(
        db=db,
        model_id=body.model_id,
        relation_type="actor_image",
        relation_entity_id=str(image_row.id),
        prompt=prompt,
        images=(
            []
            if is_front_view
            else [ref]
            if (ref := await _resolve_front_image_ref(
                db,
                image_model=ActorImage,
                parent_field_name="actor_id",
                parent_id=actor_id,
                preferred_quality_level=image_row.quality_level,
            ))
            else []
        ),
    )
    return success_response(created, code=201)


@router.post(
    "/assets/{asset_type}/{asset_id}/image-tasks",
    response_model=ApiResponse[TaskCreated],
    status_code=status.HTTP_201_CREATED,
    summary="道具/场景/服装图片生成（任务版）",
)
async def create_asset_image_generation_task(
    asset_type: str,
    asset_id: str,
    body: StudioImageTaskRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskCreated]:
    """为道具/场景/服装创建图片生成任务。

    - asset_type: prop / scene / costume
    - path 参数 asset_id 为对应资产 ID
    - body.image_id 必须为该资产下对应图片表记录的 ID（PropImage/SceneImage/CostumeImage）
    """
    if body.image_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image_id is required for asset image generation",
        )

    asset_type_norm = asset_type.strip().lower()
    if asset_type_norm == "prop":
        asset = await db.get(Prop, asset_id)
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prop not found")
        image_row = await db.get(PropImage, body.image_id)
        if image_row is None or image_row.prop_id != asset_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="image_id does not belong to given prop_id",
            )
        relation_type = "prop_image"
        is_front_view = _is_front_view(image_row.view_angle)
        category = _asset_prompt_category(
            relation_type=relation_type,
            is_front_view=is_front_view,
        )
        prompt = await _build_prompt_with_template(
            db,
            category=category,
            variables={
                "name": asset.name,
                "description": asset.description,
                "tags": ", ".join(asset.tags or []),
                "view_angle": _map_view_angle_for_prompt(image_row.view_angle),
                "quality_level": image_row.quality_level,
                "format": image_row.format,
            },
            fallback_prompt=asset.description,
            not_found_msg="Prop.description is empty",
        )
        images = (
            []
            if is_front_view
            else [ref]
            if (ref := await _resolve_front_image_ref(
                db,
                image_model=PropImage,
                parent_field_name="prop_id",
                parent_id=asset_id,
                preferred_quality_level=image_row.quality_level,
            ))
            else []
        )
    elif asset_type_norm == "scene":
        asset = await db.get(Scene, asset_id)
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scene not found")
        image_row = await db.get(SceneImage, body.image_id)
        if image_row is None or image_row.scene_id != asset_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="image_id does not belong to given scene_id",
            )
        relation_type = "scene_image"
        is_front_view = _is_front_view(image_row.view_angle)
        category = _asset_prompt_category(
            relation_type=relation_type,
            is_front_view=is_front_view,
        )
        prompt = await _build_prompt_with_template(
            db,
            category=category,
            variables={
                "name": asset.name,
                "description": asset.description,
                "tags": ", ".join(asset.tags or []),
                "view_angle": _map_view_angle_for_prompt(image_row.view_angle),
                "quality_level": image_row.quality_level,
                "format": image_row.format,
            },
            fallback_prompt=asset.description,
            not_found_msg="Scene.description is empty",
        )
        images = (
            []
            if is_front_view
            else [ref]
            if (ref := await _resolve_front_image_ref(
                db,
                image_model=SceneImage,
                parent_field_name="scene_id",
                parent_id=asset_id,
                preferred_quality_level=image_row.quality_level,
            ))
            else []
        )
    elif asset_type_norm == "costume":
        asset = await db.get(Costume, asset_id)
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Costume not found")
        image_row = await db.get(CostumeImage, body.image_id)
        if image_row is None or image_row.costume_id != asset_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="image_id does not belong to given costume_id",
            )
        relation_type = "costume_image"
        is_front_view = _is_front_view(image_row.view_angle)
        category = _asset_prompt_category(
            relation_type=relation_type,
            is_front_view=is_front_view,
        )
        prompt = await _build_prompt_with_template(
            db,
            category=category,
            variables={
                "name": asset.name,
                "description": asset.description,
                "tags": ", ".join(asset.tags or []),
                "view_angle": _map_view_angle_for_prompt(image_row.view_angle),
                "quality_level": image_row.quality_level,
                "format": image_row.format,
            },
            fallback_prompt=asset.description,
            not_found_msg="Costume.description is empty",
        )
        images = (
            []
            if is_front_view
            else [ref]
            if (ref := await _resolve_front_image_ref(
                db,
                image_model=CostumeImage,
                parent_field_name="costume_id",
                parent_id=asset_id,
                preferred_quality_level=image_row.quality_level,
            ))
            else []
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="asset_type must be one of: prop/scene/costume",
        )

    created = await _create_image_task_and_link(
        db=db,
        model_id=body.model_id,
        relation_type=relation_type,
        relation_entity_id=str(body.image_id),
        prompt=prompt,
        images=images,
    )
    return success_response(created, code=201)


@router.post(
    "/characters/{character_id}/image-tasks",
    response_model=ApiResponse[TaskCreated],
    status_code=status.HTTP_201_CREATED,
    summary="角色图片生成（任务版）",
)
async def create_character_image_generation_task(
    character_id: str,
    body: StudioImageTaskRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskCreated]:
    """为角色创建图片生成任务（对应 CharacterImage 业务）。

    - path 参数 character_id 为 Character.id
    - body.image_id 必须为该角色下的 CharacterImage.id
    """
    character = await db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    if body.image_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image_id is required for character image generation",
        )
    image_row = await db.get(CharacterImage, body.image_id)
    if image_row is None or image_row.character_id != character_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image_id does not belong to given character_id",
        )
    prompt = await _build_prompt_with_template(
        db,
        category=PromptCategory.combined,
        variables={
            "name": character.name,
            "description": character.description,
            "view_angle": _map_view_angle_for_prompt(image_row.view_angle),
            "quality_level": image_row.quality_level,
            "format": image_row.format,
        },
        fallback_prompt=character.description,
        not_found_msg="Character.description is empty",
    )
    # 自动带上参考图：Actor 图片（若存在）+ Costume 图片（若角色关联了）
    actor: Actor | None = await db.get(Actor, character.actor_id) if character.actor_id else None
    costume: Costume | None = await db.get(Costume, character.costume_id) if character.costume_id else None

    DEFAULT_VIEW_ANGLES: tuple[AssetViewAngle, ...] = (
        AssetViewAngle.front,
        AssetViewAngle.left,
        AssetViewAngle.right,
        AssetViewAngle.back,
    )
    actor_refs: list[dict[str, str]] = []
    if actor is not None:
        actor_refs = await _resolve_ordered_image_refs(
            db,
            image_model=ActorImage,
            parent_field_name="actor_id",
            parent_id=actor.id,
            view_angles=DEFAULT_VIEW_ANGLES,
        )
    costume_refs: list[dict[str, str]] = []
    if costume is not None:
        costume_refs = await _resolve_ordered_image_refs(
            db,
            image_model=CostumeImage,
            parent_field_name="costume_id",
            parent_id=costume.id,
            view_angles=DEFAULT_VIEW_ANGLES,
        )
    ref_images = [*actor_refs, *costume_refs]
    created = await _create_image_task_and_link(
        db=db,
        model_id=body.model_id,
        relation_type="character_image",
        relation_entity_id=str(image_row.id),
        prompt=prompt,
        images=ref_images if ref_images else None,
    )
    return success_response(created, code=201)


@router.post(
    "/shot/{shot_id}/frame-image-tasks",
    response_model=ApiResponse[TaskCreated],
    status_code=status.HTTP_201_CREATED,
    summary="镜头分镜帧图片生成（任务版）",
)
async def create_shot_frame_image_generation_task(
    shot_id: str,
    body: ShotFrameImageTaskRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TaskCreated]:
    """为镜头分镜帧图片生成任务（基于 `shot_id + frame_type` 自动定位数据）。"""

    shot_detail = await db.get(ShotDetail, shot_id)
    if shot_detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ShotDetail not found")

    # 取对应帧的原始提示词。
    if body.frame_type == ShotFrameType.first:
        raw_prompt = (shot_detail.first_frame_prompt or "").strip()
    elif body.frame_type == ShotFrameType.last:
        raw_prompt = (shot_detail.last_frame_prompt or "").strip()
    else:
        raw_prompt = (shot_detail.key_frame_prompt or "").strip()

    if not raw_prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ShotDetail has no prompt for frame_type={body.frame_type}",
        )

    # 通过 shot_id 与 frame_type 定位 ShotFrameImage，作为落库目标；若不存在则创建占位记录。
    shot_frame_image_stmt = (
        select(ShotFrameImage)
        .where(ShotFrameImage.shot_detail_id == shot_id, ShotFrameImage.frame_type == body.frame_type)
        .limit(1)
    )
    shot_frame_image = (await db.execute(shot_frame_image_stmt)).scalars().first()
    if shot_frame_image is None:
        # 缺少对应 frame_type 的 ShotFrameImage slot：创建占位记录（file_id 允许为空）。
        # 后续图片生成完成后会覆盖写回 file_id。
        shot_frame_image = ShotFrameImage(
            shot_detail_id=shot_id,
            frame_type=body.frame_type,
            file_id=None,
            width=None,
            height=None,
            format="png",
        )
        db.add(shot_frame_image)
        await db.flush()
        await db.refresh(shot_frame_image)
    else:
        # 已存在则补齐默认字段（不改写 file_id）。
        if not shot_frame_image.format:
            shot_frame_image.format = "png"

    # 通过 shot_id 取镜头角色，并按 ShotCharacterLink.index 构建角色顺序。
    role_links_stmt = (
        select(ShotCharacterLink)
        .options(selectinload(ShotCharacterLink.character))
        .where(ShotCharacterLink.shot_id == shot_id)
        .order_by(ShotCharacterLink.index.asc())
    )
    role_links = (await db.execute(role_links_stmt)).scalars().all()
    # 若镜头未绑定任何角色，则允许继续生成：此时不传入 role images，prompt 使用原始 frame prompt（不做角色替换）。

    role_names: list[str] = []
    role_image_refs: list[dict[str, str]] = []

    for link in role_links:
        character = link.character
        if character is None:
            continue

        # 每个角色取一个 front 参考图，保证 image list 顺序与角色顺序一致。
        ref = await _resolve_front_image_ref(
            db,
            image_model=CharacterImage,
            parent_field_name="character_id",
            parent_id=character.id,
            preferred_quality_level=None,
        )
        if ref is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"CharacterImage front ref not found for character_id={character.id}, name={character.name}",
            )

        role_names.append(character.name)
        role_image_refs.append(ref)

    if role_links and not role_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid shot character image refs found",
        )
    if len(set(role_names)) != len(role_names):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate character names in shot character links; cannot map names to image order",
        )

    def _cn_num(n: int) -> str:
        ones = {0: "零", 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九"}
        if n <= 9:
            return ones[n]
        if n == 10:
            return "十"
        if n < 20:
            return f"十{ones[n - 10]}"
        tens = n // 10
        rem = n % 10
        if rem == 0:
            return f"{ones[tens]}十"
        return f"{ones[tens]}十{ones[rem]}"

    # 将提示词中的角色名替换为图一/图二/...，以 image list 顺序作为图序。
    name_to_token: dict[str, str] = {
        name: f"图{_cn_num(i + 1)}"
        for i, name in enumerate(role_names)
    }
    sorted_pairs = sorted(name_to_token.items(), key=lambda kv: len(kv[0]), reverse=True)

    def _replace_names(text: str) -> str:
        out = text or ""
        for name, token in sorted_pairs:
            if name:
                out = out.replace(name, token)
        return out

    # 同步替换所有帧提示词变量，避免模板使用了 first/last/key 任一字段时仍保留角色名。
    replaced_first = _replace_names(shot_detail.first_frame_prompt or "")
    replaced_last = _replace_names(shot_detail.last_frame_prompt or "")
    replaced_key = _replace_names(shot_detail.key_frame_prompt or "")

    base_prompt = _replace_names(raw_prompt)
    prompt = await _build_prompt_with_template(
        db,
        category=_shot_frame_prompt_category(shot_frame_image.frame_type),
        variables={
            "description": shot_detail.description,
            "atmosphere": shot_detail.atmosphere,
            "mood_tags": ", ".join(shot_detail.mood_tags or []),
            "camera_shot": shot_detail.camera_shot,
            "angle": shot_detail.angle,
            "movement": shot_detail.movement,
            "frame_type": shot_frame_image.frame_type,
            "first_frame_prompt": replaced_first,
            "last_frame_prompt": replaced_last,
            "key_frame_prompt": replaced_key,
            "base_prompt": base_prompt,
        },
        fallback_prompt=base_prompt,
        not_found_msg=f"ShotDetail has no prompt for frame_type={body.frame_type}",
    )

    created = await _create_image_task_and_link(
        db=db,
        model_id=body.model_id,
        relation_type="shot_frame_image",
        relation_entity_id=str(shot_frame_image.id),
        prompt=prompt,
        images=role_image_refs if role_image_refs else None,
    )
    return success_response(created, code=201)

