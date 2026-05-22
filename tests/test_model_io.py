import json
import tempfile
import unittest
from pathlib import Path

from pmc_agent.domain import TaskType
from pmc_agent.model import IntentAssessment
from pmc_agent.model_io import generate_time_id, record_model_interaction


class ModelIoTests(unittest.TestCase):
    def test_generate_time_id_is_path_friendly(self):
        value = generate_time_id()

        self.assertRegex(value, r"^\d{8}_\d{6}_\d{6}$")

    def test_record_model_interaction_appends_to_conversation_file(self):
        output = IntentAssessment(
            task_type=TaskType.SHORTAGE_TRACE,
            confidence=0.9,
            user_expectation="追因",
            needs_data_context=True,
            needs_calculation=True,
            needs_write_or_approval=False,
            risk_level="medium",
            reasoning_summary="测试",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = record_model_interaction(
                "intent_recognition",
                "20260520_180000_000001",
                {"input": "测试"},
                output=output,
                base_dir=tmpdir,
            )
            second_path = record_model_interaction(
                "agentic_orchestration",
                "20260520_180000_000001",
                {"input": "继续"},
                output={"action": "final_answer"},
                base_dir=tmpdir,
            )

            self.assertEqual(path, Path(tmpdir) / "conversations" / "20260520_180000_000001.txt")
            self.assertEqual(second_path, path)
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data["id"], "20260520_180000_000001")
        self.assertEqual(data["interaction_count"], 2)
        self.assertEqual(data["interactions"][0]["interaction_type"], "intent_recognition")
        self.assertEqual(data["interactions"][0]["output"]["task_type"], "shortage_trace")
        self.assertEqual(data["interactions"][1]["interaction_type"], "agentic_orchestration")


if __name__ == "__main__":
    unittest.main()
