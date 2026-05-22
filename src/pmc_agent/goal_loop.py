from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.domain import AgentRunResult, GoalIteration, GoalLoopStatus, GoalRunResult


logger = get_logger(__name__)


class AgentRunner(Protocol):
    def run(self, text: str) -> AgentRunResult:
        ...


@dataclass
class GoalLoop:
    """围绕同一业务目标进行执行、观察、反馈修正和再执行。

    这个循环刻意复用现有 PmcAgent.run 的稳定单轮能力。它不让模型直接越过规则工具，
    而是在每轮执行后基于反馈和验证结果决定是否继续。
    """

    runner: AgentRunner
    max_iterations: int = 3
    feedback: list[str] = field(default_factory=list)

    def run(self, goal: str) -> GoalRunResult:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1.")

        iterations: list[GoalIteration] = []
        current_text = goal
        status = GoalLoopStatus.COMPLETED
        pending_questions: list[str] = []

        for index in range(1, self.max_iterations + 1):
            applied_feedback = self.feedback[index - 2] if index > 1 and index - 2 < len(self.feedback) else None
            if applied_feedback:
                current_text = _merge_goal_and_feedback(goal, applied_feedback, iterations[-1].observation if iterations else "")

            logger.info(
                "goal loop iteration started",
                extra=log_extra("goal_loop_iteration_started", iteration=index, feedback_applied=bool(applied_feedback)),
            )
            result = self.runner.run(current_text)
            observation = summarize_result(result)
            iterations.append(
                GoalIteration(
                    iteration=index,
                    request_text=current_text,
                    applied_feedback=applied_feedback,
                    result=result,
                    observation=observation,
                )
            )
            logger.info(
                "goal loop iteration completed",
                extra=log_extra(
                    "goal_loop_iteration_completed",
                    iteration=index,
                    task_type=result.plan.task_type.value,
                    decision_count=len(result.decisions),
                    artifact_count=len(result.artifacts),
                ),
            )

            if _needs_user_feedback(result):
                status = GoalLoopStatus.NEEDS_USER_FEEDBACK
                pending_questions = ["请补充物料编码、范围、时间窗口或需要复核的业务数据来源。"]
                break

            if index <= len(self.feedback):
                continue

            status = GoalLoopStatus.COMPLETED
            break
        else:
            status = GoalLoopStatus.MAX_ITERATIONS_REACHED

        return GoalRunResult(
            goal=goal,
            status=status,
            iterations=iterations,
            final_answer=_final_answer(status, iterations),
            pending_questions=pending_questions,
        )


def summarize_result(result: AgentRunResult) -> str:
    """把一轮 Agent 输出压缩成下一轮可消费的观察结果。"""

    parts = [f"task_type={result.plan.task_type.value}", f"verification={'; '.join(result.verification) or '-'}"]
    if result.plan.assumptions:
        parts.append(f"assumptions={'; '.join(result.plan.assumptions)}")
    if result.decisions:
        decision_parts = [
            f"{item.material_code}:{item.risk_level.value}:{item.summary}"
            for item in result.decisions
        ]
        parts.append(f"decisions={' | '.join(decision_parts)}")
    if result.artifacts:
        parts.append(f"artifacts={', '.join(result.artifacts.keys())}")
    return "\n".join(parts)


def _merge_goal_and_feedback(goal: str, feedback: str, previous_observation: str) -> str:
    return (
        f"{goal}\n\n"
        f"用户反馈：{feedback}\n\n"
        f"上一轮观察：{previous_observation}\n\n"
        "请根据用户反馈修正目标、重新判断意图，并只输出需要业务复核的建议或草稿。"
    )


def _needs_user_feedback(result: AgentRunResult) -> bool:
    if result.decisions or result.artifacts:
        return False
    return any("No decision was produced" in item for item in result.verification)


def _final_answer(status: GoalLoopStatus, iterations: list[GoalIteration]) -> str:
    if not iterations:
        return "目标尚未执行。"
    latest = iterations[-1]
    if status == GoalLoopStatus.NEEDS_USER_FEEDBACK:
        return f"已执行 {len(iterations)} 轮，但缺少继续判断所需的业务信息。\n{latest.observation}"
    if status == GoalLoopStatus.MAX_ITERATIONS_REACHED:
        return f"已达到最大迭代轮次 {len(iterations)}，请人工复核最新结果。\n{latest.observation}"
    return f"目标已完成，共执行 {len(iterations)} 轮。\n{latest.observation}"
