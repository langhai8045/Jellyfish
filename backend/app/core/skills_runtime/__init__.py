"""影视技能定义：数据结构（schemas）、技能实现（prompt + 输出模型）与技能注册表。

- 数据结构与枚举见 schemas。
- 技能说明文档在 backend/skills/*.md。
- 仅维护 skill 定义与 SKILL_REGISTRY；skill 加载与 agent 运行逻辑在 app.chains.agents。
"""

from pydantic import BaseModel

from app.core.skills_runtime.schemas import (
    Character,
    EvidenceSpan,
    Location,
    Prop,
    ProjectCinematicBreakdown,
    Scene,
    Shot,
    Transition,
    Uncertainty,
)
from app.core.skills_runtime.film_entity_extractor import (
    FILM_ENTITY_EXTRACTION_PROMPT,
    FilmEntityExtractionResult,
    TextChunk,
)
from app.core.skills_runtime.film_shotlist_storyboarder import (
    FILM_SHOTLIST_PROMPT,
    FilmShotlistResult,
)
from app.core.skills_runtime.shot_frame_prompt_generator import (
    SHOT_FIRST_FRAME_PROMPT,
    SHOT_LAST_FRAME_PROMPT,
    SHOT_KEY_FRAME_PROMPT,
    ShotFramePromptInput,
    ShotFramePromptResult,
)

from langchain_core.prompts import PromptTemplate

# ============================================================================
# Script Processing Skills Prompts
# ============================================================================

_SCRIPT_DIVIDER_INSTRUCTIONS = """\
你是"剧本分镜师"。将完整剧本分割为多个镜头。每个镜头应是完整的连贯场景。
为每个镜头提供：
- index（镜头序号，章节内唯一；从 1 开始）
- start_line、end_line
- shot_name（镜头名称/镜头标题，分镜名；一句话描述该镜头画面/动作；不要把它当作场景名）
- script_excerpt（镜头对应的剧本摘录/文本）
- scene_name（场景名称，必须与 shots 中 scene_name 的含义一致；不要把 shot_name 当成 scene_name）
- time_of_day
- character_names_in_text（角色名/称呼，弱信息；稳定ID会在后续合并阶段统一分配）
严格区分字段含义：
- shot_name = 分镜名/镜头标题
- scene_name = 场景名
只输出 JSON，符合 ScriptDivisionResult 结构。
"""

SCRIPT_DIVIDER_PROMPT = PromptTemplate(
    input_variables=["script_text"],
    template="{instructions}\n\n## 输入脚本\n{script_text}\n\n## 输出\n",
    partial_variables={"instructions": _SCRIPT_DIVIDER_INSTRUCTIONS},
)

_ELEMENT_EXTRACTOR_INSTRUCTIONS = """\
你是"镜头元素提取员"。从单个镜头提取关键信息：
- character_keys、scene_keys、costume_keys、prop_keys（弱ID/归一化名；稳定ID由后续合并阶段统一分配）
- characters_detailed（每个角色含 character_key/name_in_text/appearance/clothing/accessories/state + raw_* 溯源，可选 evidence）
- props_detailed（每个道具含 prop_key/name_in_text/description/state/interaction + raw_text，可选 evidence）
- scene_detailed（scene_key/name/location_detail/atmosphere/time_weather/raw_description_text，可选 evidence）
- dialogue_lines（结构化对白，字段与 schemas.DialogueLine 对齐）
- actions、shot_type_hints、confidence_breakdown
其中 dialogue_lines 每项必须包含 text/line_mode；建议包含 index/speaker_character_id/target_character_id（若可判定）。
严格按照原文，不要编造。只输出 JSON，符合 ShotElementExtractionResult 结构。
"""

ELEMENT_EXTRACTOR_PROMPT = PromptTemplate(
    input_variables=["index", "shot_text", "context_summary", "shot_division_json"],
    template="{instructions}\n\n镜头号: {index}\n分镜元信息(来自上一步): {shot_division_json}\n上文: {context_summary}\n\n## 镜头文本\n{shot_text}\n\n## 输出\n",
    partial_variables={"instructions": _ELEMENT_EXTRACTOR_INSTRUCTIONS},
)

_ENTITY_MERGER_INSTRUCTIONS = """\
你是"实体合并师"。合并多镜头提取结果，统一实体定义，为每个实体分配ID，识别变体和冲突。
请输出 EntityMergeResult，merged_library 中至少包含 characters/locations/scenes/props 四类。
每个实体条目（EntityEntry）需包含：
- 通用：id/name/type/description/aliases/normalized_name/confidence/first_appearance/evidence/first_shot/appearances/variants
- 角色（type=character）：尽量补充 costume_note、traits
- 地点（type=location）：尽量补充 location_type
- 道具（type=prop）：尽量补充 category、owner_character_id
variants 使用 {variant_key, description, affected_shots, evidence} 的最小结构。
当提供 previous_merge_json 与 conflict_resolutions_json 时，表示这是一次“重试合并”：你必须参考上一次的合并结果与冲突解决建议，优先消解 conflicts；必要时可调整实体合并/拆分策略，但要保持 ID 尽量稳定（除非建议明确要求变更）。
只输出 JSON，符合 EntityMergeResult 结构。
"""

ENTITY_MERGER_PROMPT = PromptTemplate(
    input_variables=[
        "all_extractions_json",
        "historical_library_json",
        "script_division_json",
        "previous_merge_json",
        "conflict_resolutions_json",
    ],
    template=(
        "{instructions}\n\n"
        "## 脚本分镜(来自上一步)\n{script_division_json}\n\n"
        "## 所有镜头提取结果\n{all_extractions_json}\n\n"
        "## 历史实体库\n{historical_library_json}\n\n"
        "## 上一次合并结果（可选，用于重试）\n{previous_merge_json}\n\n"
        "## 冲突解决建议（可选，用于重试）\n{conflict_resolutions_json}\n\n"
        "## 输出\n"
    ),
    partial_variables={"instructions": _ENTITY_MERGER_INSTRUCTIONS},
)

_VARIANT_ANALYZER_INSTRUCTIONS = """\
你是"变体分析师"。分析实体变体（特别是角色服装变化），构建时间线，生成变体建议。
输出 VariantAnalysisResult：costume_timelines.timeline_entries 使用 {shot_index, scene_id, costume_note, changes, evidence}；variant_suggestions 可带 evidence。
只输出 JSON，符合 VariantAnalysisResult 结构。
"""

VARIANT_ANALYZER_PROMPT = PromptTemplate(
    input_variables=["merged_library_json", "all_extractions_json", "script_division_json"],
    template="{instructions}\n\n## 脚本分镜(来自上一步)\n{script_division_json}\n\n## 合并后的实体库\n{merged_library_json}\n\n## 所有镜头提取结果\n{all_extractions_json}\n\n## 输出\n",
    partial_variables={"instructions": _VARIANT_ANALYZER_INSTRUCTIONS},
)

_CONSISTENCY_CHECKER_INSTRUCTIONS = """\
你是"一致性检查员"。只做一件事：检测原文中是否把“同一个角色”在不同段落/镜头中赋予了不同的身份或行为主体，导致角色混淆（例如：同名不同人、代词指代混乱、行为归属错位）。

输出 ScriptConsistencyCheckResult：
- issues: 每条问题必须包含 character_candidates、description、suggestion；尽量给出 affected_lines（start_line/end_line）。
- has_issues: issues 非空则为 true

只输出 JSON。
"""

CONSISTENCY_CHECKER_PROMPT = PromptTemplate(
    input_variables=["script_text"],
    template="{instructions}\n\n## 原文剧本\n{script_text}\n\n## 输出\n",
    partial_variables={"instructions": _CONSISTENCY_CHECKER_INSTRUCTIONS},
)

_SCRIPT_OPTIMIZER_INSTRUCTIONS = """\
你是\"剧本优化师\"。仅当一致性检查发现角色混淆问题时，对原文进行最小改写以消除混淆。

输入：
- script_text：原文
- consistency_json：一致性检查输出（ScriptConsistencyCheckResult）

输出 ScriptOptimizationResult：
- optimized_script_text：优化后的完整剧本文本（尽量少改，只改与 issues 相关的段落）
- change_summary：逐条对应 issues 的改动摘要

只输出 JSON。
"""

SCRIPT_OPTIMIZER_PROMPT = PromptTemplate(
    input_variables=["script_text", "consistency_json"],
    template="{instructions}\n\n## 一致性检查结果\n{consistency_json}\n\n## 原文剧本\n{script_text}\n\n## 输出\n",
    partial_variables={"instructions": _SCRIPT_OPTIMIZER_INSTRUCTIONS},
)

_SCRIPT_EXTRACTOR_INSTRUCTIONS = """\
你是\"Studio 信息提取员\"。你的任务是：基于剧本文本与分镜结果，输出可直接导入 Studio 的草稿结构 StudioScriptExtractionDraft（注意：ID 由导入 API 生成，因此这里全部使用 name 做引用键）。

输出 StudioScriptExtractionDraft：
- project_id（必填）
- chapter_id（必填）
- script_text（必填）
- characters: [{name, description, costume_name?, prop_names[], tags[]}]
- scenes/props/costumes: [{name, description, tags[], prompt_template_id?, view_count}]
- shots: [{index, title, script_excerpt, scene_name?, character_names[], prop_names[], costume_names[], dialogue_lines[], actions[]}]
  - dialogue_lines: [{index, text, line_mode, speaker_name?, target_name?}]

强约束：
- 同名实体在输出中只出现一次（全局去重）；shots 中引用必须使用同一名称
- shots.index 必须覆盖并对应输入分镜中的 index（不要跳号）
- 不要输出任何 id 字段（包括 char_001 等），由导入 API 生成

一致性强约束（必须严格遵守，否则导入会失败）：
- 先输出全局 characters/scenes/props/costumes 列表，再输出 shots；并把它们视为“字典”。
- shots[*].character_names / prop_names / costume_names / scene_name 只能从对应全局列表的 name 中选择（完全一致的字符串），禁止生成任何未在全局列表中出现的新名字。
- 禁止“同义名/括号变体/临时称呼”漂移：例如禁止在 shots 中写「女子（群）」但在 characters 中没有该条目；禁止「仙女A」与「仙女 A」混用。
- 遇到群体角色/泛指角色（如“女子（群）”“群众”“村民们”）：必须在 characters 列表中创建一条同名角色（name 完全一致），并在 shots 中引用该 name。
- 对于难以确定是否同一角色的称呼：宁可在 characters 里拆成两条不同 name，也不要在 shots 中凭空换名。
- 输出 shots 之前，必须做“全集校验”并补齐缺失：所有 shots[*] 中出现的 character_names/prop_names/costume_names/scene_name 的名字集合，必须都能在对应全局列表（characters/props/costumes/scenes）的 name 中找到；如果有缺失，必须在全局列表中补齐对应条目（描述可最小化，但 name 必须完全一致），禁止用别名替换来绕过。
- 角色名/场景名必须原样保留字符细节：包括全角/半角括号、空格、标点，不要自动做任何规范化或替换（例如不能把「女子（群）」改成「女子(群)」或「女子 （群）」）。
- 严格区分：shots[*].title 是“镜头标题”（一句话描述该镜头画面/动作），不要拿它当作 scenes 的 scene 名；shots[*].scene_name 才是场景名称，必须来自 scenes 全局列表的 name。

输入：
- project_id
- chapter_id
- script_text
- script_division_json（ScriptDivisionResult）
- consistency_json（可选）

只输出 JSON。
"""

SCRIPT_EXTRACTOR_PROMPT = PromptTemplate(
    input_variables=["project_id", "chapter_id", "script_text", "script_division_json", "consistency_json"],
    template=(
        "{instructions}\n\n"
        "## project_id\n{project_id}\n\n"
        "## chapter_id\n{chapter_id}\n\n"
        "## 一致性检查（可选）\n{consistency_json}\n\n"
        "## 分镜结果\n{script_division_json}\n\n"
        "## 剧本文本\n{script_text}\n\n"
        "## 输出\n"
    ),
    partial_variables={"instructions": _SCRIPT_EXTRACTOR_INSTRUCTIONS},
)

_OUTPUT_COMPILER_INSTRUCTIONS = """\
你是"输出编译员"。汇总所有Agent输出，生成完整项目JSON、可导出表格、项目总结。
输出 OutputCompileResult，其中 project_json 必须严格符合 ProjectCinematicBreakdown schema（至少包含 source_id/chunks/characters/locations/props/scenes/shots/transitions/notes/uncertainties）。
只输出 JSON。
"""

OUTPUT_COMPILER_PROMPT = PromptTemplate(
    input_variables=["script_division_json", "element_extractions_json", "entity_merge_json", "variant_analysis_json", "consistency_check_json"],
    template="{instructions}\n\n## 脚本分镜\n{script_division_json}\n\n## 元素提取\n{element_extractions_json}\n\n## 实体合并\n{entity_merge_json}\n\n## 变体分析\n{variant_analysis_json}\n\n## 一致性检查\n{consistency_check_json}\n\n## 输出\n",
    partial_variables={"instructions": _OUTPUT_COMPILER_INSTRUCTIONS},
)

# 技能注册表：skill_id -> (PromptTemplate, 输出 Pydantic 类型)
def _build_skill_registry() -> dict[str, tuple[PromptTemplate, type[BaseModel] | None]]:
    """构建基础 registry；script-processing 模型稍后按需补全。"""
    registry = {
        "film_entity_extractor": (FILM_ENTITY_EXTRACTION_PROMPT, FilmEntityExtractionResult),
        "film_shotlist": (FILM_SHOTLIST_PROMPT, FilmShotlistResult),
        "shot_first_frame_prompt": (SHOT_FIRST_FRAME_PROMPT, ShotFramePromptResult),
        "shot_last_frame_prompt": (SHOT_LAST_FRAME_PROMPT, ShotFramePromptResult),
        "shot_key_frame_prompt": (SHOT_KEY_FRAME_PROMPT, ShotFramePromptResult),
        "script_divider": (SCRIPT_DIVIDER_PROMPT, None),
        "shot_element_extractor": (ELEMENT_EXTRACTOR_PROMPT, None),
        "entity_merger": (ENTITY_MERGER_PROMPT, None),
        "variant_analyzer": (VARIANT_ANALYZER_PROMPT, None),
        "consistency_checker": (CONSISTENCY_CHECKER_PROMPT, None),
        "script_optimizer": (SCRIPT_OPTIMIZER_PROMPT, None),
        "script_extractor": (SCRIPT_EXTRACTOR_PROMPT, None),
        "output_compiler": (OUTPUT_COMPILER_PROMPT, None),
    }
    return registry

_skill_registry_cache: dict[str, tuple[PromptTemplate, type[BaseModel] | None]] | None = None

def _hydrate_script_processing_skills(
    registry: dict[str, tuple[PromptTemplate, type[BaseModel] | None]],
) -> dict[str, tuple[PromptTemplate, type[BaseModel] | None]]:
    """尽力补全 script-processing skills 的输出模型。

    首次 import 期间可能因循环依赖拿不到这些模型，此函数允许后续再次尝试，
    一旦 import 成功就会原地更新同一个 registry dict。
    """
    needs_hydration = any(
        registry[skill_id][1] is None
        for skill_id in (
            "script_divider",
            "shot_element_extractor",
            "entity_merger",
            "variant_analyzer",
            "consistency_checker",
            "script_optimizer",
            "script_extractor",
            "output_compiler",
        )
    )
    if not needs_hydration:
        return registry

    try:
        from app.chains.agents.script_processing_agents import (
            ScriptConsistencyCheckResult,
            ScriptOptimizationResult,
            StudioScriptExtractionDraft,
            EntityMergeResult,
            OutputCompileResult,
            ScriptDivisionResult,
            ShotElementExtractionResult,
            VariantAnalysisResult,
        )
    except ImportError:
        return registry

    registry["script_divider"] = (SCRIPT_DIVIDER_PROMPT, ScriptDivisionResult)
    registry["shot_element_extractor"] = (ELEMENT_EXTRACTOR_PROMPT, ShotElementExtractionResult)
    registry["entity_merger"] = (ENTITY_MERGER_PROMPT, EntityMergeResult)
    registry["variant_analyzer"] = (VARIANT_ANALYZER_PROMPT, VariantAnalysisResult)
    registry["consistency_checker"] = (CONSISTENCY_CHECKER_PROMPT, ScriptConsistencyCheckResult)
    registry["script_optimizer"] = (SCRIPT_OPTIMIZER_PROMPT, ScriptOptimizationResult)
    registry["script_extractor"] = (SCRIPT_EXTRACTOR_PROMPT, StudioScriptExtractionDraft)
    registry["output_compiler"] = (OUTPUT_COMPILER_PROMPT, OutputCompileResult)
    return registry


def get_skill_registry() -> dict[str, tuple[PromptTemplate, type[BaseModel] | None]]:
    """获取并按需补全 skill registry。"""
    global _skill_registry_cache
    if _skill_registry_cache is None:
        _skill_registry_cache = _build_skill_registry()
    return _hydrate_script_processing_skills(_skill_registry_cache)


SKILL_REGISTRY = get_skill_registry()

__all__ = [
    # schemas
    "Character",
    "EvidenceSpan",
    "Location",
    "Prop",
    "ProjectCinematicBreakdown",
    "Scene",
    "Shot",
    "Transition",
    "Uncertainty",
    # film entity extraction
    "FILM_ENTITY_EXTRACTION_PROMPT",
    "FilmEntityExtractionResult",
    "TextChunk",
    # film shotlist
    "FILM_SHOTLIST_PROMPT",
    "FilmShotlistResult",
    # shot frame prompt generator
    "SHOT_FIRST_FRAME_PROMPT",
    "SHOT_LAST_FRAME_PROMPT",
    "SHOT_KEY_FRAME_PROMPT",
    "ShotFramePromptInput",
    "ShotFramePromptResult",
    # script processing skills
    "SCRIPT_DIVIDER_PROMPT",
    "ELEMENT_EXTRACTOR_PROMPT",
    "ENTITY_MERGER_PROMPT",
    "VARIANT_ANALYZER_PROMPT",
    "CONSISTENCY_CHECKER_PROMPT",
    "OUTPUT_COMPILER_PROMPT",
    # registry
    "SKILL_REGISTRY",
]
