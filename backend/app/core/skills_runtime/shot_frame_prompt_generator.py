"""镜头分镜首帧/尾帧/关键帧提示词生成技能。输入对齐 Shot + ShotDetail，输出为单个 prompt 字符串。

技能说明见 backend/skills/shot_*_frame_prompt_generator.md。
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field


class ShotFramePromptInput(BaseModel):
    """镜头帧提示词生成输入，与 Shot + ShotDetail 字段对齐。"""

    model_config = ConfigDict(extra="forbid")

    script_excerpt: str = Field(..., description="剧本摘录，对应 Shot.script_excerpt")
    title: str = Field("", description="镜头标题，对应 Shot.title")
    camera_shot: Optional[str] = Field(None, description="景别，如 ECU/CU/MS")
    angle: Optional[str] = Field(None, description="机位角度")
    movement: Optional[str] = Field(None, description="运镜方式")
    atmosphere: Optional[str] = Field(None, description="氛围描述")
    mood_tags: Optional[List[str]] = Field(None, description="情绪标签")
    vfx_type: Optional[str] = Field(None, description="视效类型")
    vfx_note: Optional[str] = Field(None, description="视效说明")
    duration: Optional[int] = Field(None, description="时长（秒）")
    scene_id: Optional[str] = Field(None, description="关联场景 ID")
    dialog_summary: Optional[str] = Field(None, description="对白摘要")


class ShotFramePromptResult(BaseModel):
    """镜头帧提示词生成结果：单个 prompt 字符串。"""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., description="画面描述提示词，可写入 ShotDetail 对应字段")


_SHOT_FRAME_INPUT_VARS = [
    "script_excerpt", "title", "camera_shot", "angle", "movement",
    "atmosphere", "mood_tags", "vfx_type", "vfx_note", "duration",
    "scene_id", "dialog_summary",
]

_FIRST_FRAME_TEMPLATE = """你是一名分镜师。根据下列镜头信息，生成该镜头的**首帧**画面描述提示词（用于图像生成模型）。
要求：一句或几句简洁、可视化的中文描述（不得使用英文），涵盖画面主体、景别、氛围、关键动作或状态。
专有名词一致性规则：
- 剧本摘录（script_excerpt）中出现的角色名/场景名/道具名等专有名词，必须在输出中**原样保留**，不得翻译、不得替换为同义词或其他说法。
- 除了需要补全画面描述以外，不要对专有名词进行改写。
只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要其他文字。

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}

## 输出（仅首帧提示词，JSON：{{"prompt": "..."}}）
"""

_LAST_FRAME_TEMPLATE = """你是一名分镜师。根据下列镜头信息，生成该镜头的**尾帧**画面描述提示词（用于图像生成模型）。
要求：一句或几句简洁、可视化的中文描述（不得使用英文），描述镜头结束时的画面状态。
专有名词一致性规则：
- 剧本摘录（script_excerpt）中出现的角色名/场景名/道具名等专有名词，必须在输出中**原样保留**，不得翻译、不得替换为同义词或其他说法。
- 除了需要补全画面描述以外，不要对专有名词进行改写。
只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要其他文字。

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}

## 输出（仅尾帧提示词，JSON：{{"prompt": "..."}}）
"""

_KEY_FRAME_TEMPLATE = """你是一名分镜师。根据下列镜头信息，生成该镜头的**关键帧**画面描述提示词（用于图像生成模型）。
要求：一句或几句简洁、可视化的中文描述（不得使用英文），捕捉该镜头中最具代表性的瞬间画面。
专有名词一致性规则：
- 剧本摘录（script_excerpt）中出现的角色名/场景名/道具名等专有名词，必须在输出中**原样保留**，不得翻译、不得替换为同义词或其他说法。
- 除了需要补全画面描述以外，不要对专有名词进行改写。
只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要其他文字。

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}

## 输出（仅关键帧提示词，JSON：{{"prompt": "..."}}）
"""

SHOT_FIRST_FRAME_PROMPT = PromptTemplate(
    input_variables=_SHOT_FRAME_INPUT_VARS,
    template=_FIRST_FRAME_TEMPLATE,
)
SHOT_LAST_FRAME_PROMPT = PromptTemplate(
    input_variables=_SHOT_FRAME_INPUT_VARS,
    template=_LAST_FRAME_TEMPLATE,
)
SHOT_KEY_FRAME_PROMPT = PromptTemplate(
    input_variables=_SHOT_FRAME_INPUT_VARS,
    template=_KEY_FRAME_TEMPLATE,
)
