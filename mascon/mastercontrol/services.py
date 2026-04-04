from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import os
import platform
import re
import shutil
import subprocess
import sys


@dataclass(slots=True)
class CommandResult:
    ok: bool
    code: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class RepoState:
    repo_name: str
    branch: str
    dirty: bool
    changed_files: int
    ahead: int
    behind: int
    root: Path


@dataclass(slots=True)
class AwsStatus:
    ok: bool
    profile: str
    reason: str
    detail: str


@dataclass(slots=True)
class DoctorItem:
    key: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


WINDOWS_DRIVE_RE = re.compile(r"^(?P<drive>[A-Za-z]):\\(?P<rest>.*)$")


def run_cmd(
    args: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> CommandResult:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
    )
    result = CommandResult(
        ok=completed.returncode == 0,
        code=completed.returncode,
        stdout=(completed.stdout or "").strip(),
        stderr=(completed.stderr or "").strip(),
    )
    if check and not result.ok:
        raise RuntimeError(result.stderr or result.stdout or f"Command failed: {' '.join(args)}")
    return result


def is_wsl() -> bool:
    release = platform.uname().release.lower()
    return "microsoft" in release or "wsl" in release


def which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def get_platform_label() -> str:
    if is_wsl():
        return f"WSL ({platform.system()})"
    return platform.system()


def get_git_root(path: Path) -> Path | None:
    result = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=path)
    if not result.ok or not result.stdout:
        return None
    return Path(result.stdout).resolve()


def repo_state(path: Path) -> RepoState:
    root = get_git_root(path)
    if root is None:
        raise RuntimeError("Not inside a Git repository.")

    branch_res = run_cmd(["git", "branch", "--show-current"], cwd=root, check=True)
    status_res = run_cmd(["git", "status", "--porcelain"], cwd=root, check=True)
    ahead_behind_res = run_cmd(
        ["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"],
        cwd=root,
    )

    ahead = 0
    behind = 0
    if ahead_behind_res.ok and ahead_behind_res.stdout:
        parts = ahead_behind_res.stdout.split()
        if len(parts) == 2:
            behind = int(parts[0])
            ahead = int(parts[1])

    changed_files = len([line for line in status_res.stdout.splitlines() if line.strip()])
    return RepoState(
        repo_name=root.name,
        branch=branch_res.stdout or "(detached)",
        dirty=changed_files > 0,
        changed_files=changed_files,
        ahead=ahead,
        behind=behind,
        root=root,
    )


def scan_repos(workspace: Path) -> list[RepoState]:
    repos: list[RepoState] = []
    if not workspace.exists():
        return repos
    for child in sorted(workspace.iterdir()):
        if not child.is_dir():
            continue
        if not (child / ".git").exists():
            continue
        try:
            repos.append(repo_state(child))
        except Exception:
            continue
    return repos


def ensure_safe_for_ship(root: Path) -> None:
    git_dir_res = run_cmd(["git", "rev-parse", "--git-dir"], cwd=root, check=True)
    git_dir = (root / git_dir_res.stdout).resolve() if not Path(git_dir_res.stdout).is_absolute() else Path(git_dir_res.stdout)
    blockers = [
        git_dir / "rebase-merge",
        git_dir / "rebase-apply",
        git_dir / "MERGE_HEAD",
        git_dir / "CHERRY_PICK_HEAD",
        git_dir / "REVERT_HEAD",
    ]
    names = [p.name for p in blockers if p.exists()]
    if names:
        raise RuntimeError(f"Repository has unfinished Git operation: {', '.join(names)}")

    branch = run_cmd(["git", "branch", "--show-current"], cwd=root, check=True).stdout
    if not branch:
        raise RuntimeError("Detached HEAD is not supported for ship.")


def repo_ship(path: Path, message: str, dry_run: bool = False) -> list[str]:
    root = get_git_root(path)
    if root is None:
        raise RuntimeError("Not inside a Git repository.")
    ensure_safe_for_ship(root)

    logs: list[str] = []
    if dry_run:
        logs.append(f"dry-run: repository={root}")
        logs.append("dry-run: would run `git pull --rebase`")
        logs.append("dry-run: would run `git add -A`")
        diff_res = run_cmd(["git", "status", "--short"], cwd=root)
        if diff_res.ok and diff_res.stdout:
            logs.append("dry-run: would create a commit with the provided message")
        else:
            logs.append("dry-run: commit would be skipped if there are no staged changes")
        logs.append("dry-run: would run `git push`")
        return logs

    pull_res = run_cmd(["git", "pull", "--rebase"], cwd=root)
    if not pull_res.ok:
        raise RuntimeError(pull_res.stderr or pull_res.stdout or "git pull --rebase failed")
    logs.append("pull --rebase: ok")

    add_res = run_cmd(["git", "add", "-A"], cwd=root)
    if not add_res.ok:
        raise RuntimeError(add_res.stderr or "git add failed")
    logs.append("add -A: ok")

    diff_res = run_cmd(["git", "diff", "--cached", "--quiet"], cwd=root)
    if diff_res.code == 0:
        logs.append("commit: skipped (no staged changes)")
    else:
        commit_res = run_cmd(["git", "commit", "-m", message], cwd=root)
        if not commit_res.ok:
            raise RuntimeError(commit_res.stderr or commit_res.stdout or "git commit failed")
        first_line = commit_res.stdout.splitlines()[0] if commit_res.stdout else "commit: ok"
        logs.append(first_line)

    push_res = run_cmd(["git", "push"], cwd=root)
    if not push_res.ok:
        raise RuntimeError(push_res.stderr or push_res.stdout or "git push failed")
    logs.append("push: ok")
    return logs


def aws_env(profile: str | None = None) -> dict[str, str]:
    env = dict(os.environ)
    if profile:
        env["AWS_PROFILE"] = profile
    return env


def aws_identity(profile: str | None = None) -> CommandResult:
    return run_cmd(["aws", "sts", "get-caller-identity", "--output", "json"], env=aws_env(profile))


def aws_list_profiles() -> list[str]:
    if not which("aws"):
        return []
    result = run_cmd(["aws", "configure", "list-profiles"])
    if not result.ok or not result.stdout:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def aws_check_status(profile: str) -> AwsStatus:
    if not which("aws"):
        return AwsStatus(
            ok=False,
            profile=profile,
            reason="aws_cli_not_found",
            detail="aws command not found",
        )

    result = aws_identity(profile)
    if result.ok:
        return AwsStatus(
            ok=True,
            profile=profile,
            reason="ok",
            detail=result.stdout,
        )

    text = f"{result.stderr}\n{result.stdout}".strip()
    lowered = text.lower()

    if "the config profile" in lowered and "could not be found" in lowered:
        return AwsStatus(
            ok=False,
            profile=profile,
            reason="profile_not_found",
            detail=text,
        )

    if "token has expired and refresh failed" in lowered:
        return AwsStatus(
            ok=False,
            profile=profile,
            reason="sso_token_expired",
            detail=text,
        )

    if "error loading sso token" in lowered:
        return AwsStatus(
            ok=False,
            profile=profile,
            reason="sso_not_logged_in",
            detail=text,
        )

    if "sso" in lowered and "login" in lowered:
        return AwsStatus(
            ok=False,
            profile=profile,
            reason="sso_login_required",
            detail=text,
        )

    return AwsStatus(
        ok=False,
        profile=profile,
        reason="unknown_error",
        detail=text or "AWS verification failed",
    )


def aws_requires_login(status: AwsStatus) -> bool:
    return status.reason in {
        "sso_token_expired",
        "sso_not_logged_in",
        "sso_login_required",
    }


def aws_sso_login(profile: str) -> int:
    completed = subprocess.run(["aws", "sso", "login", "--profile", profile])
    return int(completed.returncode)


def to_windows_path(value: str | Path) -> str:
    path_str = str(value)
    if path_str.startswith("~"):
        path_str = str(Path(path_str).expanduser())
    if path_str.startswith("/mnt/"):
        parts = Path(path_str).parts
        if len(parts) >= 4:
            drive = parts[2].upper()
            rest = "\\".join(parts[3:])
            return f"{drive}:\\{rest}" if rest else f"{drive}:\\"
    if path_str.startswith("/") and is_wsl():
        distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu")
        replaced = path_str.replace("/", "\\")
        return "\\\\wsl$\\" + distro + replaced
    match = WINDOWS_DRIVE_RE.match(path_str)
    if match:
        return f"{match.group('drive').upper()}:\\{match.group('rest')}"
    return path_str


def to_wsl_path(value: str | Path) -> str:
    path_str = str(value)
    if path_str.startswith("/mnt/") or path_str.startswith("/"):
        return str(Path(path_str).expanduser())
    match = WINDOWS_DRIVE_RE.match(path_str)
    if match:
        drive = match.group("drive").lower()
        rest = match.group("rest").replace("\\", "/")
        return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"
    if path_str.startswith("\\\\wsl$\\"):
        parts = path_str.split("\\")
        if len(parts) >= 5:
            return "/" + "/".join(parts[4:])
    return path_str


def copy_to_clipboard(text: str) -> None:
    if is_wsl() and which("clip.exe"):
        subprocess.run(["clip.exe"], input=text, text=True, check=True)
        return
    if platform.system() == "Windows" and which("clip"):
        subprocess.run(["clip"], input=text, text=True, check=True)
        return
    raise RuntimeError("Clipboard integration is unavailable on this environment.")


def open_in_explorer(target: Path) -> None:
    resolved = target.resolve()
    if is_wsl() and which("explorer.exe"):
        subprocess.run(["explorer.exe", to_windows_path(resolved)], check=True)
        return
    if platform.system() == "Windows" and which("explorer"):
        subprocess.run(["explorer", str(resolved)], check=True)
        return
    raise RuntimeError("Explorer integration is unavailable on this environment.")


def codex_available() -> bool:
    return which("codex")


def json_dumps_pretty(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def python_version_ok() -> tuple[bool, str]:
    version = sys.version.split()[0]
    is_supported = sys.version_info >= (3, 11)
    return is_supported, version
