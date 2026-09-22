"""Solve each environment's planning requests on its own CuRobo backend."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import ExitStack
from contextvars import Context, copy_context
from dataclasses import dataclass
from functools import partial
from time import perf_counter
from typing import Literal, cast

import torch

from scale_bench.skills.context import (
    GraspCandidate,
    GraspState,
    JointState,
    JointTrajectory,
    PlanningScene,
    SceneSnapshot,
)
from scale_bench.skills.errors import PlanningError, SkillError
from scale_bench.skills.models import Arm, Pose
from scale_bench.skills.planner import PlanningStage

from .curobo_planner import CuroboMotionPlanner
from .skill_context import IsaacLabSkillContext

LOGGER = logging.getLogger(__name__)
PlanKind = Literal["ik", "pose", "joints"]
# IK only checks reachability and returns None; motion planning returns a path.
PlanResult = JointTrajectory | None


@dataclass(slots=True)
class _Request:
    env_id: int
    kind: PlanKind
    stage: PlanningStage
    solve: Callable[[], PlanResult]
    future: asyncio.Future[PlanResult]
    log_context: Context


class CuroboPlanningPool:
    """Own independent backends and streams; keep physics paused during solves."""

    def __init__(
        self,
        num_envs: int,
        device: str,
        planner_factory: Callable[[int], Mapping[Arm, CuroboMotionPlanner]],
    ) -> None:
        self.planners: list[Mapping[Arm, CuroboMotionPlanner]] = []
        self._resources = ExitStack()
        self._pending: list[_Request] = []
        self._observations: list[Callable[[], None]] = []
        self._counts: Counter[str] = Counter()
        self._planning_seconds = 0.0
        started = perf_counter()
        for env_id in range(num_envs):
            planners = planner_factory(env_id)
            self.planners.append(planners)
            # Matching arms share only within this environment.
            backends = {planner._planner for planner in planners.values()}
            for backend in backends:
                self._resources.callback(backend.destroy)
            for backend in backends:
                # Capture standard solver paths before any workers run.
                backend.warmup()
                current_joint_state = backend.default_joint_state.clone().unsqueeze(0)
                backend.plan_cspace(current_joint_state, current_joint_state)
                backend.ik_solver.solve_pose(
                    backend.compute_kinematics(current_joint_state).tool_poses.as_goal(),
                    current_state=current_joint_state,
                    return_seeds=backend.ik_solver.config.num_seeds,
                )
                backend.reset_seed()
        torch.cuda.synchronize(device)
        self._streams = [torch.cuda.Stream(device=device) for _ in range(num_envs)]
        # Registered last so shutdown joins workers before destroying backends.
        self._executor = self._resources.enter_context(
            ThreadPoolExecutor(max_workers=num_envs, thread_name_prefix="curobo-env")
        )
        self._warmup_seconds = perf_counter() - started
        LOGGER.info(
            "environments=%d warmup_seconds=%.2f", num_envs, self._warmup_seconds,
            extra={"event": "PLAN-INIT", "event_fields": {
                "num_envs": num_envs, "warmup_seconds": self._warmup_seconds,
            }},
        )

    async def submit(
        self,
        env_id: int,
        kind: PlanKind,
        stage: PlanningStage,
        solve: Callable[[], PlanResult],
    ) -> PlanResult:
        future: asyncio.Future[PlanResult] = asyncio.get_running_loop().create_future()
        self._counts["requests"] += 1
        self._pending.append(_Request(env_id, kind, stage, solve, future, copy_context()))
        return await future

    async def grasp_candidates(
        self,
        context: IsaacLabSkillContext,
        object_name: str,
        arm: Arm,
    ) -> tuple[GraspCandidate, ...]:
        """Read live Isaac state on the main thread outside the planning loop."""
        future: asyncio.Future[tuple[GraspCandidate, ...]] = (
            asyncio.get_running_loop().create_future()
        )
        log_context = copy_context()

        def observe() -> None:
            try:
                candidates = log_context.run(context.grasp_candidates, object_name, arm)
                future.set_result(candidates)
            except SkillError as error:
                future.set_exception(error)

        self._observations.append(observe)
        return await future

    def flush(self) -> None:
        observations, self._observations = self._observations, []
        for observe in observations:
            observe()
        requests, self._pending = self._pending, []
        requests = [request for request in requests if not request.future.cancelled()]
        if not requests:
            return
        started = perf_counter()
        self._counts["rounds"] += 1
        if len(requests) > 1:
            self._counts["concurrent_requests"] += len(requests)
        for request in requests:
            stream = self._streams[request.env_id]
            stream.wait_stream(torch.cuda.current_stream(stream.device))
        futures = [
            self._executor.submit(request.log_context.run, self._solve, request)
            for request in requests
        ]
        try:
            for request, future in zip(requests, futures, strict=True):
                try:
                    request.future.set_result(future.result())
                    self._counts["success"] += 1
                except PlanningError as error:
                    self._counts["failed"] += 1
                    request.future.set_exception(error)
        finally:
            # Drain other workers before an error can resume Isaac or teardown.
            wait(futures)
            elapsed = perf_counter() - started
            self._planning_seconds += elapsed
        if len(requests) > 1:
            LOGGER.info(
                "env_ids=%s requests=%d seconds=%.2f",
                [request.env_id for request in requests], len(requests), elapsed,
                extra={"event": "PLAN-PARALLEL", "event_fields": {
                    "env_ids": [request.env_id for request in requests],
                    "request_count": len(requests), "seconds": elapsed,
                }},
            )

    def _solve(self, request: _Request) -> PlanResult:
        stream = self._streams[request.env_id]
        started = perf_counter()
        with torch.cuda.device(stream.device), torch.cuda.stream(stream):
            try:
                return request.solve()
            finally:
                # Results and temporary buffers must finish before the next round.
                stream.synchronize()
                LOGGER.debug(
                    "kind=%s stage=%s seconds=%.3f",
                    request.kind, request.stage, perf_counter() - started,
                    extra={"event": "PLAN-SOLVE", "event_fields": {
                        "kind": request.kind, "stage": request.stage,
                        "seconds": perf_counter() - started,
                    }},
                )

    def close(self) -> None:
        self._resources.close()
        LOGGER.info(
            "requests=%d success=%d failed=%d concurrent_requests=%d "
            "planning_seconds=%.2f warmup_seconds=%.2f",
            self._counts["requests"], self._counts["success"], self._counts["failed"],
            self._counts["concurrent_requests"], self._planning_seconds,
            self._warmup_seconds,
            extra={"event": "PLAN-STATS", "event_fields": {
                **self._counts, "planning_seconds": self._planning_seconds,
                "warmup_seconds": self._warmup_seconds,
            }},
        )


class QueuedCuroboMotionPlanner:
    """Submit one dependent stage at a time to this environment's backend."""

    def __init__(
        self, planner: CuroboMotionPlanner, pool: CuroboPlanningPool, env_id: int,
    ) -> None:
        self._planner = planner
        self._pool = pool
        self._env_id = env_id

    async def solve_ik(
        self, start: JointState, target_tcp_pose_env: Pose,
        scene: PlanningScene, stage: PlanningStage,
    ) -> None:
        await self._pool.submit(
            self._env_id, "ik", stage,
            partial(self._planner.solve_ik, start, target_tcp_pose_env, scene, stage),
        )

    async def plan_pose(
        self, start: JointState, target_tcp_pose_env: Pose,
        scene: PlanningScene, stage: PlanningStage,
        linear_axis_env: tuple[float, float, float] | None,
    ) -> JointTrajectory:
        """None permits transit; contact stages provide their Cartesian axis."""
        return cast(JointTrajectory, await self._pool.submit(
            self._env_id, "pose", stage,
            partial(
                self._planner.plan_pose, start, target_tcp_pose_env, scene, stage,
                linear_axis_env,
            ),
        ))

    async def plan_joints(
        self, start: JointState, target_joint_state: JointState,
        scene: PlanningScene, stage: PlanningStage,
    ) -> JointTrajectory:
        return cast(JointTrajectory, await self._pool.submit(
            self._env_id, "joints", stage,
            partial(self._planner.plan_joints, start, target_joint_state, scene, stage),
        ))

    def commit_inspection_stages(self, stages: tuple[PlanningStage, ...]) -> None:
        self._planner.commit_inspection_stages(stages)

    def gripper_clearance_m(self, approach_axis_tcp: tuple[float, float, float]) -> float:
        return self._planner.gripper_clearance_m(approach_axis_tcp)


class QueuedSkillContext:
    """Keep live state reads local and schedule captures outside the event loop."""

    def __init__(self, context: IsaacLabSkillContext, pool: CuroboPlanningPool) -> None:
        self._context = context
        self._pool = pool

    def snapshot(self) -> SceneSnapshot:
        return self._context.snapshot()

    def measure_grasp(self, object_name: str, arm: Arm) -> GraspState:
        return self._context.measure_grasp(object_name, arm)

    async def grasp_candidates(
        self, object_name: str, arm: Arm,
    ) -> tuple[GraspCandidate, ...]:
        return await self._pool.grasp_candidates(self._context, object_name, arm)
