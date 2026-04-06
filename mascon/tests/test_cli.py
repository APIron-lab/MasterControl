from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mastercontrol import __version__
from mastercontrol.cli import (
    TITLE_TEXT,
    animations_enabled,
    build_init_config,
    build_version_line,
    cmd_doctor,
    cmd_repo_ship,
    cmd_start,
    collect_doctor_items,
    get_mascon_version,
)
from mastercontrol.config import MasconConfig
from mastercontrol.services import AwsStatus, RepoState


class DoctorTests(unittest.TestCase):
    def test_collect_doctor_items_marks_invalid_jumps(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            valid_jump = workspace
            invalid_jump = Path(tmpdir) / "missing"
            config = MasconConfig(
                profile="default",
                mode="work",
                workspace=str(workspace),
                default_aws_profile="dev",
                jumps={
                    "workspace": str(valid_jump),
                    "docs": str(invalid_jump),
                },
            )

            with (
                patch("mastercontrol.cli.config_exists", return_value=True),
                patch("mastercontrol.cli.load_config", return_value=config),
                patch("mastercontrol.cli.which", side_effect=lambda cmd: cmd in {"git", "aws", "explorer.exe", "clip.exe"}),
                patch("mastercontrol.cli.scan_repos", return_value=[]),
                patch("mastercontrol.cli.aws_list_profiles", return_value=["dev"]),
                patch(
                    "mastercontrol.cli.aws_check_status",
                    return_value=AwsStatus(ok=True, profile="dev", reason="ok", detail="{}"),
                ),
                patch("mastercontrol.cli.codex_available", return_value=True),
                patch("mastercontrol.cli.is_wsl", return_value=True),
                patch("mastercontrol.cli.get_platform_label", return_value="WSL (Linux)"),
            ):
                items, suggestions = collect_doctor_items()

        jumps_item = next(item for item in items if item.key == "jumps")
        self.assertEqual(jumps_item.status, "warn")
        self.assertIn("docs", jumps_item.detail)
        self.assertIn("Missing jump paths: docs", suggestions)

    def test_cmd_doctor_json_output_has_expected_shape(self) -> None:
        fake_items = [
            type("Item", (), {"status": "ok", "to_dict": lambda self: {"key": "python", "status": "ok", "detail": "3.12.3"}})(),
            type("Item", (), {"status": "warn", "to_dict": lambda self: {"key": "jumps", "status": "warn", "detail": "invalid"}})(),
        ]
        stdout = io.StringIO()

        with (
            patch("mastercontrol.cli.collect_doctor_items", return_value=(fake_items, ["Edit: ~/.config/mascon/config.toml"])),
            redirect_stdout(stdout),
        ):
            code = cmd_doctor(type("Args", (), {"json": True, "quiet": False})())

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"], {"ok": 1, "warn": 1, "fail": 0})
        self.assertEqual(payload["items"][0]["key"], "python")
        self.assertTrue(payload["suggested_actions"])

    def test_collect_doctor_items_adds_actions_for_unknown_aws_auth_warn(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            config = MasconConfig(
                profile="default",
                mode="work",
                workspace=str(workspace),
                default_aws_profile="dev",
                jumps={"workspace": str(workspace)},
            )

            with (
                patch("mastercontrol.cli.config_exists", return_value=True),
                patch("mastercontrol.cli.load_config", return_value=config),
                patch("mastercontrol.cli.which", side_effect=lambda cmd: cmd in {"git", "aws", "explorer.exe", "clip.exe"}),
                patch("mastercontrol.cli.scan_repos", return_value=[]),
                patch("mastercontrol.cli.aws_list_profiles", return_value=["dev"]),
                patch(
                    "mastercontrol.cli.aws_check_status",
                    return_value=AwsStatus(ok=False, profile="dev", reason="unknown_error", detail="boom"),
                ),
                patch("mastercontrol.cli.codex_available", return_value=True),
                patch("mastercontrol.cli.is_wsl", return_value=True),
                patch("mastercontrol.cli.get_platform_label", return_value="WSL (Linux)"),
            ):
                items, suggestions = collect_doctor_items()

        aws_auth_item = next(item for item in items if item.key == "aws auth")
        self.assertEqual(aws_auth_item.status, "warn")
        self.assertIn("Run `mascon aws summary` for detailed AWS auth diagnostics.", suggestions)
        self.assertIn("If you use AWS SSO, try `mascon aws login`.", suggestions)

    def test_cmd_doctor_shows_no_action_required_only_when_clean(self) -> None:
        fake_items = [type("Item", (), {"status": "warn", "key": "aws auth", "detail": "not verified"})()]
        stdout = io.StringIO()

        with (
            patch("mastercontrol.cli.collect_doctor_items", return_value=(fake_items, [])),
            redirect_stdout(stdout),
        ):
            code = cmd_doctor(type("Args", (), {"json": False, "quiet": True})())

        output = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertNotIn("No action required.", output)
        self.assertIn("Review the warnings above", output)


class InitTests(unittest.TestCase):
    def test_build_init_config_can_backup_existing_config(self) -> None:
        inputs = iter(
            [
                "b",
                "default",
                "work",
                "~/workspace",
                "dev",
                "",
                "",
                "",
                "",
            ]
        )

        with (
            patch("builtins.input", side_effect=lambda prompt="": next(inputs)),
            patch("mastercontrol.cli.config_exists", return_value=True),
            patch("mastercontrol.cli.backup_existing_config", return_value=Path("/tmp/config.toml.bak")),
            patch("mastercontrol.cli.aws_list_profiles", return_value=[]),
            patch("mastercontrol.cli.maybe_create_workspace", return_value="~/workspace"),
        ):
            config, backup_path = build_init_config()

        self.assertEqual(config.profile, "default")
        self.assertEqual(config.jumps, {"workspace": "~/workspace"})
        self.assertEqual(backup_path, Path("/tmp/config.toml.bak"))


class RepoShipTests(unittest.TestCase):
    def test_cmd_repo_ship_requires_confirmation_by_default(self) -> None:
        stdout = io.StringIO()
        args = type("Args", (), {"message": "feat: test", "dry_run": False, "yes": False})()
        state = RepoState(
            repo_name="mascon",
            branch="main",
            dirty=True,
            changed_files=3,
            ahead=0,
            behind=0,
            root=Path("/tmp/repo"),
        )

        with (
            patch("mastercontrol.cli.repo_state", return_value=state),
            patch("mastercontrol.cli.prompt_yes_no", return_value=False),
            patch("mastercontrol.cli.repo_ship") as repo_ship_mock,
            redirect_stdout(stdout),
        ):
            code = cmd_repo_ship(args)

        self.assertEqual(code, 2)
        self.assertIn("About to run repository ship:", stdout.getvalue())
        self.assertIn("Cancelled.", stdout.getvalue())
        repo_ship_mock.assert_not_called()

    def test_cmd_repo_ship_skips_confirmation_with_yes(self) -> None:
        stdout = io.StringIO()
        args = type("Args", (), {"message": "feat: test", "dry_run": False, "yes": True})()

        with (
            patch("mastercontrol.cli.repo_ship", return_value=["push: ok"]) as repo_ship_mock,
            redirect_stdout(stdout),
        ):
            code = cmd_repo_ship(args)

        self.assertEqual(code, 0)
        repo_ship_mock.assert_called_once()
        self.assertIn("push: ok", stdout.getvalue())


class StartupIntroTests(unittest.TestCase):
    def test_get_mascon_version_returns_package_version(self) -> None:
        self.assertEqual(get_mascon_version(), __version__)

    def test_build_version_line_contains_title_and_version(self) -> None:
        line = build_version_line(__version__, 80)
        self.assertIn(TITLE_TEXT, line)
        self.assertIn(f"Version {__version__}", line)

    def test_animations_enabled_respects_no_anim_flag(self) -> None:
        with (
            patch("sys.stdout.isatty", return_value=True),
            patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
        ):
            self.assertFalse(animations_enabled(type("Args", (), {"no_anim": True})()))

    def test_animations_enabled_respects_env_and_term_dumb(self) -> None:
        with (
            patch("sys.stdout.isatty", return_value=True),
            patch.dict(os.environ, {"MASCON_NO_ANIM": "1", "TERM": "dumb"}, clear=False),
        ):
            self.assertFalse(animations_enabled(type("Args", (), {"no_anim": False})()))

    def test_cmd_start_uses_intro_then_existing_flow(self) -> None:
        args = type("Args", (), {"no_anim": True, "auto_login": False})()
        with (
            patch("mastercontrol.cli.show_startup_intro") as intro_mock,
            patch("mastercontrol.cli.print_boot_checks") as boot_mock,
            patch("mastercontrol.cli.show_dashboard") as dashboard_mock,
            patch("mastercontrol.cli.interactive_loop") as loop_mock,
        ):
            code = cmd_start(args)

        self.assertEqual(code, 0)
        intro_mock.assert_called_once_with(no_anim=True)
        boot_mock.assert_called_once_with(auto_login=False)
        dashboard_mock.assert_called_once()
        loop_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
