"""Isaac RGB-D capture, AnyGrasp inference, and candidate diagnostics."""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace

import numpy as np
from isaaclab.sensors import Camera

from scale_bench.config.models.robot import RobotConfig
from scale_bench.config.models.scene import SceneConfig
from scale_bench.skills.context import GraspCandidate
from scale_bench.skills.errors import SkillError
from scale_bench.skills.geometry import (
    compose_pose,
    normalize_quaternion_xyzw,
    relative_pose,
    rotate_vector_xyzw,
)
from scale_bench.skills.models import (
    Arm,
    Pose,
)

from .anygrasp import AnyGraspClient, AnyGraspDetection, AnyGraspServiceError
from .anygrasp_diagnostics import (
    AnyGraspCandidateStatus,
    AnyGraspDiagnostics,
    AnyGraspPoseDiagnostic,
)
from .environment import ScaleBenchEnv

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ValidAnyGraspCandidate:
    detection_index: int
    score: float
    width_m: float
    tcp_position_object_m: tuple[float, float, float]
    candidate: GraspCandidate


@dataclass(frozen=True, slots=True)
class _AnyGraspCapture:
    rgb: np.ndarray
    depth_m: np.ndarray
    intrinsic_matrix_px: np.ndarray
    camera_position_env_m: tuple[float, float, float]
    camera_orientation_env_xyzw: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class _AnyGraspInference:
    capture: _AnyGraspCapture
    target_points_env_m: tuple[tuple[float, float, float], ...]
    detections: tuple[AnyGraspDetection, ...]


class AnyGraspSource:
    """Generate candidates without stepping physics or recording camera captures."""

    def __init__(
        self,
        env: ScaleBenchEnv,
        object_sizes_m: Mapping[str, tuple[float, float, float]],
        scene_config: SceneConfig,
        robot_configs: Mapping[Arm, RobotConfig],
        *,
        env_id: int,
    ) -> None:
        if env_id < 0 or env_id >= env.num_envs:
            raise ValueError(f"env_id must be in [0, {env.num_envs})")
        self._env = env
        self._object_sizes_m = object_sizes_m
        self._env_id = env_id
        self._scene_table_top_z_m = scene_config.table_top_z_m
        self._gripper_configs = {
            arm: robot_config.gripper for arm, robot_config in robot_configs.items()
        }
        self._arm_base_positions_env_m = {
            arm: (*mount.position_xy_m, scene_config.table_top_z_m)
            for arm, mount in (
                ("left", scene_config.robot_mounts.left),
                ("right", scene_config.robot_mounts.right),
            )
        }
        if scene_config.anygrasp is None:
            raise ValueError("AnyGrasp requires an AnyGrasp scene configuration")
        self._anygrasp_config = scene_config.anygrasp
        self._anygrasp_client = AnyGraspClient(self._anygrasp_config)

    def analyze(
        self,
        object_name: str,
        arm: Arm,
        object_pose_env: Pose,
    ) -> AnyGraspDiagnostics:
        """Share one inference and geometry analysis between execution and diagnostics."""

        object_position_env_m = object_pose_env.position_m
        object_orientation_env_xyzw = object_pose_env.orientation_xyzw
        inference = self._infer_anygrasp(
            object_name,
            arm,
            object_position_env_m,
            object_orientation_env_xyzw,
        )
        return self._analyze_anygrasp(
            object_name,
            arm,
            object_position_env_m,
            object_orientation_env_xyzw,
            inference,
        )

    def _infer_anygrasp(
        self,
        object_name: str,
        arm: Arm,
        object_position_env_m: tuple[float, float, float],
        object_orientation_env_xyzw: tuple[float, float, float, float],
    ) -> _AnyGraspInference:
        """Capture the task-directed RGB-D view and submit one inference request."""

        config = self._anygrasp_config
        client = self._anygrasp_client
        capture = self._capture_anygrasp_input(
            object_position_env_m,
            arm,
            config.capture_distance_m,
            config.capture_elevation_deg,
            config.capture_azimuth_offset_deg,
        )
        masked_depth, target_points_env_m = self._mask_anygrasp_target(
            object_name,
            object_position_env_m,
            object_orientation_env_xyzw,
            capture,
        )
        capture_view = "arm_side_oblique"
        oblique_target_point_count = len(target_points_env_m)
        if oblique_target_point_count < config.minimum_target_points:
            LOGGER.warning(
                "oblique view has %d target points; retrying from overhead",
                oblique_target_point_count,
                extra={
                    "event": "CAMERA",
                    "event_fields": {
                        "env_id": self._env_id,
                        "object": object_name,
                        "arm": arm,
                        "view": capture_view,
                        "target_point_count": oblique_target_point_count,
                        "minimum_target_point_count": (
                            config.minimum_target_points
                        ),
                        "fallback_view": "overhead",
                    },
                },
            )
            capture = self._capture_overhead_anygrasp_input(
                object_position_env_m,
                config.capture_distance_m,
            )
            masked_depth, target_points_env_m = self._mask_anygrasp_target(
                object_name,
                object_position_env_m,
                object_orientation_env_xyzw,
                capture,
            )
            capture_view = "overhead_fallback"
        if LOGGER.isEnabledFor(logging.DEBUG):
            valid_depth = capture.depth_m[
                np.isfinite(capture.depth_m) & (capture.depth_m > 0.0)
            ]
            depth_range_m = (
                "empty"
                if not len(valid_depth)
                else f"{float(valid_depth.min()):.4f}..{float(valid_depth.max()):.4f}"
            )
            object_position_env_m_rounded = tuple(
                round(value, 4) for value in object_position_env_m
            )
            camera_position_env_m_rounded = tuple(
                round(value, 4) for value in capture.camera_position_env_m
            )
            camera_orientation_env_xyzw_rounded = tuple(
                round(value, 4) for value in capture.camera_orientation_env_xyzw
            )
            center_depth_m = float(
                capture.depth_m[
                    capture.depth_m.shape[0] // 2,
                    capture.depth_m.shape[1] // 2,
                ]
            )
            LOGGER.debug(
                "view=%s object_position_env_m=%s camera_position_env_m=%s "
                "camera_orientation_env_xyzw=%s center_depth_m=%.4f valid_depth=%d "
                "depth_range_m=%s",
                capture_view,
                object_position_env_m_rounded,
                camera_position_env_m_rounded,
                camera_orientation_env_xyzw_rounded,
                center_depth_m,
                len(valid_depth),
                depth_range_m,
                extra={
                    "event": "CAMERA",
                    "event_fields": {
                        "env_id": self._env_id,
                        "object": object_name,
                        "arm": arm,
                        "view": capture_view,
                        "object_position_env_m": object_position_env_m_rounded,
                        "camera_position_env_m": camera_position_env_m_rounded,
                        "camera_orientation_env_xyzw": (
                            camera_orientation_env_xyzw_rounded
                        ),
                        "center_depth_m": center_depth_m,
                        "valid_depth_count": len(valid_depth),
                        "depth_range_m": depth_range_m,
                    },
                },
            )
        target_point_count = len(target_points_env_m)
        if target_point_count < config.minimum_target_points:
            raise SkillError(
                f"AnyGrasp overhead fallback crop for {object_name!r} contains "
                f"only {target_point_count} valid depth points after the "
                f"arm-side view contained {oblique_target_point_count}; "
                f"expected at least {config.minimum_target_points}"
            )
        try:
            detections = client.detect(
                capture.rgb,
                capture.depth_m,
                capture.intrinsic_matrix_px,
                masked_depth > 0.0,
            )
        except AnyGraspServiceError as error:
            raise SkillError(str(error)) from error
        return _AnyGraspInference(capture, target_points_env_m, detections)

    def _analyze_anygrasp(
        self,
        object_name: str,
        arm: Arm,
        object_position_env_m: tuple[float, float, float],
        object_orientation_env_xyzw: tuple[float, float, float, float],
        inference: _AnyGraspInference,
    ) -> AnyGraspDiagnostics:
        """Transform and classify one shared detection batch for an arm."""

        config = self._anygrasp_config
        capture = inference.capture
        detections = inference.detections
        target_points_env_m = inference.target_points_env_m
        object_pose_env = Pose(
            object_position_env_m,
            object_orientation_env_xyzw,
        )
        camera_pose_env = Pose(
            capture.camera_position_env_m,
            capture.camera_orientation_env_xyzw,
        )
        aperture_m = self._gripper_configs[arm].max_aperture_m
        diagnostics = []
        valid_candidates = []
        for detection_index, detection in enumerate(
            sorted(
                detections,
                key=lambda item: item.score,
                reverse=True,
            )
        ):
            grasp_orientation_camera_xyzw = _quaternion_xyzw_from_matrix(
                detection.rotation_camera
            )
            tcp_pose_camera = Pose(
                tuple(detection.translation_camera_m.tolist()),
                grasp_orientation_camera_xyzw,
            )
            tcp_pose_env = compose_pose(camera_pose_env, tcp_pose_camera)
            anygrasp_tip_pose_camera = Pose(
                tuple(detection.tip_position_camera_m.tolist()),
                grasp_orientation_camera_xyzw,
            )
            anygrasp_tip_pose_env = compose_pose(
                camera_pose_env,
                anygrasp_tip_pose_camera,
            )
            anygrasp_tip_pose_object = relative_pose(
                object_pose_env,
                anygrasp_tip_pose_env,
            )
            tcp_pose_object = relative_pose(object_pose_env, tcp_pose_env)
            approach_axis_env = rotate_vector_xyzw(
                tcp_pose_env.orientation_xyzw,
                (1.0, 0.0, 0.0),
            )
            finger_open_axis_env = rotate_vector_xyzw(
                tcp_pose_env.orientation_xyzw,
                (0.0, 1.0, 0.0),
            )
            candidate = GraspCandidate(
                tcp_pose_object=tcp_pose_object,
                approach_axis_tcp=(1.0, 0.0, 0.0),
                approach_distance_m=config.approach_distance_m,
                score=detection.score,
                candidate_id=detection_index,
                gripper_joint_positions=self._gripper_configs[arm].command_positions_for_width(
                    detection.width_m,
                ),
            )
            status = _anygrasp_candidate_status(
                score=detection.score,
                minimum_score=config.min_score,
                width_m=detection.width_m,
                aperture_m=aperture_m,
                open_axis_vertical_dot=abs(finger_open_axis_env[2]),
                maximum_open_axis_vertical_dot=(config.maximum_open_axis_vertical_dot),
                table_clearance_m=(
                    tcp_pose_env.position_m[2] - self._scene_table_top_z_m
                ),
                minimum_tcp_height_above_table_m=(
                    config.minimum_tcp_height_above_table_m
                ),
                tcp_inside_target_box=_point_inside_box(
                    tcp_pose_object.position_m,
                    self._object_sizes_m[object_name],
                    config.target_margin_m,
                ),
            )
            diagnostics.append(
                AnyGraspPoseDiagnostic(
                    detection_index=detection_index,
                    score=detection.score,
                    width_m=detection.width_m,
                    height_m=detection.height_m,
                    depth_m=detection.depth_m,
                    translation_camera_m=tuple(detection.translation_camera_m.tolist()),
                    rotation_camera=tuple(
                        tuple(float(value) for value in row)
                        for row in detection.rotation_camera
                    ),
                    object_id=detection.object_id,
                    grasp_origin_env_m=tcp_pose_env.position_m,
                    anygrasp_tip_pose_env=anygrasp_tip_pose_env,
                    anygrasp_tip_position_object_m=(
                        anygrasp_tip_pose_object.position_m
                    ),
                    tcp_pose_env=tcp_pose_env,
                    tcp_position_object_m=tcp_pose_object.position_m,
                    tcp_axes_env=tuple(
                        rotate_vector_xyzw(tcp_pose_env.orientation_xyzw, axis)
                        for axis in (
                            (1.0, 0.0, 0.0),
                            (0.0, 1.0, 0.0),
                            (0.0, 0.0, 1.0),
                        )
                    ),
                    approach_axis_env=approach_axis_env,
                    finger_open_axis_env=finger_open_axis_env,
                    open_axis_vertical_dot=abs(finger_open_axis_env[2]),
                    table_clearance_m=(
                        tcp_pose_env.position_m[2] - self._scene_table_top_z_m
                    ),
                    status=status,
                )
            )
            if status.is_valid:
                valid_candidates.append(
                    _ValidAnyGraspCandidate(
                        detection_index=detection_index,
                        score=detection.score,
                        width_m=detection.width_m,
                        tcp_position_object_m=tcp_pose_object.position_m,
                        candidate=candidate,
                    )
                )
        selected_candidates = (
            [max(valid_candidates, key=lambda item: item.score)]
            if valid_candidates
            else []
        )
        selected_detection_indices = {
            item.detection_index for item in selected_candidates
        }
        diagnostics = [
            replace(diagnostic, status=AnyGraspCandidateStatus.SELECTED)
            if diagnostic.detection_index in selected_detection_indices
            else diagnostic
            for diagnostic in diagnostics
        ]
        candidates = tuple(item.candidate for item in valid_candidates)
        if LOGGER.isEnabledFor(logging.DEBUG):
            accepted_diagnostics = [
                {
                    "candidate_id": item.candidate.candidate_id,
                    "detection_index": item.detection_index,
                    "score": round(item.score, 4),
                    "width_m": round(item.width_m, 4),
                    "tcp_position_object_m": tuple(
                        round(value, 4) for value in item.tcp_position_object_m
                    ),
                }
                for item in valid_candidates
            ]
            LOGGER.debug(
                "geometry-valid candidates=%s",
                accepted_diagnostics,
                extra={
                    "event": "CANDIDATE",
                    "event_fields": {
                        "env_id": self._env_id,
                        "object": object_name,
                        "arm": arm,
                        "candidates": accepted_diagnostics,
                    },
                },
            )
        status_counts = Counter(diagnostic.status.value for diagnostic in diagnostics)
        ordered_status_counts = dict(sorted(status_counts.items()))
        rejected_statuses = {
            status.removeprefix("rejected_"): count
            for status, count in ordered_status_counts.items()
            if status.startswith("rejected_")
        }
        filtered_summary = (
            ",".join(
                f"{status}:{count}"
                for status, count in rejected_statuses.items()
            )
            or "none"
        )
        LOGGER.info(
            "points=%d returned=%d valid=%d filtered=%s",
            len(target_points_env_m),
            len(detections),
            len(candidates),
            filtered_summary,
            extra={
                "event": "DETECT",
                "event_fields": {
                    "env_id": self._env_id,
                    "object": object_name,
                    "arm": arm,
                    "target_point_count": len(target_points_env_m),
                    "detection_count": len(detections),
                    "valid_candidate_count": len(candidates),
                    "status_counts": ordered_status_counts,
                },
            },
        )
        return AnyGraspDiagnostics(
            object_name=object_name,
            arm=arm,
            env_id=self._env_id,
            object_pose_env=Pose(
                object_position_env_m,
                object_orientation_env_xyzw,
            ),
            object_size_m=self._object_sizes_m[object_name],
            camera_pose_env=Pose(
                capture.camera_position_env_m,
                capture.camera_orientation_env_xyzw,
            ),
            input_rgb=capture.rgb,
            input_depth_m=capture.depth_m,
            intrinsic_matrix_px=capture.intrinsic_matrix_px,
            depth_trunc_m=config.depth_trunc_m,
            target_points_env_m=target_points_env_m,
            table_top_z_m=self._scene_table_top_z_m,
            gripper_aperture_m=aperture_m,
            minimum_score=config.min_score,
            maximum_open_axis_vertical_dot=(config.maximum_open_axis_vertical_dot),
            minimum_tcp_height_above_table_m=(config.minimum_tcp_height_above_table_m),
            detections=tuple(diagnostics),
            candidates=candidates,
        )

    def _capture_anygrasp_input(
        self,
        object_position_env_m: tuple[float, float, float],
        arm: Arm,
        capture_distance_m: float,
        capture_elevation_deg: float,
        capture_azimuth_offset_deg: float,
    ) -> _AnyGraspCapture:
        """Capture from the selected arm's side at the configured elevation."""

        arm_base_position_env_m = self._arm_base_positions_env_m[arm]
        horizontal_x = arm_base_position_env_m[0] - object_position_env_m[0]
        horizontal_y = arm_base_position_env_m[1] - object_position_env_m[1]
        horizontal_norm = math.hypot(horizontal_x, horizontal_y)

        if horizontal_norm <= 1.0e-9:
            raise SkillError(
                f"cannot build an arm-side AnyGrasp view for {arm}: "
                "object and robot base have the same XY position"
            )

        direction_x = horizontal_x / horizontal_norm
        direction_y = horizontal_y / horizontal_norm

        azimuth_rad = math.radians(capture_azimuth_offset_deg)
        cos_azimuth = math.cos(azimuth_rad)
        sin_azimuth = math.sin(azimuth_rad)

        rotated_direction_x = (
            cos_azimuth * direction_x
            - sin_azimuth * direction_y
        )
        rotated_direction_y = (
            sin_azimuth * direction_x
            + cos_azimuth * direction_y
        )

        elevation_rad = math.radians(capture_elevation_deg)

        horizontal_offset_m = capture_distance_m * math.cos(elevation_rad)
        vertical_offset_m = capture_distance_m * math.sin(elevation_rad)

        eye_position_env_m = (
            object_position_env_m[0]
            + horizontal_offset_m * rotated_direction_x,
            object_position_env_m[1]
            + horizontal_offset_m * rotated_direction_y,
            object_position_env_m[2] + vertical_offset_m,
        )
        return self._capture_anygrasp_view(
            object_position_env_m,
            eye_position_env_m,
        )

    def _capture_overhead_anygrasp_input(
        self,
        object_position_env_m: tuple[float, float, float],
        capture_distance_m: float,
    ) -> _AnyGraspCapture:
        """Capture the single fallback view directly above the target."""

        eye_position_env_m = (
            object_position_env_m[0],
            object_position_env_m[1],
            object_position_env_m[2] + capture_distance_m,
        )
        return self._capture_anygrasp_view(
            object_position_env_m,
            eye_position_env_m,
        )

    def _capture_anygrasp_view(
        self,
        object_position_env_m: tuple[float, float, float],
        eye_position_env_m: tuple[float, float, float],
    ) -> _AnyGraspCapture:
        """Render one target-centered view without stepping or recording."""

        camera = self._env.scene.sensors["overhead_camera"]
        if not isinstance(camera, Camera):
            raise SkillError("AnyGrasp requires an Isaac Lab Camera sensor")
        original_position_world = (
            camera.data.pos_w.torch[self._env_id].detach().cpu().numpy().copy()
        )
        original_orientation_ros = (
            camera.data.quat_w_ros.torch[self._env_id].detach().cpu().numpy().copy()
        )
        env_origin = self._env.scene.env_origins[self._env_id].detach().cpu().numpy()
        target_world = env_origin + np.asarray(object_position_env_m, dtype=np.float64)
        eye_world = env_origin + np.asarray(eye_position_env_m, dtype=np.float64)
        camera.set_world_poses_from_view(
            eyes=eye_world.reshape(1, 3),
            targets=target_world.reshape(1, 3),
            env_ids=[self._env_id],
        )
        try:
            self._refresh_camera_without_recording(camera)
            output = camera.data.output
            if output is None or not {
                "rgb",
                "distance_to_image_plane",
            }.issubset(output):
                raise SkillError(
                    "AnyGrasp requires overhead_camera aligned RGB-D output"
                )
            return _AnyGraspCapture(
                rgb=(output["rgb"].torch[self._env_id].detach().cpu().numpy().copy()),
                depth_m=(
                    output["distance_to_image_plane"]
                    .torch[self._env_id]
                    .detach()
                    .cpu()
                    .numpy()
                    .copy()
                ),
                intrinsic_matrix_px=(
                    camera.data.intrinsic_matrices.torch[self._env_id]
                    .detach()
                    .cpu()
                    .numpy()
                    .copy()
                ),
                camera_position_env_m=tuple(
                    float(value)
                    for value in (
                        camera.data.pos_w.torch[self._env_id].detach().cpu().numpy()
                        - env_origin
                    )
                ),
                camera_orientation_env_xyzw=tuple(
                    float(value)
                    for value in camera.data.quat_w_ros.torch[self._env_id]
                    .detach()
                    .cpu()
                    .tolist()
                ),
            )
        finally:
            camera.set_world_poses(
                positions=original_position_world.reshape(1, 3),
                orientations=original_orientation_ros.reshape(1, 4),
                env_ids=[self._env_id],
                convention="ros",
            )
            self._refresh_camera_without_recording(camera)

    def _mask_anygrasp_target(
        self,
        object_name: str,
        object_position_env_m: tuple[float, float, float],
        object_orientation_env_xyzw: tuple[float, float, float, float],
        capture: _AnyGraspCapture,
    ) -> tuple[np.ndarray, tuple[tuple[float, float, float], ...]]:
        """Extract visible target points from one captured scene frame."""

        config = self._anygrasp_config
        return _mask_depth_to_target_box(
            capture.depth_m,
            capture.intrinsic_matrix_px,
            capture.camera_position_env_m,
            capture.camera_orientation_env_xyzw,
            object_position_env_m,
            object_orientation_env_xyzw,
            self._object_sizes_m[object_name],
            config.target_margin_m,
            config.depth_trunc_m,
            minimum_env_z_m=(
                self._scene_table_top_z_m + config.minimum_point_height_above_table_m
            ),
        )

    def _refresh_camera_without_recording(self, camera: Camera) -> None:
        """Refresh one camera without environment or video recorder hooks."""

        import omni.kit.app

        self._env.sim.forward()
        # Pump Kit once so RTX observes the changed USD camera transform. This
        # bypasses SimulationContext.render(), whose final stage runs the
        # video-recording hooks.
        omni.kit.app.get_app().update()
        self._env.sim.render_context.reset_transform_cadence()
        camera.reset(env_ids=[self._env_id])
        camera.update(0.0, force_recompute=True)


def _matrix_from_quaternion_xyzw(
    value: tuple[float, float, float, float],
) -> np.ndarray:
    x, y, z, w = normalize_quaternion_xyzw(value)
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _quaternion_xyzw_from_matrix(
    matrix: np.ndarray,
) -> tuple[float, float, float, float]:
    rotation = np.asarray(matrix, dtype=np.float64)
    if rotation.shape != (3, 3):
        raise ValueError("rotation matrix must have shape (3, 3)")
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quaternion = (
            (rotation[2, 1] - rotation[1, 2]) / scale,
            (rotation[0, 2] - rotation[2, 0]) / scale,
            (rotation[1, 0] - rotation[0, 1]) / scale,
            0.25 * scale,
        )
    else:
        diagonal = np.diag(rotation)
        index = int(np.argmax(diagonal))
        if index == 0:
            scale = (
                math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
            )
            quaternion = (
                0.25 * scale,
                (rotation[0, 1] + rotation[1, 0]) / scale,
                (rotation[0, 2] + rotation[2, 0]) / scale,
                (rotation[2, 1] - rotation[1, 2]) / scale,
            )
        elif index == 1:
            scale = (
                math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
            )
            quaternion = (
                (rotation[0, 1] + rotation[1, 0]) / scale,
                0.25 * scale,
                (rotation[1, 2] + rotation[2, 1]) / scale,
                (rotation[0, 2] - rotation[2, 0]) / scale,
            )
        else:
            scale = (
                math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
            )
            quaternion = (
                (rotation[0, 2] + rotation[2, 0]) / scale,
                (rotation[1, 2] + rotation[2, 1]) / scale,
                0.25 * scale,
                (rotation[1, 0] - rotation[0, 1]) / scale,
            )
    return normalize_quaternion_xyzw(tuple(float(value) for value in quaternion))


def _point_inside_box(
    point_object_m: tuple[float, float, float],
    size_m: tuple[float, float, float],
    margin_m: float,
) -> bool:
    return all(
        abs(coordinate) <= dimension / 2.0 + margin_m
        for coordinate, dimension in zip(point_object_m, size_m, strict=True)
    )


def _anygrasp_candidate_status(
    *,
    score: float,
    minimum_score: float,
    width_m: float,
    aperture_m: float,
    open_axis_vertical_dot: float,
    maximum_open_axis_vertical_dot: float,
    table_clearance_m: float,
    minimum_tcp_height_above_table_m: float,
    tcp_inside_target_box: bool,
) -> AnyGraspCandidateStatus:
    """Return the first failed filter in the runtime's fixed filter order."""

    if score < minimum_score:
        return AnyGraspCandidateStatus.REJECTED_SCORE
    if width_m > aperture_m + 1.0e-6:
        return AnyGraspCandidateStatus.REJECTED_WIDTH
    if not tcp_inside_target_box:
        return AnyGraspCandidateStatus.REJECTED_TARGET_BOX
    if open_axis_vertical_dot > maximum_open_axis_vertical_dot:
        return AnyGraspCandidateStatus.REJECTED_OPEN_AXIS
    if table_clearance_m < minimum_tcp_height_above_table_m:
        return AnyGraspCandidateStatus.REJECTED_TABLE_CLEARANCE
    return AnyGraspCandidateStatus.VALID_NOT_SELECTED


def _mask_depth_to_target_box(
    depth_m: np.ndarray,
    intrinsic_matrix_px: np.ndarray,
    camera_position_env_m: tuple[float, float, float],
    camera_orientation_env_xyzw: tuple[float, float, float, float],
    object_position_env_m: tuple[float, float, float],
    object_orientation_env_xyzw: tuple[float, float, float, float],
    object_size_m: tuple[float, float, float],
    margin_m: float,
    depth_trunc_m: float,
    *,
    minimum_env_z_m: float,
) -> tuple[
    np.ndarray,
    tuple[tuple[float, float, float], ...],
]:
    """Keep depth points inside the target's expanded oriented bounding box."""

    depth = np.asarray(depth_m, dtype=np.float32)
    if depth.ndim == 3 and depth.shape[-1] == 1:
        depth = depth[..., 0]
    if depth.ndim != 2:
        raise SkillError(f"overhead depth has unexpected shape {depth.shape}")
    intrinsics = np.asarray(intrinsic_matrix_px, dtype=np.float64)
    if intrinsics.shape != (3, 3):
        raise SkillError(
            f"overhead camera intrinsics have unexpected shape {intrinsics.shape}"
        )
    fx, fy = float(intrinsics[0, 0]), float(intrinsics[1, 1])
    cx, cy = float(intrinsics[0, 2]), float(intrinsics[1, 2])
    if fx <= 0.0 or fy <= 0.0:
        raise SkillError("overhead camera focal lengths must be positive")

    valid = np.isfinite(depth) & (depth > 0.0) & (depth < depth_trunc_m)
    rows, columns = np.nonzero(valid)
    masked = np.zeros_like(depth, dtype=np.float32)
    if not len(rows):
        return masked, ()
    z = depth[rows, columns].astype(np.float64, copy=False)
    points_camera = np.column_stack(
        (
            (columns.astype(np.float64) - cx) / fx * z,
            (rows.astype(np.float64) - cy) / fy * z,
            z,
        )
    )
    camera_to_env = _matrix_from_quaternion_xyzw(camera_orientation_env_xyzw)
    object_to_env = _matrix_from_quaternion_xyzw(object_orientation_env_xyzw)
    points_env = points_camera @ camera_to_env.T + np.asarray(
        camera_position_env_m,
        dtype=np.float64,
    )
    # Row-vector form of R_object_env.T @ (point_env - object_position_env).
    points_object = (
        points_env - np.asarray(object_position_env_m, dtype=np.float64)
    ) @ object_to_env
    half_extents = np.asarray(object_size_m, dtype=np.float64) / 2.0 + margin_m
    inside = np.all(np.abs(points_object) <= half_extents, axis=1) & (
        points_env[:, 2] >= minimum_env_z_m
    )
    masked[rows[inside], columns[inside]] = z[inside]
    target_points_env_m = tuple(
        tuple(float(value) for value in point) for point in points_env[inside]
    )
    return masked, target_points_env_m


__all__ = ["AnyGraspSource"]
