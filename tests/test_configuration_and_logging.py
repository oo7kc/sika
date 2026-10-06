from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from sika.configuration import ConfigurationError, LoggingConfig, load_logging_config
from sika.logging_config import JsonLineFormatter, configure_logging
from sika.market_data.mt5_export import main as export_main


class ConfigurationAndLoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_logging(LoggingConfig(level="CRITICAL"))

    def test_logging_configuration_is_validated(self) -> None:
        config = load_logging_config(
            {
                "SIKA_LOG_LEVEL": "warning",
                "SIKA_LOG_FORMAT": "json",
                "SIKA_LOG_FILE": "logs/review.jsonl",
            }
        )

        self.assertEqual(config.level, "WARNING")
        self.assertEqual(config.output_format, "json")
        self.assertEqual(config.file_path, Path("logs/review.jsonl"))

        with self.assertRaisesRegex(ConfigurationError, "SIKA_LOG_LEVEL"):
            load_logging_config({"SIKA_LOG_LEVEL": "VERBOSE"})
        with self.assertRaisesRegex(ConfigurationError, "SIKA_LOG_FORMAT"):
            load_logging_config({"SIKA_LOG_FORMAT": "xml"})

    def test_json_logs_have_stable_fields_and_do_not_copy_secrets(self) -> None:
        record = logging.LogRecord(
            "sika.test",
            logging.INFO,
            __file__,
            1,
            "validation complete",
            (),
            None,
        )
        record.event = "validation_completed"
        record.password = "must-not-be-logged"

        payload = json.loads(JsonLineFormatter().format(record))

        self.assertEqual(payload["event"], "validation_completed")
        self.assertEqual(payload["message"], "validation complete")
        self.assertNotIn("password", payload)
        self.assertNotIn("must-not-be-logged", json.dumps(payload))

    def test_reconfiguration_does_not_duplicate_file_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sika.jsonl"
            config = LoggingConfig(
                level="INFO",
                output_format="json",
                file_path=output,
            )
            with redirect_stderr(io.StringIO()):
                logger = configure_logging(config)
                logger = configure_logging(config)
                logger.info("one event", extra={"event": "test_event"})
            for handler in logger.handlers:
                handler.flush()

            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["event"], "test_event")

    def test_command_fails_closed_on_invalid_logging_configuration(self) -> None:
        with (
            patch.dict(os.environ, {"SIKA_LOG_FORMAT": "xml"}, clear=True),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            exit_code = export_main(["missing-manifest.json"])

        self.assertEqual(exit_code, 2)
        self.assertIn("CONFIGURATION ERROR", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
