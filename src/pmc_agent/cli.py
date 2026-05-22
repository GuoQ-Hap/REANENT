from __future__ import annotations

import argparse

from pmc_agent.env import load_env_file
from pmc_agent.orchestrator import PmcAgent


def main() -> None:
    load_env_file(override=False)

    parser = argparse.ArgumentParser(description="Run the PMC supply chain control agent.")
    parser.add_argument("request", help="PMC control request, for example: 检查 A100 是否有缺料风险")
    parser.add_argument("--feedback", action="append", default=[], help="Feedback to apply in the next goal-loop iteration. Can be passed multiple times.")
    parser.add_argument("--max-iterations", type=int, default=3, help="Maximum iterations when feedback is provided.")
    args = parser.parse_args()

    agent = PmcAgent.create_default()
    if args.feedback:
        goal_result = agent.run_goal(args.request, feedback=args.feedback, max_iterations=args.max_iterations)
        print(f"Goal status: {goal_result.status.value}")
        print(f"Final answer: {goal_result.final_answer}")
        if goal_result.pending_questions:
            print("Pending questions:")
            for question in goal_result.pending_questions:
                print(f"- {question}")
        print("Iterations:")
        for iteration in goal_result.iterations:
            print(f"- Iteration {iteration.iteration}")
            if iteration.applied_feedback:
                print(f"  Feedback: {iteration.applied_feedback}")
            print(f"  Request: {iteration.request_text}")
            print(f"  Observation: {iteration.observation}")
        return

    result = agent.run(args.request)

    print(f"Task type: {result.plan.task_type.value}")
    print(f"Confidence: {result.plan.confidence:.2f}")
    if result.plan.assumptions:
        print("Assumptions:")
        for assumption in result.plan.assumptions:
            print(f"- {assumption}")

    print("Plan:")
    for step in result.plan.steps:
        print(f"- {step.name}: {step.purpose}")

    print("Decisions:")
    for decision in result.decisions:
        print(f"- {decision.material_code} [{decision.risk_level.value}] {decision.summary}")
        for action in decision.recommended_actions:
            print(f"  * {action}")

    if result.artifacts:
        print("Artifacts:")
        for name, artifact in result.artifacts.items():
            print(f"- {name}: {artifact}")

    print("Verification:")
    for item in result.verification:
        print(f"- {item}")


if __name__ == "__main__":
    main()
