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
    cmd_jump,
    cmd_repo_ship,
    cmd_start,
    collect_doctor_items,
    get_mascon_version,
    interactive_loop,
    maybe_record_repl_history,
    repl_expand_bare_command,
    repl_completion_candidates,
    show_dashboard,
)
from mastercontrol.config import AiConfig, AiProfileConfig, MasconConfig
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
            patch("mastercontrol.cli.maybe_create_workspace", return_value="~/workspace"),
        ):
            config, backup_path = build_init_config()

        self.assertEqual(config.profile, "default")
        self.assertEqual(config.jumps, {"workspace": "~/workspace"})
        self.assertEqual(config.default_aws_profile, "default")
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


class JumpTests(unittest.TestCase):
    def test_cmd_jump_list_prints_configured_jumps(self) -> None:
        config = MasconConfig(jumps={"workspace": "~/workspace", "docs": "~/workspace/docs"})
        stdout = io.StringIO()
        with (
            patch("mastercontrol.cli.load_config", return_value=config),
            redirect_stdout(stdout),
        ):
            code = cmd_jump(type("Args", (), {"jump_args": ["list"]})())

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("workspace", output)
        self.assertIn("~/workspace/docs", output)

    def test_cmd_jump_add_saves_new_jump(self) -> None:
        config = MasconConfig(jumps={"workspace": "~/workspace"})
        stdout = io.StringIO()
        with (
            patch("mastercontrol.cli.load_config", return_value=config),
            patch("mastercontrol.cli.save_config") as save_mock,
            redirect_stdout(stdout),
        ):
            code = cmd_jump(type("Args", (), {"jump_args": ["add", "docs", "~/workspace/docs"]})())

        self.assertEqual(code, 0)
        self.assertEqual(config.jumps["docs"], "~/workspace/docs")
        save_mock.assert_called_once_with(config)
        self.assertIn("Saved jump: docs -> ~/workspace/docs", stdout.getvalue())

    def test_cmd_jump_add_rejects_existing_name(self) -> None:
        config = MasconConfig(jumps={"docs": "~/workspace/docs"})
        stderr = io.StringIO()
        with (
            patch("mastercontrol.cli.load_config", return_value=config),
            patch("sys.stderr", stderr),
        ):
            code = cmd_jump(type("Args", (), {"jump_args": ["add", "docs", "~/other"]})())

        self.assertEqual(code, 1)
        self.assertIn("Jump already exists: docs", stderr.getvalue())

    def test_cmd_jump_remove_deletes_existing_jump(self) -> None:
        config = MasconConfig(jumps={"workspace": "~/workspace", "docs": "~/workspace/docs"})
        stdout = io.StringIO()
        with (
            patch("mastercontrol.cli.load_config", return_value=config),
            patch("mastercontrol.cli.save_config") as save_mock,
            redirect_stdout(stdout),
        ):
            code = cmd_jump(type("Args", (), {"jump_args": ["remove", "docs"]})())

        self.assertEqual(code, 0)
        self.assertNotIn("docs", config.jumps)
        save_mock.assert_called_once_with(config)
        self.assertIn("Removed jump: docs", stdout.getvalue())

    def test_cmd_jump_remove_errors_for_missing_name(self) -> None:
        config = MasconConfig(jumps={"workspace": "~/workspace"})
        stderr = io.StringIO()
        with (
            patch("mastercontrol.cli.load_config", return_value=config),
            patch("sys.stderr", stderr),
        ):
            code = cmd_jump(type("Args", (), {"jump_args": ["remove", "docs"]})())

        self.assertEqual(code, 1)
        self.assertIn("Unknown jump: docs", stderr.getvalue())

    def test_cmd_jump_lookup_still_resolves_existing_name(self) -> None:
        config = MasconConfig(jumps={"workspace": "~/workspace"})
        stdout = io.StringIO()
        with (
            patch("mastercontrol.cli.load_config", return_value=config),
            patch("mastercontrol.cli.expand_path", return_value=Path("/tmp/workspace")),
            redirect_stdout(stdout),
        ):
            code = cmd_jump(type("Args", (), {"jump_args": ["workspace"]})())

        self.assertEqual(code, 0)
        self.assertIn("/tmp/workspace", stdout.getvalue())


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

    def test_show_dashboard_prints_environment_and_suggestions(self) -> None:
        config = MasconConfig(profile="default", mode="work", workspace="~/workspace", jumps={"workspace": "~/workspace"})
        config.ai = AiConfig(profiles={}, default_profile="")
        stdout = io.StringIO()

        with (
            patch("mastercontrol.cli.load_config", return_value=config),
            patch("mastercontrol.cli.scan_repos", return_value=[]),
            patch("mastercontrol.cli.codex_available", return_value=True),
            patch("mastercontrol.cli.which", side_effect=lambda cmd: cmd == "aws"),
            patch("mastercontrol.cli.aws_list_profiles", return_value=[]),
            redirect_stdout(stdout),
        ):
            show_dashboard()

        output = stdout.getvalue()
        self.assertIn("Environment", output)
        self.assertIn("AI profiles : not configured", output)
        self.assertIn("Cloud auth  : not configured", output)
        self.assertIn("Suggested actions", output)
        self.assertIn("mascon ai register", output)


class ReplTests(unittest.TestCase):
    def test_maybe_record_repl_history_skips_when_readline_already_added(self) -> None:
        fake_readline = type(
            "FakeReadline",
            (),
            {
                "get_current_history_length": staticmethod(lambda: 3),
                "add_history": staticmethod(lambda _value: (_ for _ in ()).throw(AssertionError("should not add"))),
            },
        )()
        with patch("mastercontrol.cli.readline", fake_readline):
            maybe_record_repl_history("help", 2)

    def test_maybe_record_repl_history_adds_once_when_readline_did_not(self) -> None:
        added: list[str] = []
        fake_readline = type(
            "FakeReadline",
            (),
            {
                "get_current_history_length": staticmethod(lambda: 2),
                "add_history": staticmethod(lambda value: added.append(value)),
            },
        )()
        with patch("mastercontrol.cli.readline", fake_readline):
            maybe_record_repl_history("help", 2)

        self.assertEqual(added, ["help"])

    def test_repl_completion_suggests_top_level_commands(self) -> None:
        candidates = repl_completion_candidates("a", "a", 0, 1)
        self.assertIn("ai", candidates)
        self.assertIn("aws", candidates)

    def test_repl_completion_suggests_ai_subcommands(self) -> None:
        candidates = repl_completion_candidates("ai r", "r", 3, 4)
        self.assertIn("register", candidates)
        self.assertIn("review", candidates)
        self.assertIn("run", candidates)

    def test_repl_completion_suggests_profile_names(self) -> None:
        config = MasconConfig()
        config.ai = AiConfig(
            profiles={
                "sophia": AiProfileConfig(type="ollama", model="qwen2.5:7b"),
                "coder": AiProfileConfig(type="llama.cpp", model_path="~/models/coder.gguf"),
            }
        )
        with patch("mastercontrol.cli.load_config", return_value=config):
            use_candidates = repl_completion_candidates("ai use s", "s", 7, 8)
            chat_candidates = repl_completion_candidates("ai chat -p s", "s", 11, 12)

        self.assertIn("sophia", use_candidates)
        self.assertIn("sophia", chat_candidates)

    def test_repl_completion_suggests_jump_management_and_names(self) -> None:
        config = MasconConfig(jumps={"workspace": "~/workspace", "docs": "~/workspace/docs"})
        with patch("mastercontrol.cli.load_config", return_value=config):
            bare_candidates = repl_completion_candidates("jump ", "", 5, 5)
            named_candidates = repl_completion_candidates("jump d", "d", 5, 6)

        self.assertIn("list", bare_candidates)
        self.assertIn("add", bare_candidates)
        self.assertIn("remove", bare_candidates)
        self.assertIn("docs", named_candidates)

    def test_interactive_loop_dispatches_to_run_cli(self) -> None:
        with (
            patch("mastercontrol.cli.setup_repl_readline"),
            patch("builtins.input", side_effect=["ai list", "exit"]),
            patch("mastercontrol.cli.run_cli", return_value=0) as run_cli_mock,
        ):
            interactive_loop()

        run_cli_mock.assert_called_once_with(["mascon", "ai", "list"])

    def test_repl_expand_bare_command_routes_to_help(self) -> None:
        self.assertEqual(repl_expand_bare_command("ai"), ["mascon", "ai", "--help"])
        self.assertEqual(repl_expand_bare_command("repo"), ["mascon", "repo", "--help"])
        self.assertEqual(repl_expand_bare_command("aws"), ["mascon", "aws", "--help"])
        self.assertEqual(repl_expand_bare_command("path"), ["mascon", "path", "--help"])
        self.assertEqual(repl_expand_bare_command("jump"), ["mascon", "jump", "--help"])
        self.assertEqual(repl_expand_bare_command("ai list"), ["mascon", "ai", "list"])


if __name__ == "__main__":
    unittest.main()
