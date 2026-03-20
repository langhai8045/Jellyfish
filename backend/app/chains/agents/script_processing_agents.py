"""脚本处理 Agent：分镜分割、信息提取、实体合并、变体分析、一致性检查、输出编译。"""

from __future__ import annotations

import json
from typing import Any

from app.chains.agents.base import SkillAgentBase, _extract_json_from_text
from app.core.skills_runtime import schemas as sp_schemas

# 统一输出模型来源：严格 schema 在 schemas.py
ShotDivision = sp_schemas.ShotDivision
ScriptDivisionResult = sp_schemas.ScriptDivisionResult
ScriptConsistencyCheckResult = sp_schemas.ScriptConsistencyCheckResult
ScriptOptimizationResult = sp_schemas.ScriptOptimizationResult
StudioScriptExtractionDraft = sp_schemas.StudioScriptExtractionDraft
ShotCharacterInfo = sp_schemas.ShotCharacterInfo
ShotPropInfo = sp_schemas.ShotPropInfo
ShotSceneInfo = sp_schemas.ShotSceneInfo
ShotElements = sp_schemas.ShotElements
ShotElementExtractionResult = sp_schemas.ShotElementExtractionResult
EntityVariant = sp_schemas.EntityVariant
EntityEntry = sp_schemas.EntityEntry
EntityLibrary = sp_schemas.EntityLibrary
EntityMergeResult = sp_schemas.EntityMergeResult
CostumeTimelineEntry = sp_schemas.CostumeTimelineEntry
CostumeTimeline = sp_schemas.CostumeTimeline
VariantSuggestion = sp_schemas.VariantSuggestion
VariantAnalysisResult = sp_schemas.VariantAnalysisResult
ConsistencyWarning = sp_schemas.ConsistencyWarning
ConsistencyCheckResult = sp_schemas.ConsistencyCheckResult
TableData = sp_schemas.TableData
OutputCompileResult = sp_schemas.OutputCompileResult


# ============================================================================
# 1. ScriptDividerAgent - 剧本自动分镜
# ============================================================================

class ScriptDividerAgent(SkillAgentBase[ScriptDivisionResult]):
    """剧本自动分镜：输入完整剧本文本，输出分镜列表。"""

    SCRIPT_DIVIDER_SKILL_IDS = ("script_divider",)

    def load_skill(self, skill_id: str) -> None:
        from app.core.skills_runtime import get_skill_registry

        registry = get_skill_registry()
        if skill_id not in self.SCRIPT_DIVIDER_SKILL_IDS or skill_id not in registry:
            raise ValueError(
                f"Unknown or invalid script_divider skill_id: {skill_id}. "
                f"Allowed: {self.SCRIPT_DIVIDER_SKILL_IDS}"
            )
        self._prompt, self._output_model = registry[skill_id]
        self._skill_id = skill_id
        self._structured_chain = None

    def format_output(self, raw: str) -> ScriptDivisionResult:
        """
        更强的兜底解析：
        LLM 可能输出：
        - 正常结构：{shots:[...], total_shots:N}
        - 包裹结构：{"ScriptDivisionResult": {...}}
        - 直接列表：[{...}, {...}]（视为 shots）
        """
        self._ensure_loaded()
        assert self._output_model is not None

        json_str = _extract_json_from_text(raw)
        data: Any = json.loads(json_str)

        if isinstance(data, list):
            data = {"shots": data}
        elif isinstance(data, dict) and "ScriptDivisionResult" in data:
            inner = data.get("ScriptDivisionResult")
            if isinstance(inner, list):
                data = {"shots": inner}
            elif isinstance(inner, dict):
                data = inner
            else:
                data = {"shots": []}

        if isinstance(data, dict):
            data = self._normalize(data)

        return self._output_model.model_validate(data)  # type: ignore[arg-type]

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化脚本分割结果。"""
        data = dict(data)

        # 兼容：LLM 可能输出 {"ScriptDivisionResult": {...}} 或 {"ScriptDivisionResult": [...]}
        if "ScriptDivisionResult" in data:
            inner = data.get("ScriptDivisionResult")
            if isinstance(inner, list):
                data = {"shots": inner}
            elif isinstance(inner, dict):
                data = dict(inner)
            else:
                data = {"shots": []}

        if "shots" in data and isinstance(data["shots"], list):
            shots = []
            for idx, shot in enumerate(data["shots"]):
                shot_dict: dict[str, Any] = (
                    dict(shot) if isinstance(shot, dict) else {"script_excerpt": str(shot), "shot_name": ""}
                )
                if "index" not in shot_dict:
                    shot_dict["index"] = idx + 1
                # 兼容：LLM 可能用 title/shot_title 代替 shot_name
                if "shot_name" not in shot_dict:
                    if "title" in shot_dict:
                        shot_dict["shot_name"] = str(shot_dict.pop("title"))
                    elif "shot_title" in shot_dict:
                        shot_dict["shot_name"] = str(shot_dict.pop("shot_title"))
                shot_dict.setdefault("shot_name", "")
                # 兼容旧字段：character_ids -> character_names_in_text（此阶段为弱信息）
                if "character_ids" in shot_dict and "character_names_in_text" not in shot_dict:
                    val = shot_dict.get("character_ids")
                    if isinstance(val, list):
                        shot_dict["character_names_in_text"] = [str(x) for x in val]
                    shot_dict.pop("character_ids", None)
                shots.append(shot_dict)
            data["shots"] = shots
        if "total_shots" not in data and "shots" in data:
            data["total_shots"] = len(data["shots"])
        return data


# ============================================================================
# 2. ShotElementExtractorAgent - 逐镜信息提取（兼容旧流程）
# ============================================================================

class ShotElementExtractorAgent(SkillAgentBase[ShotElementExtractionResult]):
    """[兼容] 逐镜信息提取：输入单镜文本+上文摘要，输出该镜的结构化提取结果。"""

    ELEMENT_EXTRACTOR_SKILL_IDS = ("shot_element_extractor",)

    def load_skill(self, skill_id: str) -> None:
        from app.core.skills_runtime import get_skill_registry

        registry = get_skill_registry()
        if skill_id not in self.ELEMENT_EXTRACTOR_SKILL_IDS or skill_id not in registry:
            raise ValueError(
                f"Unknown or invalid element_extractor skill_id: {skill_id}. "
                f"Allowed: {self.ELEMENT_EXTRACTOR_SKILL_IDS}"
            )
        self._prompt, self._output_model = registry[skill_id]
        self._skill_id = skill_id
        self._structured_chain = None

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化元素提取结果（升级版结构）。"""
        data = dict(data)
        # 兼容：缺失 shot_division
        if "shot_division" not in data:
            data["shot_division"] = None
        if "elements" not in data or not isinstance(data["elements"], dict):
            data["elements"] = {}

        elements = data["elements"]

        # 兼容旧字段名：*_ids -> *_keys
        legacy_key_map = {
            "character_ids": "character_keys",
            "scene_ids": "scene_keys",
            "costume_ids": "costume_keys",
            "prop_ids": "prop_keys",
        }
        for old, new in legacy_key_map.items():
            if old in elements and new not in elements:
                val = elements.get(old)
                if isinstance(val, list):
                    elements[new] = [str(x) for x in val]
                elements.pop(old, None)

        # 兼容旧字段名：dialog_lines -> dialogue_lines
        if "dialog_lines" in elements and "dialogue_lines" not in elements:
            elements["dialogue_lines"] = elements.pop("dialog_lines")

        for key in (
            "character_keys",
            "scene_keys",
            "costume_keys",
            "prop_keys",
            "characters_detailed",
            "props_detailed",
            "dialogue_lines",
            "actions",
            "shot_type_hints",
        ):
            if key not in elements or not isinstance(elements[key], list):
                elements[key] = []

        if "scene_detailed" not in elements:
            elements["scene_detailed"] = None
        elif elements["scene_detailed"] is not None and not isinstance(elements["scene_detailed"], dict):
            elements["scene_detailed"] = None

        if "confidence_breakdown" not in elements or not isinstance(elements["confidence_breakdown"], dict):
            elements["confidence_breakdown"] = {}

        # 兼容旧结构：characters_detailed/props_detailed/scene_detailed 里字段名 *_id -> *_key
        for c in elements.get("characters_detailed", []) or []:
            if isinstance(c, dict) and "character_id" in c and "character_key" not in c:
                c["character_key"] = str(c.pop("character_id"))
            if isinstance(c, dict) and "evidence" not in c:
                c["evidence"] = []
        for p in elements.get("props_detailed", []) or []:
            if isinstance(p, dict) and "prop_id" in p and "prop_key" not in p:
                p["prop_key"] = str(p.pop("prop_id"))
            if isinstance(p, dict) and "evidence" not in p:
                p["evidence"] = []
        sd = elements.get("scene_detailed")
        if isinstance(sd, dict) and "scene_id" in sd and "scene_key" not in sd:
            sd["scene_key"] = str(sd.pop("scene_id"))
        if isinstance(sd, dict) and "evidence" not in sd:
            sd["evidence"] = []

        # 兼容旧对白行结构：补齐 schemas.DialogueLine 的可选字段
        dl = elements.get("dialogue_lines")
        if isinstance(dl, list):
            for line in dl:
                if not isinstance(line, dict):
                    continue
                if "index" not in line and "order" in line:
                    line["index"] = line.pop("order")
                if "evidence" not in line:
                    line["evidence"] = []
                # 确保 line_mode 合法字符串（由 schema Literal 校验）
                if "line_mode" not in line:
                    line["line_mode"] = "DIALOGUE"

        data["elements"] = elements

        if "confidence" not in data:
            data["confidence"] = None

        return data


# ============================================================================
# 2b. ElementExtractorAgent - 项目级信息提取（新流程最终输出）
# ============================================================================

class ElementExtractorAgent(SkillAgentBase[StudioScriptExtractionDraft]):
    """项目级信息提取（最终输出）：输入剧本文本 + 分镜结果，产出全局实体表 + 逐镜关联。"""

    PROJECT_EXTRACTOR_SKILL_IDS = ("script_extractor",)

    def load_skill(self, skill_id: str) -> None:
        from app.core.skills_runtime import get_skill_registry

        registry = get_skill_registry()
        if skill_id not in self.PROJECT_EXTRACTOR_SKILL_IDS or skill_id not in registry:
            raise ValueError(
                f"Unknown or invalid script_extractor skill_id: {skill_id}. "
                f"Allowed: {self.PROJECT_EXTRACTOR_SKILL_IDS}"
            )
        self._prompt, self._output_model = registry[skill_id]
        self._skill_id = skill_id
        self._structured_chain = None

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        data.setdefault("project_id", "")
        data.setdefault("chapter_id", "")
        data.setdefault("script_text", "")
        for k in ("characters", "scenes", "props", "costumes", "shots"):
            if k not in data or not isinstance(data[k], list):
                data[k] = []
        return data


# ============================================================================
# 3. EntityMergerAgent - 跨镜静态合并 + 基础画像生成
# ============================================================================

class EntityMergerAgent(SkillAgentBase[EntityMergeResult]):
    """跨镜合并 + 基础画像生成：输入全部分镜提取结果+历史实体库，输出合并后的库。"""

    ENTITY_MERGER_SKILL_IDS = ("entity_merger",)

    def load_skill(self, skill_id: str) -> None:
        from app.core.skills_runtime import get_skill_registry

        registry = get_skill_registry()
        if skill_id not in self.ENTITY_MERGER_SKILL_IDS or skill_id not in registry:
            raise ValueError(
                f"Unknown or invalid entity_merger skill_id: {skill_id}. "
                f"Allowed: {self.ENTITY_MERGER_SKILL_IDS}"
            )
        self._prompt, self._output_model = registry[skill_id]
        self._skill_id = skill_id
        self._structured_chain = None

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化实体合并结果。"""
        data = dict(data)
        if "merged_library" not in data:
            data["merged_library"] = {
                "characters": [],
                "locations": [],
                "scenes": [],
                "props": [],
                "total_entries": 0,
            }
        lib = data["merged_library"]
        # 兼容旧字段：缺 locations 时补空；旧结构可能没有 scenes
        if "locations" not in lib:
            lib["locations"] = []
        if "scenes" not in lib:
            lib["scenes"] = []
        if "total_entries" not in lib:
            lib["total_entries"] = sum(
                len(lib.get(k, []) or [])
                for k in ("characters", "locations", "scenes", "props")
            )
        # 兼容旧 variants 结构：dict[] -> EntityVariant[]（最小补齐）
        for bucket_name in ("characters", "locations", "scenes", "props"):
            bucket = lib.get(bucket_name)
            if not isinstance(bucket, list):
                continue
            for ent in bucket:
                if not isinstance(ent, dict):
                    continue
                if "variants" in ent and isinstance(ent["variants"], list):
                    new_vars = []
                    for v in ent["variants"]:
                        if isinstance(v, dict):
                            if "variant_key" not in v:
                                v["variant_key"] = v.get("id") or v.get("key") or "variant"
                            if "affected_shots" not in v:
                                v["affected_shots"] = []
                            if "evidence" not in v:
                                v["evidence"] = []
                            new_vars.append(v)
                        else:
                            new_vars.append(
                                {
                                    "variant_key": "variant",
                                    "description": str(v),
                                    "affected_shots": [],
                                    "evidence": [],
                                }
                            )
                    ent["variants"] = new_vars
        if "merge_stats" not in data:
            data["merge_stats"] = {}
        if "conflicts" not in data or not isinstance(data["conflicts"], list):
            data["conflicts"] = []
        return data


# ============================================================================
# 4. VariantAnalyzerAgent - 服装/外形变体检测与建议
# ============================================================================

class VariantAnalyzerAgent(SkillAgentBase[VariantAnalysisResult]):
    """服装/外形变体检测与建议：输入实体库+全镜提取，输出变体分析结果。"""

    VARIANT_ANALYZER_SKILL_IDS = ("variant_analyzer",)

    def load_skill(self, skill_id: str) -> None:
        from app.core.skills_runtime import get_skill_registry

        registry = get_skill_registry()
        if skill_id not in self.VARIANT_ANALYZER_SKILL_IDS or skill_id not in registry:
            raise ValueError(
                f"Unknown or invalid variant_analyzer skill_id: {skill_id}. "
                f"Allowed: {self.VARIANT_ANALYZER_SKILL_IDS}"
            )
        self._prompt, self._output_model = registry[skill_id]
        self._skill_id = skill_id
        self._structured_chain = None

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化变体分析结果。"""
        data = dict(data)
        if "costume_timelines" not in data or not isinstance(data["costume_timelines"], list):
            data["costume_timelines"] = []
        if "variant_suggestions" not in data or not isinstance(data["variant_suggestions"], list):
            data["variant_suggestions"] = []
        if "chapter_variants" not in data or not isinstance(data["chapter_variants"], dict):
            data["chapter_variants"] = {}
        # 补齐可选 evidence 字段，避免 strict schema 校验失败
        for tl in data.get("costume_timelines", []) or []:
            if not isinstance(tl, dict):
                continue
            entries = tl.get("timeline_entries")
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict) and "evidence" not in e:
                        e["evidence"] = []
        for s in data.get("variant_suggestions", []) or []:
            if isinstance(s, dict) and "evidence" not in s:
                s["evidence"] = []
        return data


# ============================================================================
# 5. ConsistencyCheckerAgent - 文本一致性检查
# ============================================================================

class ConsistencyCheckerAgent(SkillAgentBase[ScriptConsistencyCheckResult]):
    """一致性检查（角色混淆）：输入原文，检测同一角色身份/行为混淆并给出修改建议。"""

    CONSISTENCY_CHECKER_SKILL_IDS = ("consistency_checker",)

    def load_skill(self, skill_id: str) -> None:
        from app.core.skills_runtime import get_skill_registry

        registry = get_skill_registry()
        if skill_id not in self.CONSISTENCY_CHECKER_SKILL_IDS or skill_id not in registry:
            raise ValueError(
                f"Unknown or invalid consistency_checker skill_id: {skill_id}. "
                f"Allowed: {self.CONSISTENCY_CHECKER_SKILL_IDS}"
            )
        self._prompt, self._output_model = registry[skill_id]
        self._skill_id = skill_id
        self._structured_chain = None

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化一致性检查结果（角色混淆）。"""
        data = dict(data)
        if "issues" not in data or not isinstance(data["issues"], list):
            data["issues"] = []
        for it in data["issues"]:
            if isinstance(it, dict):
                it.setdefault("issue_type", "character_confusion")
                it.setdefault("character_candidates", [])
                it.setdefault("affected_lines", None)
                it.setdefault("evidence", [])
        if "has_issues" not in data:
            data["has_issues"] = len(data["issues"]) > 0
        if "summary" not in data:
            data["summary"] = None
        return data


class ScriptOptimizerAgent(SkillAgentBase[ScriptOptimizationResult]):
    """剧本优化 Agent：输入一致性检查输出 + 原文，输出优化后的剧本。"""

    SCRIPT_OPTIMIZER_SKILL_IDS = ("script_optimizer",)

    def load_skill(self, skill_id: str) -> None:
        from app.core.skills_runtime import get_skill_registry

        registry = get_skill_registry()
        if skill_id not in self.SCRIPT_OPTIMIZER_SKILL_IDS or skill_id not in registry:
            raise ValueError(
                f"Unknown or invalid script_optimizer skill_id: {skill_id}. "
                f"Allowed: {self.SCRIPT_OPTIMIZER_SKILL_IDS}"
            )
        self._prompt, self._output_model = registry[skill_id]
        self._skill_id = skill_id
        self._structured_chain = None

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        if "optimized_script_text" not in data:
            data["optimized_script_text"] = ""
        if "change_summary" not in data:
            data["change_summary"] = ""
        return data


# ============================================================================
# 6. OutputCompilerAgent - 最终输出打包
# ============================================================================

class OutputCompilerAgent(SkillAgentBase[OutputCompileResult]):
    """最终输出打包：输入所有Agent状态，输出完整项目JSON + 表格数据。"""

    OUTPUT_COMPILER_SKILL_IDS = ("output_compiler",)

    def load_skill(self, skill_id: str) -> None:
        from app.core.skills_runtime import get_skill_registry

        registry = get_skill_registry()
        if skill_id not in self.OUTPUT_COMPILER_SKILL_IDS or skill_id not in registry:
            raise ValueError(
                f"Unknown or invalid output_compiler skill_id: {skill_id}. "
                f"Allowed: {self.OUTPUT_COMPILER_SKILL_IDS}"
            )
        self._prompt, self._output_model = registry[skill_id]
        self._skill_id = skill_id
        self._structured_chain = None

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化输出编译结果。"""
        data = dict(data)
        # 严格输出：project_json 必须能被 ProjectCinematicBreakdown 校验
        if "project_json" not in data or not isinstance(data["project_json"], dict):
            data["project_json"] = {}
        pj = data["project_json"]
        if isinstance(pj, dict):
            # 补齐 ProjectCinematicBreakdown 必填字段
            pj.setdefault("source_id", "unknown_source")
            pj.setdefault("chunks", [])
            pj.setdefault("characters", [])
            pj.setdefault("locations", [])
            pj.setdefault("props", [])
            pj.setdefault("scenes", [])
            pj.setdefault("shots", [])
            pj.setdefault("transitions", [])
            pj.setdefault("notes", [])
            pj.setdefault("uncertainties", [])
        if "tables" not in data or not isinstance(data["tables"], list):
            data["tables"] = []
        if "export_stats" not in data or not isinstance(data["export_stats"], dict):
            data["export_stats"] = {
                "total_tables": len(data["tables"]),
                "total_rows": sum(t.get("row_count", 0) for t in data["tables"]),
            }
        return data

