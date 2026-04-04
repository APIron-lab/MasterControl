from __future__ import annotations

import unittest

from mastercontrol.config import MasconConfig, build_config_toml
from mastercontrol.services import AwsStatus, CommandResult, aws_check_status


class BuildConfigTomlTests(unittest.TestCase):
    def test_build_config_toml_renders_expected_fields(self) -> None:
        config = MasconConfig(
            profile="apiron",
            mode="work",
            workspace="~/workspace",
            default_aws_profile="dev",
            jumps={
                "workspace": "~/workspace",
                "mastercontrol": "~/workspace/mastercontrol",
            },
        )

        rendered = build_config_toml(config)

        self.assertIn('profile = "apiron"', rendered)
        self.assertIn('mode = "work"', rendered)
        self.assertIn('workspace = "~/workspace"', rendered)
        self.assertIn('default_aws_profile = "dev"', rendered)
        self.assertIn("[jumps]", rendered)
        self.assertIn('workspace = "~/workspace"', rendered)
        self.assertIn('mastercontrol = "~/workspace/mastercontrol"', rendered)


class AwsCheckStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        from mastercontrol import services

        self.services = services
        self.orig_which = services.which
        self.orig_aws_identity = services.aws_identity

    def tearDown(self) -> None:
        self.services.which = self.orig_which
        self.services.aws_identity = self.orig_aws_identity

    def test_profile_not_found_is_classified(self) -> None:
        self.services.which = lambda cmd: cmd == "aws"
        self.services.aws_identity = lambda profile=None: CommandResult(
            ok=False,
            code=255,
            stdout="",
            stderr="The config profile (missing) could not be found",
        )

        status = aws_check_status("missing")

        self.assertIsInstance(status, AwsStatus)
        self.assertEqual(status.reason, "profile_not_found")

    def test_sso_login_required_is_classified(self) -> None:
        self.services.which = lambda cmd: cmd == "aws"
        self.services.aws_identity = lambda profile=None: CommandResult(
            ok=False,
            code=255,
            stdout="",
            stderr="Error loading SSO Token: login required",
        )

        status = aws_check_status("dev")

        self.assertEqual(status.reason, "sso_not_logged_in")


if __name__ == "__main__":
    unittest.main()
