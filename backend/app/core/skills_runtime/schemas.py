"""从小说文本抽取的影视化分镜数据结构：人物/地点/道具、场景、镜头、转场及可追溯证据。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


# ---------- Common ----------
DialogueLineMode = Literal["DIALOGUE", "VOICE_OVER", "OFF_SCREEN", "PHONE"]


class EvidenceSpan(BaseModel):
    """可追溯证据：原文定位（chunk + 起止位置/摘录），用于审核与回查。"""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., description="输入文本块的唯一ID（例如 chapter1_p03）")
    start_char: Optional[int] = Field(None, description="在该 chunk 中的起始字符位置（可选）")
    end_char: Optional[int] = Field(None, description="在该 chunk 中的结束字符位置（可选）")
    quote: Optional[str] = Field(None, description="不超过200字的原文摘录（可选，便于人工审核）")


class DialogueLine(BaseModel):
    """单条对白：说话人/对象、正文、情绪与表达方式、旁白/电话等模式、镜头内时间点。"""

    model_config = ConfigDict(extra="forbid")

    index: Optional[int] = Field(
        None,
        ge=0,
        description="可选：镜头内排序（脚本处理链路用于保持原始顺序）",
    )
    speaker_character_id: Optional[str] = Field(None, description="说话人角色ID，若无法判定可为空")
    target_character_id: Optional[str] = Field(None, description="对谁说（听者角色ID），可选")
    text: str = Field(..., description="对白正文")
    emotion: Optional[str] = Field(None, description="情绪/语气（如：愤怒、平静、哽咽）")
    delivery: Optional[str] = Field(None, description="表达方式（如：低声、喊叫、旁白腔）")
    line_mode: DialogueLineMode = Field(
        "DIALOGUE",
        description="DIALOGUE=正常对白, VOICE_OVER=旁白, OFF_SCREEN=画外音, PHONE=电话音等",
    )
    start_time_sec: Optional[float] = Field(None, ge=0, description="在该镜头内相对起始时间（秒），用于对口型/字幕切分")
    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据")


# ---------- Entities ----------
class Character(BaseModel):
    """从小说中抽取的角色：主名、别名、外貌与性格、服装描述、首次出场证据及抽取置信度。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="稳定ID，例如 char_001")
    name: str = Field(..., description="主名称（尽量取原文最常用的称呼）")
    normalized_name: Optional[str] = Field(None, description="归一化主名，如将「王二/二哥/王二哥」统一为同一主名（来自文本）")
    aliases: List[str] = Field(default_factory=list, description="别名/称呼（原文出现过的）")
    description: Optional[str] = Field(None, description="外貌/身份/气质（忠实原文，与服装区分）")
    costume_note: Optional[str] = Field(
        None,
        description="从原文抽取的服装/造型描述（如款式、颜色、配饰），与 description 区分，便于后续关联服装资产",
    )
    traits: List[str] = Field(default_factory=list, description="性格/特征词（尽量来自原文）")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="抽取确定度 0-1（模型输出）")
    first_appearance: Optional[EvidenceSpan] = None


class Location(BaseModel):
    """从小说中抽取的地点：名称、类型、场景描写及首次出场证据、置信度。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="稳定ID，例如 loc_001")
    name: str = Field(..., description="地点名称（原文）")
    normalized_name: Optional[str] = Field(None, description="归一化名称（来自文本）")
    type: Optional[str] = Field(None, description="地点类型：房间/街道/森林/车厢等（可选）")
    description: Optional[str] = Field(None, description="场景描写（忠实原文，简短）")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="抽取确定度 0-1（模型输出）")
    first_appearance: Optional[EvidenceSpan] = None


class Prop(BaseModel):
    """从小说中抽取的道具：名称、类别、外观/用途、归属角色及首次出场证据、置信度。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="稳定ID，例如 prop_001")
    name: str = Field(..., description="道具名称（原文）")
    normalized_name: Optional[str] = Field(None, description="归一化名称（来自文本）")
    category: Optional[str] = Field(None, description="可选：weapon/document/vehicle/clothing/device/magic_item/other")
    description: Optional[str] = Field(None, description="外观/用途（忠实原文）")
    owner_character_id: Optional[str] = Field(None, description="拥有者（如果明确）")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="抽取确定度 0-1（模型输出）")
    first_appearance: Optional[EvidenceSpan] = None


# ---------- Story / Scenes ----------
SceneTime = Literal["DAY", "NIGHT", "DAWN", "DUSK", "UNKNOWN"]
SceneInterior = Literal["INT", "EXT", "INT_EXT", "UNKNOWN"]

class Scene(BaseModel):
    """场景：内/外景、时间、关联地点与人物/道具，含原文标题与系统格式化标题。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="例如 scene_001")
    raw_title: Optional[str] = Field(None, description="来自原文的场景标题（若存在）")
    formatted_title: Optional[str] = Field(None, description="系统生成的影视格式标题，如 INT. 地点 - TIME")
    interior: SceneInterior = "UNKNOWN"
    time_of_day: SceneTime = "UNKNOWN"

    location_id: Optional[str] = Field(None, description="loc_xxx，如可判定")
    summary: Optional[str] = Field(None, description="场景发生了什么（忠实原文，短）")

    character_ids: List[str] = Field(default_factory=list, description="该场景出现的人物ID")
    prop_ids: List[str] = Field(default_factory=list, description="该场景关键道具ID")
    evidence: List[EvidenceSpan] = Field(default_factory=list, description="支持该场景的证据片段（可多条）")


# ---------- Cinematic (Shots / Transitions / VFX) ----------
ShotType = Literal["ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS"]
CameraAngle = Literal[
    "EYE_LEVEL", "HIGH_ANGLE", "LOW_ANGLE", "BIRD_EYE", "DUTCH", "OVER_SHOULDER"
]
CameraMovement = Literal[
    "STATIC", "PAN", "TILT", "DOLLY_IN", "DOLLY_OUT", "TRACK", "CRANE", "HANDHELD", "STEADICAM", "ZOOM_IN", "ZOOM_OUT"
]
TransitionType = Literal["CUT", "DISSOLVE", "WIPE", "FADE_IN", "FADE_OUT", "MATCH_CUT", "J_CUT", "L_CUT"]
VFXType = Literal[
    "NONE",
    "PARTICLES",
    "VOLUMETRIC_FOG",
    "CG_DOUBLE",
    "DIGITAL_ENVIRONMENT",
    "MATTE_PAINTING",
    "FIRE_SMOKE",
    "WATER_SIM",
    "DESTRUCTION",
    "ENERGY_MAGIC",
    "COMPOSITING_CLEANUP",
    "SLOW_MOTION_TIME",
    "OTHER",
]
ComplexityLevel = Literal["LOW", "MEDIUM", "HIGH"]

# ---------- 英文枚举 → 中文映射（影视/分镜专业用语） ----------
DIALOGUE_LINE_MODE_ZH: dict[str, str] = {
    "DIALOGUE": "对白",
    "VOICE_OVER": "旁白",
    "OFF_SCREEN": "画外音",
    "PHONE": "电话声",
}

SCENE_TIME_ZH: dict[str, str] = {
    "DAY": "日",
    "NIGHT": "夜",
    "DAWN": "黎明",
    "DUSK": "黄昏",
    "UNKNOWN": "未知",
}

SCENE_INTERIOR_ZH: dict[str, str] = {
    "INT": "内景",
    "EXT": "外景",
    "INT_EXT": "内景兼外景",
    "UNKNOWN": "未知",
}

SHOT_TYPE_ZH: dict[str, str] = {
    "ECU": "大特写",
    "CU": "特写",
    "MCU": "中近景",
    "MS": "中景",
    "MLS": "中远景",
    "LS": "远景",
    "ELS": "大远景",
}

CAMERA_ANGLE_ZH: dict[str, str] = {
    "EYE_LEVEL": "平视",
    "HIGH_ANGLE": "俯拍",
    "LOW_ANGLE": "仰拍",
    "BIRD_EYE": "鸟瞰",
    "DUTCH": "荷兰角",
    "OVER_SHOULDER": "过肩",
}

CAMERA_MOVEMENT_ZH: dict[str, str] = {
    "STATIC": "固定",
    "PAN": "横摇",
    "TILT": "俯仰",
    "DOLLY_IN": "推轨",
    "DOLLY_OUT": "拉轨",
    "TRACK": "跟拍",
    "CRANE": "升降",
    "HANDHELD": "手持",
    "STEADICAM": "斯坦尼康",
    "ZOOM_IN": "变焦推进",
    "ZOOM_OUT": "变焦拉远",
}

TRANSITION_TYPE_ZH: dict[str, str] = {
    "CUT": "切",
    "DISSOLVE": "叠化",
    "WIPE": "划变",
    "FADE_IN": "淡入",
    "FADE_OUT": "淡出",
    "MATCH_CUT": "匹配剪辑",
    "J_CUT": "J 剪",
    "L_CUT": "L 剪",
}

VFX_TYPE_ZH: dict[str, str] = {
    "NONE": "无",
    "PARTICLES": "粒子",
    "VOLUMETRIC_FOG": "体积雾",
    "CG_DOUBLE": "数字替身",
    "DIGITAL_ENVIRONMENT": "数字场景",
    "MATTE_PAINTING": "绘景",
    "FIRE_SMOKE": "烟火",
    "WATER_SIM": "水效",
    "DESTRUCTION": "破碎/解算",
    "ENERGY_MAGIC": "能量/魔法",
    "COMPOSITING_CLEANUP": "合成/修脏",
    "SLOW_MOTION_TIME": "升格/慢动作",
    "OTHER": "其他",
}

COMPLEXITY_ZH: dict[str, str] = {
    "LOW": "低",
    "MEDIUM": "中",
    "HIGH": "高",
}

PROP_CATEGORY_ZH: dict[str, str] = {
    "weapon": "武器",
    "document": "文书/证件",
    "vehicle": "载具",
    "clothing": "服装",
    "device": "器械/设备",
    "magic_item": "魔法/特殊物品",
    "other": "其他",
}


class VFXNote(BaseModel):
    """单条视效说明：类型、描述、复杂度及原文依据。"""

    model_config = ConfigDict(extra="forbid")

    vfx_type: VFXType = "NONE"
    description: Optional[str] = Field(None, description="视效说明（简短、可执行）")
    complexity: Optional[ComplexityLevel] = Field(None, description="粗略复杂度")
    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据（若为忠实抽取）")


class Shot(BaseModel):
    """单镜头：景别/机位/运镜、时长与画面描述、对白列表、音效与视效、关联角色与道具。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="例如 shot_001_003（scene_001 第3镜）")
    scene_id: str = Field(..., description="所属 scene_xxx")
    order: int = Field(..., ge=1, description="场景内镜头序号，从1开始")

    shot_type: ShotType
    camera_angle: CameraAngle = "EYE_LEVEL"
    camera_movement: CameraMovement = "STATIC"

    # 可拍性/执行信息
    duration_sec: Optional[float] = Field(None, ge=0.5, le=30, description="建议时长（可选）")
    description: str = Field(..., description="镜头里发生的动作/画面（行业口吻，简短可拍）")

    character_ids: List[str] = Field(default_factory=list)
    prop_ids: List[str] = Field(default_factory=list)

    vfx: List[VFXNote] = Field(default_factory=list)
    sfx: List[str] = Field(default_factory=list, description="音效提示，如 footsteps, rain, explosion（可选）")
    dialogue_lines: List[DialogueLine] = Field(
        default_factory=list,
        description="该镜头内的对白列表（结构化：说话人、对象、情绪、旁白/电话等、时间点）",
    )
    dialogue: Optional[str] = Field(None, description="[兼容] 若该镜头承载关键对白，可摘录/概述（可选）")

    evidence: List[EvidenceSpan] = Field(default_factory=list, description="对应原文依据（可选）")


class Transition(BaseModel):
    """镜头间转场：从哪镜到哪镜、转场类型及可选说明。"""

    model_config = ConfigDict(extra="forbid")

    from_shot_id: str
    to_shot_id: str
    transition: TransitionType = "CUT"
    note: Optional[str] = Field(None, description="为何用该转场（可选）")


# ---------- Extraction metadata & uncertainties ----------
class Uncertainty(BaseModel):
    """结构化不确定项：字段路径、原因及可选证据，便于人工审核与回溯。"""

    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(..., description="如 characters[0].name、scenes[2].location_id")
    reason: str = Field(..., description="不确定原因简述")
    evidence: List[EvidenceSpan] = Field(default_factory=list, description="相关原文依据（可选）")


class ProjectCinematicBreakdown(BaseModel):
    """从小说抽取的完整影视分镜：元信息、实体表、场景表、镜头表、转场表及不确定项。"""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., description="小说/章节标识，例如 novel_x_ch05")
    source_title: Optional[str] = Field(None, description="书名/章节名（从书名页或章节头抽取）")
    source_author: Optional[str] = Field(None, description="作者（若可从文本抽取）")
    language: Optional[str] = Field(None, description="如 zh、en，便于后续提示词与分词")
    extraction_version: Optional[str] = Field(None, description="本次抽取器版本，便于回溯差异")
    schema_version: Optional[str] = Field(None, description="本输出使用的 schema 版本")

    chunks: List[str] = Field(default_factory=list, description="本次处理的 chunk_id 列表")

    characters: List[Character] = Field(default_factory=list)
    locations: List[Location] = Field(default_factory=list)
    props: List[Prop] = Field(default_factory=list)

    scenes: List[Scene] = Field(default_factory=list)
    shots: List[Shot] = Field(default_factory=list)
    transitions: List[Transition] = Field(default_factory=list)

    notes: List[str] = Field(default_factory=list, description="全局备注/不确定点（可选）")
    uncertainties: List[Uncertainty] = Field(
        default_factory=list,
        description="结构化不确定项：field_path、reason、evidence",
    )


# ============================================================================
# Script Processing (Intermediate Schemas)
# ============================================================================

SceneTimeLoose = Literal["DAY", "NIGHT", "DAWN", "DUSK", "UNKNOWN", "日", "夜", "黎明", "黄昏", "不明", "未知"]


class ShotDivision(BaseModel):
    """剧本分镜中的单镜信息：行号 + 预览文本（可选弱语义）。"""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(..., ge=1, description="镜头序号（章节内唯一）")
    start_line: int = Field(..., ge=1, description="起始行号（1-based）")
    end_line: int = Field(..., ge=1, description="结束行号（1-based）")
    script_excerpt: str = Field(..., description="镜头对应的剧本摘录/文本")

    # 强区分：shot_name 是“分镜名/镜头标题”，scene_name 是“场景名”
    shot_name: str = Field("", description="镜头名称（分镜名/镜头标题，勿与 scene_name 混用）")

    # 弱语义：此阶段不强制稳定ID
    scene_name: Optional[str] = Field(None, description="场景名称（可选，来自原文或推断）")
    time_of_day: Optional[SceneTimeLoose] = Field(None, description="时间（日/夜/未知等，可选）")
    character_names_in_text: List[str] = Field(default_factory=list, description="本镜出现的角色名/称呼（弱信息）")


class ScriptDivisionResult(BaseModel):
    """剧本分镜结果：镜头列表（每镜起止行号+预览文本）。"""

    model_config = ConfigDict(extra="forbid")

    shots: List[ShotDivision] = Field(default_factory=list, description="分镜列表")
    total_shots: int = Field(..., ge=0, description="总镜头数")
    notes: Optional[str] = Field(None, description="拆分说明或建议（可选）")


class ShotCharacterInfo(BaseModel):
    """单镜中单个角色的提取信息（弱ID/可溯源）。"""

    model_config = ConfigDict(extra="forbid")

    character_key: str = Field(..., description="角色键（可为临时ID或归一化名；合并阶段再分配稳定ID）")
    name_in_text: Optional[str] = Field(None, description="本镜文本中出现的写法（昵称/小名等）")

    appearance: str = Field("", description="外貌描述：年龄感、体型、发型、五官、疤痕、肤色等")
    clothing: str = Field("", description="本镜服装描述：款式、颜色、材质、状态（破损、湿透、沾泥等）")
    accessories: str = Field("", description="配饰、眼镜、帽子、首饰等")
    state: str = Field("", description="本镜临时状态：情绪主导、受伤、脏污、疲惫等")

    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据（可选）")
    raw_appearance_text: str = Field("", description="导致 appearance 字段的原始剧本片段")
    raw_clothing_text: str = Field("", description="导致 clothing 字段的原始剧本片段")
    raw_state_text: str = Field("", description="导致 state 字段的原始剧本片段")


class ShotPropInfo(BaseModel):
    """单镜中单个道具的提取信息（弱ID/可溯源）。"""

    model_config = ConfigDict(extra="forbid")

    prop_key: str = Field(..., description="道具键（可为临时ID或归一化名；合并阶段再分配稳定ID）")
    name_in_text: Optional[str] = Field(None, description="本镜文本中出现的写法")
    description: str = Field("", description="外观、材质、颜色、尺寸、特殊标记等")
    state: str = Field("", description="当前状态：全新、破损、沾血、打开/关闭等")
    interaction: str = Field("", description="在本镜的使用方式：拿起、丢弃、指向、使用等")

    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据（可选）")
    raw_text: str = Field("", description="导致以上描述的原始文本片段")


class ShotSceneInfo(BaseModel):
    """单镜场景描述（弱ID/可溯源）。"""

    model_config = ConfigDict(extra="forbid")

    scene_key: str = Field(..., description="场景键（可为临时ID或归一化名；合并阶段再分配稳定ID）")
    name: Optional[str] = Field(None, description="场景名称（可选）")
    location_detail: str = Field("", description="具体地点描述：老旧客厅、雨中街头、废弃工厂等")
    atmosphere: str = Field("", description="氛围、光线、色调、声音暗示等")
    time_weather: str = Field("", description="时间+天气补充（如果文本中有）")

    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据（可选）")
    raw_description_text: str = Field("", description="场景相关的主要描述原文")


class ShotElements(BaseModel):
    """单镜提取的元素信息（索引 + 细粒度 + 对白/动作）。"""

    model_config = ConfigDict(extra="forbid")

    # 兼容旧字段：这里允许“弱ID列表”（key 或占位）
    character_keys: List[str] = Field(default_factory=list, description="角色键列表（弱ID）")
    scene_keys: List[str] = Field(default_factory=list, description="场景键列表（弱ID）")
    costume_keys: List[str] = Field(default_factory=list, description="服装键列表（弱ID）")
    prop_keys: List[str] = Field(default_factory=list, description="道具键列表（弱ID）")

    characters_detailed: List[ShotCharacterInfo] = Field(default_factory=list, description="角色细粒度提取")
    props_detailed: List[ShotPropInfo] = Field(default_factory=list, description="道具细粒度提取")
    scene_detailed: Optional[ShotSceneInfo] = Field(None, description="场景细粒度提取")

    dialogue_lines: List[DialogueLine] = Field(default_factory=list, description="结构化对白列表")
    actions: List[str] = Field(default_factory=list, description="动作/场景描述")

    shot_type_hints: List[str] = Field(default_factory=list, description="推断的镜头类型：close-up, wide-shot, tracking 等")
    confidence_breakdown: Dict[str, float] = Field(default_factory=dict, description="各类别置信度")


class ShotElementExtractionResult(BaseModel):
    """单镜信息提取结果。"""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(..., ge=1, description="镜头序号（章节内唯一）")
    shot_division: Optional[ShotDivision] = Field(None, description="分镜元信息（来自 ScriptDivider 输出）")
    elements: ShotElements = Field(..., description="提取的元素")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="提取置信度（0-1）")
    notes: Optional[str] = Field(None, description="提取说明或不确定项")


class EntityVariant(BaseModel):
    """实体变体条目（最小可用结构，便于服装/外形演变）。"""

    model_config = ConfigDict(extra="forbid")

    variant_key: str = Field(..., description="变体键（例如 outfit_v1、wounded_state 等）")
    description: Optional[str] = Field(None, description="变体描述（简短）")
    affected_shots: List[int] = Field(default_factory=list, description="涉及镜头序号")
    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据（可选）")


class EntityEntry(BaseModel):
    """合并后的实体条目（脚本处理中间态）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="实体稳定ID（合并阶段分配）")
    name: str = Field(..., description="实体名称")
    type: Literal["character", "scene", "prop", "location"] = Field(..., description="实体类型")
    # 通用画像（尽量可直接映射到 ProjectCinematicBreakdown 的 Character/Location/Prop）
    normalized_name: Optional[str] = Field(None, description="归一化名称（来自文本，可选）")
    aliases: List[str] = Field(default_factory=list, description="别名/称呼（来自文本，可选）")
    description: Optional[str] = Field(None, description="基础画像/描述（忠实文本，简短）")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="合并确定度 0-1（可选）")
    first_appearance: Optional[EvidenceSpan] = Field(None, description="首次出场证据（可选）")

    # 角色专用（type=character）
    costume_note: Optional[str] = Field(None, description="服装/造型描述（可选，便于变体与资产关联）")
    traits: List[str] = Field(default_factory=list, description="性格/特征词（可选）")

    # 地点专用（type=location）
    location_type: Optional[str] = Field(None, description="地点类型：房间/街道/森林/车厢等（可选）")

    # 道具专用（type=prop）
    category: Optional[str] = Field(None, description="道具类别（可选：weapon/document/vehicle/clothing/device/magic_item/other）")
    owner_character_id: Optional[str] = Field(None, description="拥有者角色ID（可选）")

    evidence: List[EvidenceSpan] = Field(default_factory=list, description="支撑该实体画像的证据片段（可选）")
    first_shot: Optional[int] = Field(None, description="首次出现的镜头序号")
    appearances: List[int] = Field(default_factory=list, description="出现镜头列表")
    variants: List[EntityVariant] = Field(default_factory=list, description="变体列表")


class EntityLibrary(BaseModel):
    """合并后的实体库（脚本处理中间态）。"""

    model_config = ConfigDict(extra="forbid")

    characters: List[EntityEntry] = Field(default_factory=list, description="角色库")
    locations: List[EntityEntry] = Field(default_factory=list, description="地点库")
    scenes: List[EntityEntry] = Field(default_factory=list, description="场景库")
    props: List[EntityEntry] = Field(default_factory=list, description="道具库")
    total_entries: int = Field(..., ge=0, description="总实体数")


class EntityMergeResult(BaseModel):
    """实体合并结果（脚本处理中间态）。"""

    model_config = ConfigDict(extra="forbid")

    merged_library: EntityLibrary = Field(..., description="合并后的实体库")
    merge_stats: Dict[str, Any] = Field(default_factory=dict, description="合并统计信息")
    conflicts: List[str] = Field(default_factory=list, description="发现的冲突/待处理项")
    notes: Optional[str] = Field(None, description="合并说明")


class ConflictResolutionSuggestion(BaseModel):
    """冲突解决建议（用于重试合并）。"""

    model_config = ConfigDict(extra="forbid")

    conflict: str = Field(..., description="与 EntityMergeResult.conflicts 对应的冲突描述（原文/原样）")
    resolution: str = Field(..., description="解决建议（例如：保留哪个名字/合并哪些实体/拆分成变体等）")
    entity_ids: List[str] = Field(default_factory=list, description="涉及的稳定实体ID（若已存在）")
    preferred_entity_id: Optional[str] = Field(None, description="建议优先保留的实体ID（可选）")
    notes: Optional[str] = Field(None, description="补充说明（可选）")


# ============================================================================
# New Flow: Script Consistency / Optimization / Final Extraction
# ============================================================================

class ScriptConsistencyIssue(BaseModel):
    """角色混淆类一致性问题：同一角色在不同镜头被赋予不同身份/行为主体导致混淆。"""

    model_config = ConfigDict(extra="forbid")

    issue_type: Literal["character_confusion"] = Field(
        "character_confusion",
        description="固定为角色混淆类问题",
    )
    character_candidates: List[str] = Field(
        default_factory=list,
        description="涉及的角色候选（名字/称呼/ID 皆可，优先用原文称呼）",
    )
    description: str = Field(..., description="问题描述（为什么会混淆）")
    suggestion: str = Field(..., description="修改建议（如何改写以消除混淆）")
    affected_lines: Optional[Dict[str, int]] = Field(
        None,
        description="受影响的行号范围，形如 {start_line: x, end_line: y}",
    )
    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据（可选）")


class ScriptConsistencyCheckResult(BaseModel):
    """基于原文的一致性检查结果（聚焦角色混淆）。"""

    model_config = ConfigDict(extra="forbid")

    issues: List[ScriptConsistencyIssue] = Field(default_factory=list, description="问题列表")
    has_issues: bool = Field(..., description="是否发现问题")
    summary: Optional[str] = Field(None, description="总结（可选）")


class ScriptOptimizationResult(BaseModel):
    """剧本优化输出：仅在发现角色混淆问题时使用。"""

    model_config = ConfigDict(extra="forbid")

    optimized_script_text: str = Field(..., description="优化后的剧本文本")
    change_summary: str = Field(..., description="改动摘要（只围绕 issues）")


class ScriptShotExtraction(BaseModel):
    """单镜提取结果（最终输出用，引用全局实体稳定ID）。"""

    model_config = ConfigDict(extra="forbid")

    shot_index: int = Field(..., ge=1, description="镜头序号（与 ScriptDivisionResult.shots.index 一致）")
    shot_division: ShotDivision = Field(..., description="该镜头的分镜元信息")

    # 稳定 ID 引用
    scene_id: Optional[str] = Field(None, description="所属场景 ID（scene_###，若可判定）")
    character_ids: List[str] = Field(default_factory=list, description="本镜出现角色 ID 列表（char_###）")
    prop_ids: List[str] = Field(default_factory=list, description="本镜关键道具 ID 列表（prop_###）")
    location_ids: List[str] = Field(default_factory=list, description="本镜关联地点 ID 列表（loc_###）")

    dialogue_lines: List[DialogueLine] = Field(default_factory=list, description="结构化对白列表")
    actions: List[str] = Field(default_factory=list, description="动作/场景描述")

    notes: Optional[str] = Field(None, description="本镜补充说明（可选）")


class ScriptExtractionResult(BaseModel):
    """最终输出：全局实体表 + 每镜关联（信息提取即最终结果）。"""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., description="来源标识（如 demo_script_001）")
    script_text: str = Field(..., description="输入剧本（可能为优化后版本）")

    division: ScriptDivisionResult = Field(..., description="分镜结果")

    # 全局表（稳定 ID）
    characters: List[Character] = Field(default_factory=list, description="全局角色表")
    locations: List[Location] = Field(default_factory=list, description="全局地点表")
    props: List[Prop] = Field(default_factory=list, description="全局道具表")
    scenes: List[Scene] = Field(default_factory=list, description="全局场景表（可选填充）")

    shots: List[ScriptShotExtraction] = Field(default_factory=list, description="逐镜提取与关联结果")

    consistency: Optional[ScriptConsistencyCheckResult] = Field(
        None,
        description="一致性检查结果（可选，full-process 可回填）",
    )


# ============================================================================
# Studio-aligned extraction draft (name-based; IDs generated by import API)
# ============================================================================

class StudioAssetDraft(BaseModel):
    """Studio 资产草稿（Scene/Prop/Costume）：不含 id，由导入 API 生成。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="名称（同项目内建议唯一）")
    description: str = Field("", description="描述")
    tags: List[str] = Field(default_factory=list, description="标签")
    prompt_template_id: Optional[str] = Field(None, description="提示词模板 ID（可空）")
    view_count: int = Field(1, ge=1, description="计划生成视角图数量")


class StudioCharacterDraft(BaseModel):
    """Studio 角色草稿：不含 id，由导入 API 生成。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="角色名称（同项目内建议唯一）")
    description: str = Field("", description="角色描述")
    tags: List[str] = Field(default_factory=list, description="标签（可选）")
    costume_name: Optional[str] = Field(None, description="服装名称（可选，导入时映射到 costume_id）")
    prop_names: List[str] = Field(default_factory=list, description="角色常用道具名称列表（可选）")


class StudioShotDraftDialogueLine(BaseModel):
    """镜头对白草稿：speaker/target 使用角色 name，导入时映射为 character_id。"""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(0, ge=0, description="镜头内排序")
    text: str = Field(..., description="台词内容")
    line_mode: DialogueLineMode = Field("DIALOGUE", description="对白模式")
    speaker_name: Optional[str] = Field(None, description="说话角色名称（可空）")
    target_name: Optional[str] = Field(None, description="听者角色名称（可空）")


class StudioShotDraft(BaseModel):
    """镜头草稿：不含 shot_id，由导入 API 生成；引用实体用 name。"""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(..., ge=1, description="镜头序号（章节内唯一）")
    title: str = Field(..., description="镜头标题")
    script_excerpt: str = Field("", description="剧本摘录")

    scene_name: Optional[str] = Field(None, description="场景名称（可选）")
    character_names: List[str] = Field(default_factory=list, description="本镜出现角色名称列表")
    prop_names: List[str] = Field(default_factory=list, description="本镜关键道具名称列表")
    costume_names: List[str] = Field(default_factory=list, description="本镜服装名称列表")

    dialogue_lines: List[StudioShotDraftDialogueLine] = Field(default_factory=list, description="对白列表")
    actions: List[str] = Field(default_factory=list, description="动作/场景描述")


class StudioScriptExtractionDraft(BaseModel):
    """用于导入 Studio 的提取结果草稿（name-based）。"""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., description="项目 ID（必填）")
    chapter_id: str = Field(..., description="章节 ID（必填，用于创建 shots/links）")
    script_text: str = Field(..., description="剧本文本（可为优化后版本）")

    characters: List[StudioCharacterDraft] = Field(default_factory=list)
    scenes: List[StudioAssetDraft] = Field(default_factory=list)
    props: List[StudioAssetDraft] = Field(default_factory=list)
    costumes: List[StudioAssetDraft] = Field(default_factory=list)

    shots: List[StudioShotDraft] = Field(default_factory=list, description="镜头草稿列表")


class CostumeTimelineEntry(BaseModel):
    """单角色的服装演变时间线条目。"""

    model_config = ConfigDict(extra="forbid")

    shot_index: int = Field(..., ge=1, description="镜头序号")
    scene_id: Optional[str] = Field(None, description="可选：所属场景稳定ID（若已可推断）")
    costume_note: Optional[str] = Field(None, description="服装/外形要点（简短）")
    changes: List[str] = Field(default_factory=list, description="与上一条相比的变化点")
    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据（可选）")


class CostumeTimeline(BaseModel):
    """单角色的服装演变时间线。"""

    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(..., description="角色稳定ID")
    character_name: str = Field(..., description="角色名称")
    timeline_entries: List[CostumeTimelineEntry] = Field(default_factory=list, description="时间线条目")


class VariantSuggestion(BaseModel):
    """变体建议。"""

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(..., description="实体ID")
    entity_name: str = Field(..., description="实体名称")
    entity_type: str = Field(..., description="实体类型（character/scene/prop/location）")
    suggestion: str = Field(..., description="变体建议说明")
    affected_shots: List[int] = Field(default_factory=list, description="涉及的镜头")
    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据（可选）")


class VariantAnalysisResult(BaseModel):
    """变体分析结果。"""

    model_config = ConfigDict(extra="forbid")

    costume_timelines: List[CostumeTimeline] = Field(default_factory=list, description="各角色服装演变时间线")
    variant_suggestions: List[VariantSuggestion] = Field(default_factory=list, description="变体建议列表")
    chapter_variants: Dict[str, List[str]] = Field(default_factory=dict, description="章节变体建议")
    notes: Optional[str] = Field(None, description="分析说明")


class ConsistencyWarning(BaseModel):
    """单条一致性检查警告。"""

    model_config = ConfigDict(extra="forbid")

    warning_type: str = Field(..., description="警告类型（character_name_conflict/location_inconsistency/等）")
    severity: Literal["low", "medium", "high"] = Field(..., description="严重程度")
    description: str = Field(..., description="问题描述")
    entity_ids: List[str] = Field(default_factory=list, description="涉及的实体ID")
    affected_shots: List[int] = Field(default_factory=list, description="涉及的镜头序号")
    affected_lines: Optional[Dict[str, int]] = Field(
        None,
        description="可选：建议修正的行号范围，形如 {start_line: x, end_line: y}",
    )
    suggestion: Optional[str] = Field(None, description="修正建议")
    evidence: List[EvidenceSpan] = Field(default_factory=list, description="原文依据（可选）")


class ConsistencyCheckResult(BaseModel):
    """一致性检查结果。"""

    model_config = ConfigDict(extra="forbid")

    warnings: List[ConsistencyWarning] = Field(default_factory=list, description="警告列表")
    total_issues: int = Field(..., ge=0, description="问题总数")
    critical_issues: int = Field(..., ge=0, description="严重问题数（high severity）")
    consistency_score: float = Field(..., ge=0, le=100, description="一致性评分（0-100）")
    notes: Optional[str] = Field(None, description="检查说明")


class TableData(BaseModel):
    """可直接导出的表格数据。"""

    model_config = ConfigDict(extra="forbid")

    table_type: str = Field(..., description="表格类型（character_table/location_table/prop_table/shot_table）")
    headers: List[str] = Field(..., description="表头")
    rows: List[List[Any]] = Field(..., description="行数据")
    row_count: int = Field(..., ge=0, description="行数")


class OutputCompileResult(BaseModel):
    """最终输出编译结果。"""

    model_config = ConfigDict(extra="forbid")

    project_json: ProjectCinematicBreakdown = Field(..., description="完整项目JSON（严格 schema）")
    tables: List[TableData] = Field(default_factory=list, description="可导出的表格数据")
    export_stats: Dict[str, Any] = Field(default_factory=dict, description="导出统计信息")
    summary: Optional[str] = Field(None, description="项目总结")