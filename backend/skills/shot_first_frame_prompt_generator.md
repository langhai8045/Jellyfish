# 镜头分镜首帧提示词生成

## 目标

根据镜头信息（剧本摘录、景别、机位、运镜、氛围、对白等）生成**首帧画面提示词**，用于后续首帧图像生成，结果可写入 `app.models.studio.ShotDetail.first_frame_prompt`。

## 输入

与 Shot + ShotDetail 对齐：`script_excerpt`、`title`、`camera_shot`、`angle`、`movement`、`atmosphere`、`mood_tags`、`vfx_type`、`vfx_note`、`duration`、`scene_id`（可选）、`dialog_summary`（可选）等。

## 输出

单个中文字符串 `prompt`，即首帧画面描述提示词，可直接写入 `ShotDetail.first_frame_prompt`。

## 实现与调用

- **技能定义**：`app.core.skills_runtime.shot_frame_prompt_generator`（首帧）
- **Agent**：`app.chains.agents.shot_frame_prompt_agents.ShotFirstFramePromptAgent`
