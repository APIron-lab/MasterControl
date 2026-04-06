from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mastercontrol.ai import ProviderStatus, provider_statuses, resolve_provider_name
from mastercontrol.cli import cmd_ai_doctor, cmd_ai_list, cmd_ai_plan, cmd_ai_review
from mastercontrol.config import load_config


class AiConfigTests(unittest.TestCase):
    def test_load_config_has_default_ai_section(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        'profile = "default"',
                        'mode = "work"',
                        'workspace = "~/workspace"',
                        'default_aws_profile = "dev"',
                        "",
                        "[jumps]",
                        'workspace = "~/workspace"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("mastercontrol.config.CONFIG_FILE", config_path):
                config = load_config()

        self.assertEqual(config.ai.default_provider, "codex")
        self.assertEqual(config.ai.default_task_provider["review"], "claude")
        self.assertIn("local", config.ai.providers)

    def test_resolve_provider_name_prefers_task_mapping_and_override(self) -> None:
        config = load_config()
        self.assertEqual(resolve_provider_name(config, "review"), "claude")
        self.assertEqual(resolve_provider_name(config, "review", explicit_provider="local"), "local")


class AiProviderTests(unittest.TestCase):
    def test_provider_statuses_reflect_availability(self) -> None:
        config = load_config()
        with patch("mastercontrol.ai.which", side_effect=lambda cmd: cmd in {"codex", "ollama"}):
            statuses = provider_statuses(config.ai)

        status_map = {status.name: status for status in statuses}
        self.assertTrue(status_map["codex"].available)
        self.assertFalse(status_map["claude"].available)
        self.assertTrue(status_map["local"].available)


class AiCliTests(unittest.TestCase):
    def test_ai_list_outputs_provider_rows(self) -> None:
        stdout = io.StringIO()
        fake_statuses = [
            ProviderStatus("codex", "cli", True, True, "codex", "", "available"),
            ProviderStatus("local", "ollama", True, True, "ollama", "qwen3-coder", "available"),
        ]

        with (
            patch("mastercontrol.cli.load_config", return_value=load_config()),
            patch("mastercontrol.cli.provider_statuses", return_value=fake_statuses),
            redirect_stdout(stdout),
        ):
            code = cmd_ai_list(type("Args", (), {})())

        output = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("codex | cli", output)
        self.assertIn("local | ollama", output)

    def test_ai_doctor_json_reports_missing_provider(self) -> None:
        config = load_config()
        stdout = io.StringIO()
        with (
            patch("mastercontrol.cli.load_config", return_value=config),
            patch("mastercontrol.ai.which", return_value=False),
            redirect_stdout(stdout),
        ):
            code = cmd_ai_doctor(type("Args", (), {"json": True, "quiet": False})())

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertGreaterEqual(payload["summary"]["warn"], 1)
        self.assertEqual(payload["summary"]["fail"], 0)
        self.assertTrue(payload["suggested_actions"])

    def test_ai_review_uses_default_task_provider(self) -> None:
        stdout = io.StringIO()
        with (
            patch(
                "mastercontrol.cli.run_ai_task",
                return_value=type("Resp", (), {"ok": True, "stdout": "reviewed", "stderr": "", "provider": "claude"})(),
            ) as run_mock,
            patch("mastercontrol.cli.load_config", return_value=load_config()),
            redirect_stdout(stdout),
        ):
            code = cmd_ai_review(type("Args", (), {"path": ".", "provider": None})())

        self.assertEqual(code, 0)
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.kwargs["explicit_provider"], None)
        self.assertIn("reviewed", stdout.getvalue())

    def test_ai_plan_provider_override_is_passed_through(self) -> None:
        stdout = io.StringIO()
        with (
            patch(
                "mastercontrol.cli.run_ai_task",
                return_value=type("Resp", (), {"ok": True, "stdout": "planned", "stderr": "", "provider": "local"})(),
            ) as run_mock,
            patch("mastercontrol.cli.load_config", return_value=load_config()),
            redirect_stdout(stdout),
        ):
            code = cmd_ai_plan(type("Args", (), {"task": "add compare", "provider": "local"})())

        self.assertEqual(code, 0)
        self.assertEqual(run_mock.call_args.kwargs["explicit_provider"], "local")
        self.assertIn("planned", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
