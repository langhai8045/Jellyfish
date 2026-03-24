/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShotFrameType } from './ShotFrameType';
/**
 * 镜头分镜帧图片生成请求体：只根据 `shot_id + frame_type` 定位 ShotFrameImage。
 *
 * 用于替代旧接口中通过 `image_id` 直接传入 ShotFrameImage.id 的方式。
 */
export type ShotFrameImageTaskRequest = {
    /**
     * 可选模型 ID（models.id）；不传则使用 ModelSettings.default_image_model_id；Provider 由模型关联反查
     */
    model_id?: (string | null);
    /**
     * first | last | key
     */
    frame_type: ShotFrameType;
};

