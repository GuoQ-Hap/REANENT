import unittest

from pmc_agent.state import RunStateMachine, RunStatus


class StateMachineTests(unittest.TestCase):
    def test_state_transition_records_history_and_logs(self):
        state = RunStateMachine(request_id="20260520_180000_000001")

        with self.assertLogs("pmc_agent.state", level="INFO") as logs:
            state.transition(RunStatus.INTENT_RECOGNIZING, "intent_recognition_started")

        self.assertEqual(state.status, RunStatus.INTENT_RECOGNIZING)
        self.assertEqual(state.history[0].from_status, RunStatus.CREATED)
        self.assertEqual(state.history[0].to_status, RunStatus.INTENT_RECOGNIZING)
        self.assertEqual(logs.records[0].event, "state_transition")


if __name__ == "__main__":
    unittest.main()
