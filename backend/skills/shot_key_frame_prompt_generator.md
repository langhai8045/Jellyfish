# 镜头分镜关键帧提示词生成

## 目标

根据镜头信息生成**关键帧画面提示词**，用于后续关键帧图像生成，结果可写入 `app.models.studio.ShotDetail.key_frame_prompt`。

## 输入

与 Shot + ShotDetail 对齐（同首/尾帧）：`script_excerpt`、`title`、`camera_shot`、`angle`、`movement`、`atmosphere`、`mood_tags`、`vfx_type`、`vfx_note`、`duration`、`scene_id`、`dialog_summary` 等。

## 输出

单个中文字符串 `prompt`，即关键帧画面描述提示词，可直接写入 `ShotDetail.key_frame_prompt`。

## 实现与调用

- **技能定义**：`app.core.skills_runtime.shot_frame_prompt_generator`（关键帧）
- **Agent**：`app.chains.agents.shot_frame_prompt_agents.ShotKeyFramePromptAgent`
