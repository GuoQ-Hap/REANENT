import os
import tempfile
import unittest
from pathlib import Path

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.env import load_env_file


class EnvAndLoggingTests(unittest.TestCase):
    def test_load_env_file_sets_missing_values_and_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("PMC_TEST_ENV_VALUE=ok\n", encoding="utf-8")

            os.environ.pop("PMC_TEST_ENV_VALUE", None)
            with self.assertLogs("pmc_agent.env", level="INFO") as logs:
                load_env_file(env_path)

        self.assertEqual(os.environ["PMC_TEST_ENV_VALUE"], "ok")
        self.assertEqual(logs.records[0].event, "env_file_loaded")
        os.environ.pop("PMC_TEST_ENV_VALUE", None)

    def test_load_env_file_overrides_existing_values_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("PMC_TEST_ENV_VALUE=from_file\n", encoding="utf-8")

            os.environ["PMC_TEST_ENV_VALUE"] = "from_process"
            load_env_file(env_path)

        self.assertEqual(os.environ["PMC_TEST_ENV_VALUE"], "from_file")
        os.environ.pop("PMC_TEST_ENV_VALUE", None)

    def test_load_env_file_can_preserve_existing_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("PMC_TEST_ENV_VALUE=from_file\n", encoding="utf-8")

            os.environ["PMC_TEST_ENV_VALUE"] = "from_process"
            load_env_file(env_path, override=False)

        self.assertEqual(os.environ["PMC_TEST_ENV_VALUE"], "from_process")
        os.environ.pop("PMC_TEST_ENV_VALUE", None)

    def test_logger_supports_standard_context_fields(self):
        logger = get_logger("pmc_agent.tests.logging")

        with self.assertLogs("pmc_agent.tests.logging", level="INFO") as logs:
            logger.info("hello", extra=log_extra("test_event", request_id="req-test", task_type="inventory_risk"))

        self.assertEqual(logs.records[0].event, "test_event")


if __name__ == "__main__":
    unittest.main()
