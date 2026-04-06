from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import tomllib

from . import __version__ as package_version
from .ai import (
    collect_ai_doctor,
    provider_statuses,
    resolve_provider_name,
    run_ai_prompt,
    run_ai_task,
)
from .config import (
    CONFIG_FILE,
    MasconConfig,
    backup_existing_config,
    build_config_toml,
    config_exists,
    ensure_config_dir,
    expand_path,
    load_config,
    save_config,
)
from .services import (
    DoctorItem,
    aws_check_status,
    aws_identity,
    aws_list_profiles,
    aws_requires_login,
    aws_sso_login,
    codex_available,
    copy_to_clipboard,
    get_platform_label,
    is_wsl,
    json_dumps_pretty,
    open_in_explorer,
    python_version_ok,
    repo_ship,
    repo_state,
    scan_repos,
    to_windows_path,
    to_wsl_path,
    which,
)


ASCII_LOGO = r"""
 __  __           _             ____            _             _
|  \/  | __ _ ___| |_ ___ _ __ / ___|___  _ __ | |_ _ __ ___ | |
| |\/| |/ _` / __| __/ _ \ '__| |   / _ \| '_ \| __| '__/ _ \| |
| |  | | (_| \__ \ ||  __/ |  | |__| (_) | | | | |_| | | (_) | |
|_|  |_|\__,_|___/\__\___|_|   \____\___/|_| |_|\__|_|  \___/|_|
"""

TITLE_TEXT = "M A S T E R   C O N T R O L"


def print_banner() -> None:
    print(ASCII_LOGO)
    print()
    print(TITLE_TEXT.center(get_terminal_width()))


def get_mascon_version() -> str:
    try:
        return str(package_version)
    except Exception:
        return "unknown"


def animations_enabled(args: argparse.Namespace) -> bool:
    if getattr(args, "no_anim", False):
        return False
    if os.environ.get("MASCON_NO_ANIM") == "1":
        return False
    if not sys.stdout.isatty():
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    return True


def get_terminal_width(default: int = 80) -> int:
    return shutil.get_terminal_size((default, 24)).columns


def build_version_line(version: str, width: int) -> str:
    return f"{TITLE_TEXT}   Version {version}".center(width)


def ansi_dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def ansi_bright(text: str) -> str:
    return f"\033[97m{text}\033[0m"


def clear_screen_soft() -> None:
    sys.stdout.write("\033[H\033[J")
    sys.stdout.flush()


def render_banner_frame(lines: list[str], version_line: str | None = None) -> None:
    width = get_terminal_width()
    centered = [line.center(width) if line else "" for line in lines]
    print("\n".join(centered))
    print()
    if version_line is not None:
        print(version_line)


def render_static_banner(version: str) -> None:
    width = get_terminal_width()
    render_banner_frame(ASCII_LOGO.splitlines(), build_version_line(version, width))


def render_staged_banner(version: str, total_ms: int = 1100) -> None:
    logo_lines = ASCII_LOGO.splitlines()
    width = get_terminal_width()
    version_text = build_version_line(version, width)
    stages = [2, 4, len(logo_lines)]
    delays = [0.22, 0.22, 0.22, 0.18, 0.18]

    clear_screen_soft()
    for index, count in enumerate(stages):
        clear_screen_soft()
        version_line = ansi_dim(version_text) if count == len(logo_lines) else None
        render_banner_frame(logo_lines[:count], version_line)
        time.sleep(delays[index])

    clear_screen_soft()
    render_banner_frame(logo_lines, ansi_bright(version_text))
    time.sleep(delays[3])
    clear_screen_soft()
    render_banner_frame(logo_lines, version_text)
    time.sleep(delays[4])


def show_startup_intro(no_anim: bool = False) -> None:
    version = get_mascon_version()
    args = argparse.Namespace(no_anim=no_anim)
    if animations_enabled(args):
        render_staged_banner(version)
        return
    render_static_banner(version)


def aws_reason_label(reason: str) -> str:
    mapping = {
        "ok": "ok",
        "profile_not_found": "profile not found",
        "sso_token_expired": "sso token expired",
        "sso_not_logged_in": "sso login required",
        "sso_login_required": "sso login required",
        "aws_cli_not_found": "aws cli not found",
        "unknown_error": "not verified",
    }
    return mapping.get(reason, reason)


def maybe_login_aws(profile: str, auto_login: bool) -> bool:
    status = aws_check_status(profile)
    if status.ok:
        return True

    if not aws_requires_login(status):
        return False

    if auto_login:
        print(f"[ WARN ] aws       : {profile} ({aws_reason_label(status.reason)})")
        print("AWS SSO login required. Running login automatically...")
        code = aws_sso_login(profile)
        return code == 0

    print(f"[ WARN ] aws       : {profile} ({aws_reason_label(status.reason)})")
    answer = input("Run AWS login now? [Y/n]: ").strip().lower()
    if answer in {"", "y", "yes"}:
        code = aws_sso_login(profile)
        return code == 0
    return False


def print_boot_checks(auto_login: bool = False) -> None:
    config = load_config()
    workspace = config.workspace_path
    repos = scan_repos(workspace)
    profile = config.default_aws_profile

    aws_status = aws_check_status(profile)
    if not aws_status.ok and aws_requires_login(aws_status):
        logged_in = maybe_login_aws(profile, auto_login=auto_login)
        if logged_in:
            aws_status = aws_check_status(profile)

    print(f"[ OK ] profile   : {config.profile}")
    print(f"[ OK ] platform  : {get_platform_label()}")
    print(f"[ OK ] workspace : {len(repos)} repositories detected")
    print(f"[ {'OK' if codex_available() else 'WARN'} ] codex     : {'available' if codex_available() else 'not found'}")

    if aws_status.ok:
        print(f"[ OK ] aws       : {profile}")
    else:
        print(f"[ WARN ] aws       : {profile} ({aws_reason_label(aws_status.reason)})")

    print(f"[ OK ] mode      : {config.mode}")
    print()
    print("Entering dashboard...")
    print()


def show_dashboard() -> None:
    config = load_config()
    workspace = config.workspace_path
    repos = scan_repos(workspace)
    dirty = [r for r in repos if r.dirty]

    print("─" * 72)
    print(f"Profile: {config.profile} | Mode: {config.mode} | Workspace: {workspace}")
    print("─" * 72)
    print("Repositories")
    if not repos:
        print("  (no repositories found)")
    else:
        for repo in repos[:8]:
            status = "dirty" if repo.dirty else "clean"
            print(
                f"  - {repo.repo_name:<24} {status:<5} "
                f"branch={repo.branch:<20} changed={repo.changed_files:<3} "
                f"ahead={repo.ahead:<2} behind={repo.behind:<2}"
            )
    print("─" * 72)
    print(f"Dirty repos: {len(dirty)} | Codex: {'ready' if codex_available() else 'missing'}")
    print("Type 'help' for interactive commands, 'exit' to leave.")
    print("─" * 72)


def prompt_text(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    entered = input(f"{label}{suffix}: ").strip()
    if not entered and default is not None:
        return default
    return entered


def prompt_yes_no(label: str, default_yes: bool = True) -> bool:
    hint = "[Y/n]" if default_yes else "[y/N]"
    entered = input(f"{label} {hint}: ").strip().lower()
    if not entered:
        return default_yes
    return entered in {"y", "yes"}


def prompt_choice(label: str, choices: dict[str, str]) -> str:
    print(label)
    for key, value in choices.items():
        print(f"  {key}) {value}")
    while True:
        entered = input(f"Select [{'/'.join(choices)}]: ").strip()
        if entered in choices:
            return entered
        print(f"Please enter one of: {', '.join(choices)}")


def maybe_create_workspace(path_text: str) -> str:
    path = expand_path(path_text)
    if path.exists():
        return path_text
    print(f"Workspace does not exist: {path}")
    if prompt_yes_no("Create it now?", default_yes=True):
        path.mkdir(parents=True, exist_ok=True)
        return path_text
    raise KeyboardInterrupt


def prompt_optional_jump(name: str, suggested: str) -> str | None:
    print(f"Optional jump '{name}'")
    entered = input(f"Path [{suggested}] (leave blank to skip): ").strip()
    if not entered:
        return None
    return entered


def build_init_config() -> tuple[MasconConfig, Path | None]:
    backup_path: Path | None = None
    if config_exists():
        choice = prompt_choice(
            "Existing config file detected.",
            {
                "k": "keep current config and cancel init",
                "o": "overwrite current config",
                "b": "backup current config and overwrite",
            },
        )
        if choice == "k":
            raise KeyboardInterrupt
        if choice == "b":
            backup_path = backup_existing_config()

    print()
    profile = prompt_text("Profile", "default")
    mode = prompt_text("Mode", "work")
    workspace = maybe_create_workspace(prompt_text("Workspace", "~/workspace"))

    aws_profiles = aws_list_profiles()
    default_aws_profile = "default"
    if aws_profiles:
        print("Available AWS profiles:")
        for name in aws_profiles:
            print(f"  - {name}")
        default_aws_profile = aws_profiles[0]
    aws_profile = prompt_text("Default AWS profile", default_aws_profile)

    jumps: dict[str, str] = {"workspace": workspace}
    for name, suggested in {
        "mastercontrol": "~/workspace/mastercontrol",
        "projects": "~/workspace/projects",
        "docs": "~/workspace/docs",
        "tools": "~/workspace/tools",
    }.items():
        value = prompt_optional_jump(name, suggested)
        if value:
            jumps[name] = value

    config = MasconConfig(
        profile=profile,
        mode=mode,
        workspace=workspace,
        default_aws_profile=aws_profile,
        jumps=jumps,
    )
    return config, backup_path


def doctor_item(key: str, status: str, detail: str) -> DoctorItem:
    return DoctorItem(key=key, status=status, detail=detail)


def suggest_edit_config() -> str:
    return f"Edit: {CONFIG_FILE}"


def aws_doctor_suggestions(reason: str) -> list[str]:
    if reason == "sso_token_expired":
        return ["Run `mascon aws login` to refresh AWS SSO."]
    if reason in {"sso_not_logged_in", "sso_login_required"}:
        return ["Run `mascon aws login`."]
    if reason == "profile_not_found":
        return [
            f"Check `default_aws_profile` in `{CONFIG_FILE}`.",
            "Run `aws configure list-profiles` to see available profiles.",
        ]
    if reason == "aws_cli_not_found":
        return ["Install AWS CLI and retry."]
    if reason in {"unknown_error", "not verified"}:
        return [
            "Run `mascon aws summary` for detailed AWS auth diagnostics.",
            "If you use AWS SSO, try `mascon aws login`.",
        ]
    return []


def collect_doctor_items() -> tuple[list[DoctorItem], list[str]]:
    items: list[DoctorItem] = []
    suggestions: list[str] = []

    py_ok, py_version = python_version_ok()
    items.append(doctor_item("python", "ok" if py_ok else "fail", py_version))

    platform_label = get_platform_label()
    items.append(doctor_item("platform", "ok" if is_wsl() else "warn", platform_label))

    config: MasconConfig | None = None
    if not config_exists():
        items.append(doctor_item("config", "fail", f"missing: {CONFIG_FILE}"))
        suggestions.append("Run `mascon init` to create the config file.")
    else:
        try:
            config = load_config()
            items.append(doctor_item("config", "ok", f"loaded from {CONFIG_FILE}"))
        except tomllib.TOMLDecodeError as exc:
            items.append(doctor_item("config", "fail", f"invalid TOML: {exc}"))
            suggestions.append(suggest_edit_config())
        except Exception as exc:
            items.append(doctor_item("config", "fail", f"failed to load config: {exc}"))
            suggestions.append(suggest_edit_config())

    workspace: Path | None = None
    if config is not None:
        workspace = config.workspace_path
        if workspace.exists():
            items.append(doctor_item("workspace", "ok", str(workspace)))
        else:
            items.append(doctor_item("workspace", "fail", f"missing: {workspace}"))
            suggestions.append("Create the configured workspace or update `workspace` in config.")
    else:
        items.append(doctor_item("workspace", "warn", "skipped because config is unavailable"))

    git_present = which("git")
    items.append(doctor_item("git", "ok" if git_present else "fail", "git found" if git_present else "git not found"))
    if not git_present:
        suggestions.append("Install Git.")

    if workspace is not None and workspace.exists():
        try:
            repo_count = len(scan_repos(workspace))
            status = "ok" if repo_count > 0 else "warn"
            detail = f"{repo_count} repositories under {workspace}"
            items.append(doctor_item("repos", status, detail))
            if repo_count == 0:
                suggestions.append("Clone repositories into the configured workspace if expected.")
        except Exception as exc:
            items.append(doctor_item("repos", "warn", f"scan failed: {exc}"))
    else:
        items.append(doctor_item("repos", "warn", "skipped because workspace is unavailable"))

    aws_cli_present = which("aws")
    items.append(doctor_item("aws cli", "ok" if aws_cli_present else "fail", "aws found" if aws_cli_present else "aws not found"))
    if not aws_cli_present:
        suggestions.append("Install AWS CLI.")

    if config is not None:
        profiles = aws_list_profiles()
        if not aws_cli_present:
            items.append(doctor_item("aws profile", "warn", "skipped because AWS CLI is unavailable"))
            items.append(doctor_item("aws auth", "warn", "skipped because AWS CLI is unavailable"))
            suggestions.extend(aws_doctor_suggestions("aws_cli_not_found"))
        elif config.default_aws_profile in profiles:
            items.append(doctor_item("aws profile", "ok", config.default_aws_profile))
            aws_status = aws_check_status(config.default_aws_profile)
            if aws_status.ok:
                items.append(doctor_item("aws auth", "ok", "authenticated"))
            elif aws_requires_login(aws_status):
                items.append(doctor_item("aws auth", "warn", aws_reason_label(aws_status.reason)))
                suggestions.extend(aws_doctor_suggestions(aws_status.reason))
            elif aws_status.reason == "profile_not_found":
                items.append(doctor_item("aws auth", "fail", "configured AWS profile was not found"))
                suggestions.extend(aws_doctor_suggestions(aws_status.reason))
            else:
                items.append(doctor_item("aws auth", "warn", aws_reason_label(aws_status.reason)))
                suggestions.extend(aws_doctor_suggestions(aws_status.reason))
        else:
            items.append(
                doctor_item(
                    "aws profile",
                    "fail",
                    f"profile not found: {config.default_aws_profile}",
                )
            )
            items.append(doctor_item("aws auth", "warn", "skipped because profile was not found"))
            suggestions.extend(aws_doctor_suggestions("profile_not_found"))
    else:
        items.append(doctor_item("aws profile", "warn", "skipped because config is unavailable"))
        items.append(doctor_item("aws auth", "warn", "skipped because config is unavailable"))

    codex_present = codex_available()
    items.append(doctor_item("codex", "ok" if codex_present else "warn", "codex found" if codex_present else "codex not found"))
    if not codex_present:
        suggestions.append("Install or expose `codex` in PATH if you plan to use it.")

    if is_wsl():
        explorer_present = which("explorer.exe")
        clip_present = which("clip.exe")
        items.append(
            doctor_item(
                "explorer.exe",
                "ok" if explorer_present else "warn",
                "explorer.exe found" if explorer_present else "explorer.exe not found",
            )
        )
        items.append(
            doctor_item(
                "clip.exe",
                "ok" if clip_present else "warn",
                "clip.exe found" if clip_present else "clip.exe not found",
            )
        )
    else:
        items.append(doctor_item("explorer.exe", "warn", "not running under WSL"))
        items.append(doctor_item("clip.exe", "warn", "not running under WSL"))

    if config is not None:
        if not config.jumps:
            items.append(doctor_item("jumps", "warn", "no jumps configured"))
            suggestions.append("Add at least a `workspace` jump in config.")
        else:
            invalid = [name for name, value in config.jumps.items() if not expand_path(value).exists()]
            if invalid:
                items.append(doctor_item("jumps", "warn", f"invalid jumps: {', '.join(invalid)}"))
                suggestions.append("Run `mascon init` to update jump paths.")
                suggestions.append(suggest_edit_config())
                suggestions.append(f"Missing jump paths: {', '.join(invalid)}")
            else:
                items.append(doctor_item("jumps", "ok", f"{len(config.jumps)} jumps valid"))
    else:
        items.append(doctor_item("jumps", "warn", "skipped because config is unavailable"))

    return items, sorted(set(suggestions))


def format_status(status: str) -> str:
    if status == "ok":
        return "[ OK ]"
    if status == "warn":
        return "[ WARN ]"
    return "[ FAIL ]"


def print_doctor_report(title: str, items: list[DoctorItem], suggestions: list[str], quiet: bool = False) -> int:
    summary = {
        "ok": sum(1 for item in items if item.status == "ok"),
        "warn": sum(1 for item in items if item.status == "warn"),
        "fail": sum(1 for item in items if item.status == "fail"),
    }

    print(title)
    print("─" * 72)
    for item in items:
        if quiet and item.status == "ok":
            continue
        print(f"{format_status(item.status)} {item.key:<24} {item.detail}")

    print("─" * 72)
    print(f"Summary: OK={summary['ok']} WARN={summary['warn']} FAIL={summary['fail']}")
    print("Suggested actions:")
    if suggestions:
        for suggestion in suggestions:
            print(f"  - {suggestion}")
    elif summary["warn"] == 0 and summary["fail"] == 0:
        print("  - No action required.")
    else:
        print("  - Review the warnings above and investigate the reported checks.")
    return 1 if summary["fail"] else 0


def cmd_init(_: argparse.Namespace) -> int:
    try:
        ensure_config_dir()
        print_banner()
        print("Interactive setup")
        print()
        config, backup_path = build_init_config()
        print()
        print("Configuration preview")
        print("─" * 72)
        print(build_config_toml(config))
        print("─" * 72)
        if not prompt_yes_no("Write this config file?", default_yes=True):
            print("Cancelled.")
            return 2
        save_config(config)
        print(f"Wrote config: {CONFIG_FILE}")
        if backup_path is not None:
            print(f"Backup saved: {backup_path}")
        print("Run `mascon doctor` to validate this environment.")
        return 0
    except KeyboardInterrupt:
        print()
        print("Cancelled.")
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        items, suggestions = collect_doctor_items()
        summary = {
            "ok": sum(1 for item in items if item.status == "ok"),
            "warn": sum(1 for item in items if item.status == "warn"),
            "fail": sum(1 for item in items if item.status == "fail"),
        }

        if args.json:
            print(
                json_dumps_pretty(
                    {
                        "items": [item.to_dict() for item in items],
                        "summary": summary,
                        "suggested_actions": suggestions,
                    }
                )
            )
            return 1 if summary["fail"] else 0

        return print_doctor_report("Mascon doctor", items, suggestions, quiet=args.quiet)
    except Exception as exc:
        print(f"ERROR: doctor failed: {exc}", file=sys.stderr)
        return 2


def cmd_ai_doctor(args: argparse.Namespace) -> int:
    try:
        config = load_config()
        items, suggestions = collect_ai_doctor(config)
        summary = {
            "ok": sum(1 for item in items if item.status == "ok"),
            "warn": sum(1 for item in items if item.status == "warn"),
            "fail": sum(1 for item in items if item.status == "fail"),
        }
        if args.json:
            print(
                json_dumps_pretty(
                    {
                        "items": [item.to_dict() for item in items],
                        "summary": summary,
                        "suggested_actions": suggestions,
                    }
                )
            )
            return 1 if summary["fail"] else 0
        return print_doctor_report("Mascon AI doctor", items, suggestions, quiet=args.quiet)
    except Exception as exc:
        print(f"ERROR: ai doctor failed: {exc}", file=sys.stderr)
        return 2


def cmd_ai_list(_: argparse.Namespace) -> int:
    config = load_config()
    statuses = provider_statuses(config.ai)
    if not statuses:
        print("No AI providers configured.")
        return 1
    for status in statuses:
        availability = "available" if status.available else "not found"
        enabled = "enabled" if status.enabled else "disabled"
        extra = f" command={status.command}"
        if status.model:
            extra += f" model={status.model}"
        print(f"{status.name} | {status.type} | {enabled} | {availability}{extra}")
    return 0


def run_ai_and_print(task: str, target: str, provider_name: str | None = None) -> int:
    config = load_config()
    response = run_ai_task(config, task, target, explicit_provider=provider_name)
    if response.ok:
        if response.stdout:
            print(response.stdout)
        return 0
    print(response.stderr or response.stdout or f"{response.provider} command failed.", file=sys.stderr)
    return 1


def cmd_ai_review(args: argparse.Namespace) -> int:
    target = str(expand_path(args.path)) if args.path not in {".", ".."} else str(Path(args.path).resolve())
    return run_ai_and_print("review", target, provider_name=args.provider)


def cmd_ai_explain(args: argparse.Namespace) -> int:
    target = str(expand_path(args.path)) if args.path not in {".", ".."} else str(Path(args.path).resolve())
    return run_ai_and_print("explain", target, provider_name=args.provider)


def cmd_ai_plan(args: argparse.Namespace) -> int:
    return run_ai_and_print("plan", args.task, provider_name=args.provider)


def cmd_ai_run(args: argparse.Namespace) -> int:
    config = load_config()
    response = run_ai_prompt(config, args.provider, args.prompt)
    if response.ok:
        if response.stdout:
            print(response.stdout)
        return 0
    print(response.stderr or response.stdout or f"{response.provider} command failed.", file=sys.stderr)
    return 1


def cmd_start(args: argparse.Namespace) -> int:
    show_startup_intro(no_anim=not animations_enabled(args))
    print_boot_checks(auto_login=args.auto_login)
    show_dashboard()
    interactive_loop()
    return 0


def interactive_loop() -> None:
    while True:
        try:
            raw = input("mascon> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not raw:
            continue
        if raw in {"exit", "quit"}:
            return
        if raw == "help":
            print(
                "Commands: init | doctor | ai doctor | ai review . | repo check | repo dirty | aws whoami | aws login | "
                "path win . | open . | jump <name> | codex | codex ask \"...\" | exit"
            )
            continue
        argv = ["mascon", *shlex.split(raw)]
        try:
            code = run_cli(argv)
            if code != 0:
                print(f"Command exited with status {code}")
        except SystemExit as exc:
            if int(exc.code or 0) != 0:
                print(f"Command exited with status {exc.code}")
        except Exception as exc:
            print(f"ERROR: {exc}")


def cmd_repo_check(_: argparse.Namespace) -> int:
    state = repo_state(Path.cwd())
    print(f"repo    : {state.repo_name}")
    print(f"branch  : {state.branch}")
    print(f"root    : {state.root}")
    print(f"dirty   : {state.dirty}")
    print(f"changed : {state.changed_files}")
    print(f"ahead   : {state.ahead}")
    print(f"behind  : {state.behind}")
    return 0


def cmd_repo_dirty(_: argparse.Namespace) -> int:
    config = load_config()
    repos = [repo for repo in scan_repos(config.workspace_path) if repo.dirty]
    if not repos:
        print("No dirty repositories found.")
        return 0
    for repo in repos:
        print(f"{repo.repo_name}\tbranch={repo.branch}\tchanged={repo.changed_files}\t{repo.root}")
    return 0


def cmd_repo_scan(_: argparse.Namespace) -> int:
    config = load_config()
    repos = scan_repos(config.workspace_path)
    if not repos:
        print("No repositories found.")
        return 0
    for repo in repos:
        status = "dirty" if repo.dirty else "clean"
        print(
            f"{repo.repo_name}\t{status}\tbranch={repo.branch}\t"
            f"ahead={repo.ahead}\tbehind={repo.behind}\t{repo.root}"
        )
    return 0


def cmd_repo_ship(args: argparse.Namespace) -> int:
    if not args.dry_run and not args.yes:
        state = repo_state(Path.cwd())
        print("About to run repository ship:")
        print(f"  branch       : {state.branch}")
        print(f"  changed files: {state.changed_files}")
        print("  actions      : git pull --rebase, git add -A, git commit, git push")
        if not prompt_yes_no("Continue?", default_yes=False):
            print("Cancelled.")
            return 2
    logs = repo_ship(Path.cwd(), args.message, dry_run=args.dry_run)
    for line in logs:
        print(line)
    return 0


def cmd_aws_whoami(_: argparse.Namespace) -> int:
    config = load_config()
    result = aws_identity(config.default_aws_profile)
    if result.ok:
        print(result.stdout)
        return 0
    print(result.stderr or result.stdout or "AWS identity check failed.", file=sys.stderr)
    return 1


def cmd_aws_profile(_: argparse.Namespace) -> int:
    config = load_config()
    print(config.default_aws_profile)
    return 0


def cmd_aws_summary(_: argparse.Namespace) -> int:
    config = load_config()
    status = aws_check_status(config.default_aws_profile)
    print(f"profile: {config.default_aws_profile}")
    print(f"status : {'ok' if status.ok else 'warn'}")
    print(f"reason : {aws_reason_label(status.reason)}")
    if status.detail:
        print(status.detail)
    return 0 if status.ok else 1


def cmd_aws_login(_: argparse.Namespace) -> int:
    config = load_config()
    return aws_sso_login(config.default_aws_profile)


def cmd_codex(args: argparse.Namespace) -> int:
    if not codex_available():
        print("codex command was not found in PATH.", file=sys.stderr)
        return 1
    cmd = ["codex"]
    if args.codex_args:
        cmd.extend(args.codex_args)
    completed = subprocess.run(cmd)
    return int(completed.returncode)


def cmd_path_win(args: argparse.Namespace) -> int:
    target = expand_path(args.target) if args.target not in {".", ".."} else Path(args.target).resolve()
    converted = to_windows_path(target)
    print(converted)
    if args.copy:
        copy_to_clipboard(converted)
        print("(copied)")
    return 0


def cmd_path_wsl(args: argparse.Namespace) -> int:
    converted = to_wsl_path(args.target)
    print(converted)
    if args.copy:
        copy_to_clipboard(converted)
        print("(copied)")
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    target = expand_path(args.target) if args.target not in {".", ".."} else Path(args.target).resolve()
    open_in_explorer(target)
    print(f"Opened: {target}")
    return 0


def cmd_jump(args: argparse.Namespace) -> int:
    config = load_config()
    if args.name not in config.jumps:
        print(f"Unknown jump: {args.name}", file=sys.stderr)
        return 1
    print(str(expand_path(config.jumps[args.name])))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mascon", description="Master Control personal CLI for WSL workflows")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Interactive initial setup")
    init_p.set_defaults(func=cmd_init)

    doctor_p = sub.add_parser("doctor", help="Run environment diagnostics")
    doctor_p.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    doctor_p.add_argument("--quiet", action="store_true", help="Show WARN / FAIL only")
    doctor_p.set_defaults(func=cmd_doctor)

    ai_p = sub.add_parser("ai", help="AI task and provider commands")
    ai_sub = ai_p.add_subparsers(dest="ai_command", required=True)

    ai_doctor_p = ai_sub.add_parser("doctor", help="Run AI environment diagnostics")
    ai_doctor_p.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    ai_doctor_p.add_argument("--quiet", action="store_true", help="Show WARN / FAIL only")
    ai_doctor_p.set_defaults(func=cmd_ai_doctor)

    ai_list_p = ai_sub.add_parser("list", help="List configured AI providers")
    ai_list_p.set_defaults(func=cmd_ai_list)

    ai_review_p = ai_sub.add_parser("review", help="Ask an AI provider to review a path")
    ai_review_p.add_argument("path", nargs="?", default=".")
    ai_review_p.add_argument("--provider", help="Override provider for this task")
    ai_review_p.set_defaults(func=cmd_ai_review)

    ai_explain_p = ai_sub.add_parser("explain", help="Ask an AI provider to explain a path")
    ai_explain_p.add_argument("path")
    ai_explain_p.add_argument("--provider", help="Override provider for this task")
    ai_explain_p.set_defaults(func=cmd_ai_explain)

    ai_plan_p = ai_sub.add_parser("plan", help="Ask an AI provider to propose a plan")
    ai_plan_p.add_argument("task")
    ai_plan_p.add_argument("--provider", help="Override provider for this task")
    ai_plan_p.set_defaults(func=cmd_ai_plan)

    ai_run_p = ai_sub.add_parser("run", help="Run a raw prompt against a specific provider")
    ai_run_p.add_argument("--provider", required=True, help="Provider name")
    ai_run_p.add_argument("prompt", help="Prompt to send")
    ai_run_p.set_defaults(func=cmd_ai_run)

    start_p = sub.add_parser("start", help="Start Master Control dashboard")
    start_p.add_argument(
        "--auto-login",
        action="store_true",
        help="Automatically run AWS SSO login when login is required",
    )
    start_p.add_argument(
        "--no-anim",
        action="store_true",
        help="Disable startup animation",
    )
    start_p.set_defaults(func=cmd_start)

    repo_p = sub.add_parser("repo", help="Git helper commands")
    repo_sub = repo_p.add_subparsers(dest="repo_command", required=True)

    repo_check_p = repo_sub.add_parser("check", help="Show repository status")
    repo_check_p.set_defaults(func=cmd_repo_check)

    repo_dirty_p = repo_sub.add_parser("dirty", help="List dirty repositories in workspace")
    repo_dirty_p.set_defaults(func=cmd_repo_dirty)

    repo_scan_p = repo_sub.add_parser("scan", help="Scan repositories in workspace")
    repo_scan_p.set_defaults(func=cmd_repo_scan)

    repo_ship_p = repo_sub.add_parser("ship", help="pull --rebase, add, commit, push")
    repo_ship_p.add_argument("-m", "--message", required=True, help="Commit message")
    repo_ship_p.add_argument("--dry-run", action="store_true", help="Show what would run without changing the repository")
    repo_ship_p.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    repo_ship_p.set_defaults(func=cmd_repo_ship)

    aws_p = sub.add_parser("aws", help="AWS helper commands")
    aws_sub = aws_p.add_subparsers(dest="aws_command", required=True)

    aws_whoami_p = aws_sub.add_parser("whoami", help="Show sts get-caller-identity")
    aws_whoami_p.set_defaults(func=cmd_aws_whoami)

    aws_profile_p = aws_sub.add_parser("profile", help="Show configured AWS profile")
    aws_profile_p.set_defaults(func=cmd_aws_profile)

    aws_summary_p = aws_sub.add_parser("summary", help="Show profile and validation status")
    aws_summary_p.set_defaults(func=cmd_aws_summary)

    aws_login_p = aws_sub.add_parser("login", help="Run aws sso login for configured profile")
    aws_login_p.set_defaults(func=cmd_aws_login)

    codex_p = sub.add_parser("codex", help="Pass through to codex CLI")
    codex_p.add_argument("codex_args", nargs=argparse.REMAINDER)
    codex_p.set_defaults(func=cmd_codex)

    path_p = sub.add_parser("path", help="WSL/Windows path conversion helpers")
    path_sub = path_p.add_subparsers(dest="path_command", required=True)

    path_win_p = path_sub.add_parser("win", help="Convert target path to Windows format")
    path_win_p.add_argument("target")
    path_win_p.add_argument("--copy", action="store_true", help="Copy result to clipboard")
    path_win_p.set_defaults(func=cmd_path_win)

    path_wsl_p = path_sub.add_parser("wsl", help="Convert target path to WSL format")
    path_wsl_p.add_argument("target")
    path_wsl_p.add_argument("--copy", action="store_true", help="Copy result to clipboard")
    path_wsl_p.set_defaults(func=cmd_path_wsl)

    open_p = sub.add_parser("open", help="Open path in Windows Explorer")
    open_p.add_argument("target", nargs="?", default=".")
    open_p.set_defaults(func=cmd_open)

    jump_p = sub.add_parser("jump", help="Print named jump target path")
    jump_p.add_argument("name")
    jump_p.set_defaults(func=cmd_jump)

    return parser


def run_cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:] if argv else None)
    return int(args.func(args))


def main() -> None:
    raise SystemExit(run_cli(sys.argv))


if __name__ == "__main__":
    main()
