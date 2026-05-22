import unittest

from pmc_agent.model import _extract_response_text


class ModelTests(unittest.TestCase):
    def test_extract_response_text_from_output_text(self):
        self.assertEqual(_extract_response_text({"output_text": '{"ok": true}'}), '{"ok": true}')

    def test_extract_response_text_from_output_content(self):
        response = {"output": [{"content": [{"type": "output_text", "text": '{"ok": true}'}]}]}

        self.assertEqual(_extract_response_text(response), '{"ok": true}')

    def test_extract_response_text_raises_for_missing_text(self):
        with self.assertRaises(ValueError):
            _extract_response_text({"output": []})


if __name__ == "__main__":
    unittest.main()
