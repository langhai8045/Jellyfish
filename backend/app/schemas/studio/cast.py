"""演员/角色及关联表 schemas。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ActorBase(BaseModel):
    id: str = Field(..., description="演员 ID")
    name: str = Field(..., description="名称")
    description: str = Field("", description="描述")
    tags: list[str] = Field(default_factory=list, description="标签")
    prompt_template_id: str | None = Field(None, description="提示词模板 ID（可空）")
    view_count: int = Field(1, ge=1, description="计划为该演员生成的视角图片数量（不含分镜帧）")


class ActorCreate(ActorBase):
    pass


class ActorUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    prompt_template_id: str | None = None
    view_count: int | None = Field(None, ge=1)


class ActorRead(ActorBase):
    thumbnail: str = Field("", description="缩略图下载地址")

    class Config:
        from_attributes = True


class CharacterBase(BaseModel):
    id: str = Field(..., description="角色 ID")
    project_id: str = Field(..., description="所属项目 ID")
    name: str = Field(..., description="角色名称")
    description: str = Field("", description="角色描述")
    actor_id: str | None = Field(None, description="演员 ID（可空；用于仅导入角色文案但不关联演员时）")
    costume_id: str | None = Field(None, description="服装 ID（可空）")


class CharacterCreate(CharacterBase):
    pass


class CharacterUpdate(BaseModel):
    project_id: str | None = None
    name: str | None = None
    description: str | None = None
    actor_id: str | None = None
    costume_id: str | None = None


class CharacterRead(CharacterBase):
    thumbnail: str = Field("", description="缩略图下载地址")

    class Config:
        from_attributes = True


class CharacterPropLinkBase(BaseModel):
    id: int = Field(..., description="关联行 ID")
    character_id: str = Field(..., description="角色 ID")
    prop_id: str = Field(..., description="道具 ID")
    index: int = Field(0, description="角色道具排序")
    note: str = Field("", description="备注")


class CharacterPropLinkCreate(BaseModel):
    character_id: str
    prop_id: str
    index: int = 0
    note: str = ""


class CharacterPropLinkUpdate(BaseModel):
    index: int | None = None
    note: str | None = None


class CharacterPropLinkRead(CharacterPropLinkBase):
    class Config:
        from_attributes = True


class ShotCharacterLinkBase(BaseModel):
    id: int = Field(..., description="关联行 ID")
    shot_id: str = Field(..., description="镜头 ID")
    character_id: str = Field(..., description="角色 ID")
    index: int = Field(0, description="镜头内角色排序")
    note: str = Field("", description="备注")


class ShotCharacterLinkCreate(BaseModel):
    shot_id: str
    character_id: str
    index: int = 0
    note: str = ""


class ShotCharacterLinkUpdate(BaseModel):
    index: int | None = None
    note: str | None = None


class ShotCharacterLinkRead(ShotCharacterLinkBase):
    class Config:
        from_attributes = True

