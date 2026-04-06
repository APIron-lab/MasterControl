# Master Control

[日本語版 README](README.ja.md)

`Master Control` is a WSL-first command center for personal development workflows.

It gives you one CLI, `mascon`, for:

- workspace and repository visibility
- AWS profile and auth checks
- path conversion and Windows interop from WSL
- task-first AI commands across Codex, Claude Code, and local LLMs
- a lightweight daily-start dashboard

This is not a general-purpose shell replacement. It is a focused cockpit for people who live in WSL and want fast, repeatable commands for the things they do every day.

## Who It Is For

`mascon` is built for developers who:

- work primarily inside WSL
- manage multiple repositories under one workspace
- use AWS profiles or AWS SSO regularly
- want quick access to Codex, Claude Code, or local models without switching tools
- prefer a pragmatic CLI over a large IDE-centric workflow layer

## 30-Second Setup

If `mascon` is installed as a package:

```bash
pipx install mascon
mascon init
mascon doctor
mascon ai doctor
mascon start
```

If you are working from source:

```bash
cd /path/to/mascon
python3 -m pip install -e .
mascon init
mascon doctor
mascon ai doctor
mascon start
```

## What You Get

### Environment Checks

`mascon doctor` validates the basics of your daily environment:

- Python and platform
- config loading
- workspace existence
- Git presence and repo count
- AWS CLI, configured profile, and auth state
- Codex and WSL integration tools
- jump path validity

Example:

```text
Mascon doctor
────────────────────────────────────────────────────────────────────────
[ OK ] python                   3.12.3
[ OK ] platform                 WSL (Linux)
[ OK ] config                   loaded from /home/user/.config/mascon/config.toml
[ OK ] workspace                /home/user/workspace
[ OK ] git                      git found
[ OK ] repos                    12 repositories under /home/user/workspace
[ OK ] aws cli                  aws found
[ OK ] aws profile              dev
[ WARN ] aws auth               sso login required
[ OK ] codex                    codex found
[ OK ] explorer.exe             explorer.exe found
[ OK ] clip.exe                 clip.exe found
[ OK ] jumps                    4 jumps valid
────────────────────────────────────────────────────────────────────────
Summary: OK=12 WARN=1 FAIL=0
Suggested actions:
  - Run `mascon aws login` to refresh AWS SSO.
```

Machine-readable output:

```bash
mascon doctor --json
```

### AI Commands

`mascon ai` is task-first.

You start with what you want to do:

```bash
mascon ai review .
mascon ai explain mastercontrol/cli.py
mascon ai plan "add ai compare command"
```

If needed, you can override the provider:

```bash
mascon ai review . --provider codex
mascon ai run --provider claude "Review this repository structure"
```

Current AI MVP commands:

- `mascon ai doctor`
- `mascon ai list`
- `mascon ai review [path]`
- `mascon ai explain <path>`
- `mascon ai plan "<task>"`
- `mascon ai run --provider <name> "<prompt>"`

Example:

```text
Mascon AI doctor
────────────────────────────────────────────────────────────────────────
[ OK ] ai config                loaded
[ OK ] codex                    cli, available
[ WARN ] claude                 cli, not found
[ WARN ] local                  ollama, not found
[ OK ] local model              qwen3-coder
────────────────────────────────────────────────────────────────────────
Summary: OK=3 WARN=2 FAIL=0
Suggested actions:
  - Install or expose `claude` in PATH.
  - Install or expose `ollama` in PATH.
```

Machine-readable output:

```bash
mascon ai doctor --json
```

### Repository Operations

Representative commands:

```bash
mascon repo check
mascon repo dirty
mascon repo scan
mascon repo ship -m "feat: add dashboard" --dry-run
mascon repo ship -m "feat: add dashboard"
mascon repo ship -m "feat: add dashboard" --yes
```

`repo ship` performs:

```text
git pull --rebase
git add -A
git commit -m "..."
git push
```

Safety features:

- `--dry-run` shows what would happen without changing anything
- default execution shows branch and changed file count, then asks for confirmation
- `--yes` skips the confirmation prompt

### WSL Convenience

Daily-use helper commands:

```bash
mascon path win . --copy
mascon path wsl "C:\\Users\\..."
mascon open .
mascon jump workspace
mascon aws whoami
mascon aws login
```

## AI Provider Config

`mascon ai` uses task-first defaults from `~/.config/mascon/config.toml`.

Minimal example:

```toml
[ai]
default_provider = "codex"
fallback_provider = "local"

[ai.default_task_provider]
review = "claude"
explain = "codex"
plan = "claude"

[ai.providers.codex]
type = "cli"
command = "codex"
enabled = true

[ai.providers.claude]
type = "cli"
command = "claude"
enabled = true

[ai.providers.local]
type = "ollama"
command = "ollama"
model = "qwen3-coder"
enabled = true
```

Behavior:

- `review`, `explain`, and `plan` prefer `ai.default_task_provider`
- if a task-specific mapping is missing, `default_provider` is used
- if a configured provider is missing, `fallback_provider` can be used
- `mascon ai run --provider ...` bypasses task routing

## Config

Interactive setup is the default:

```bash
mascon init
```

Manual config is also supported:

```bash
mkdir -p ~/.config/mascon
cat > ~/.config/mascon/config.toml <<'TOML'
profile = "default"
mode = "work"
workspace = "~/workspace"
default_aws_profile = "dev"

[jumps]
workspace = "~/workspace"
mastercontrol = "~/workspace/mastercontrol"

[ai]
default_provider = "codex"
fallback_provider = "local"

[ai.default_task_provider]
review = "claude"
explain = "codex"
plan = "claude"

[ai.providers.codex]
type = "cli"
command = "codex"
enabled = true

[ai.providers.claude]
type = "cli"
command = "claude"
enabled = true

[ai.providers.local]
type = "ollama"
command = "ollama"
model = "qwen3-coder"
enabled = true
TOML
```

## Command Snapshot

```bash
mascon start
mascon init
mascon doctor
mascon ai doctor
mascon ai list
mascon ai review .
mascon ai explain mastercontrol/cli.py
mascon ai plan "add ai compare command"
mascon repo check
mascon repo dirty
mascon aws whoami
mascon path win . --copy
mascon open .
mascon jump workspace
```

## WSL Notes

`Master Control` is designed primarily for WSL.

Some commands assume Windows interop is available:

- `mascon open` expects `explorer.exe`
- clipboard integration expects `clip.exe`
- path conversion assumes WSL-style path translation

It can run outside WSL, but the intended experience is WSL-first.

## What It Is Not

- not a full Git abstraction layer
- not a general-purpose agent orchestration platform
- not a replacement for your shell, editor, or CI system
- not trying to normalize every provider-specific AI feature behind one heavy interface

The current AI layer is intentionally lightweight: task-first commands, provider override, and environment diagnostics first.

## Development

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Run syntax checks:

```bash
python3 -m py_compile mastercontrol/config.py mastercontrol/services.py mastercontrol/ai.py mastercontrol/cli.py
```

## Requirements

- Python 3.11+
- WSL recommended
- Git for repo features
- AWS CLI for AWS features
- `codex`, `claude`, or `ollama` in `PATH` if you want AI provider support
