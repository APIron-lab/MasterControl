from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import os
import tomllib


CONFIG_DIR = Path.home() / ".config" / "mascon"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass(slots=True)
class MasconConfig:
    profile: str = "default"
    mode: str = "work"
    workspace: str = str(Path.home() / "workspace")
    default_aws_profile: str = "default"
    jumps: dict[str, str] = field(default_factory=dict)
    ai: "AiConfig" = field(default_factory=lambda: AiConfig())

    @property
    def workspace_path(self) -> Path:
        return expand_path(self.workspace)


@dataclass(slots=True)
class AiProviderConfig:
    type: str = "cli"
    command: str = ""
    enabled: bool = True
    model: str = ""


@dataclass(slots=True)
class AiConfig:
    default_provider: str = "codex"
    fallback_provider: str = "local"
    default_task_provider: dict[str, str] = field(
        default_factory=lambda: {
            "review": "claude",
            "explain": "codex",
            "plan": "claude",
        }
    )
    providers: dict[str, AiProviderConfig] = field(
        default_factory=lambda: {
            "codex": AiProviderConfig(type="cli", command="codex", enabled=True),
            "claude": AiProviderConfig(type="cli", command="claude", enabled=True),
            "local": AiProviderConfig(type="ollama", command="ollama", model="qwen3-coder", enabled=True),
        }
    )


DEFAULT_CONFIG_TOML = """profile = \"default\"
mode = \"work\"
workspace = \"~/workspace\"
default_aws_profile = \"default\"

[jumps]
workspace = \"~/workspace\"

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
"""


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def config_exists() -> bool:
    return CONFIG_FILE.exists()


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def ensure_config_file() -> None:
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")


def load_config() -> MasconConfig:
    ensure_config_file()
    data = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    ai_data = dict(data.get("ai", {}))
    default_task_provider = {
        "review": "claude",
        "explain": "codex",
        "plan": "claude",
    }
    default_task_provider.update(
        {str(k): str(v) for k, v in dict(ai_data.get("default_task_provider", {})).items()}
    )
    default_providers = {
        "codex": AiProviderConfig(type="cli", command="codex", enabled=True),
        "claude": AiProviderConfig(type="cli", command="claude", enabled=True),
        "local": AiProviderConfig(type="ollama", command="ollama", model="qwen3-coder", enabled=True),
    }
    raw_providers = dict(ai_data.get("providers", {}))
    providers: dict[str, AiProviderConfig] = {}
    for name, defaults in default_providers.items():
        raw_provider = dict(raw_providers.get(name, {}))
        providers[name] = AiProviderConfig(
            type=str(raw_provider.get("type", defaults.type)),
            command=str(raw_provider.get("command", defaults.command)),
            enabled=bool(raw_provider.get("enabled", defaults.enabled)),
            model=str(raw_provider.get("model", defaults.model)),
        )
    for name, raw_value in raw_providers.items():
        if name in providers:
            continue
        raw_provider = dict(raw_value)
        providers[str(name)] = AiProviderConfig(
            type=str(raw_provider.get("type", "cli")),
            command=str(raw_provider.get("command", str(name))),
            enabled=bool(raw_provider.get("enabled", True)),
            model=str(raw_provider.get("model", "")),
        )
    return MasconConfig(
        profile=str(data.get("profile", "default")),
        mode=str(data.get("mode", "work")),
        workspace=str(data.get("workspace", "~/workspace")),
        default_aws_profile=str(data.get("default_aws_profile", "default")),
        jumps={str(k): str(v) for k, v in dict(data.get("jumps", {})).items()},
        ai=AiConfig(
            default_provider=str(ai_data.get("default_provider", "codex")),
            fallback_provider=str(ai_data.get("fallback_provider", "local")),
            default_task_provider=default_task_provider,
            providers=providers,
        ),
    )


def toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"")


def build_config_toml(config: MasconConfig) -> str:
    lines = [
        f'profile = "{toml_escape(config.profile)}"',
        f'mode = "{toml_escape(config.mode)}"',
        f'workspace = "{toml_escape(config.workspace)}"',
        f'default_aws_profile = "{toml_escape(config.default_aws_profile)}"',
        "",
        "[jumps]",
    ]
    for key, value in config.jumps.items():
        lines.append(f'{key} = "{toml_escape(value)}"')
    lines.append("")
    lines.append("[ai]")
    lines.append(f'default_provider = "{toml_escape(config.ai.default_provider)}"')
    lines.append(f'fallback_provider = "{toml_escape(config.ai.fallback_provider)}"')
    lines.append("")
    lines.append("[ai.default_task_provider]")
    for key, value in config.ai.default_task_provider.items():
        lines.append(f'{key} = "{toml_escape(value)}"')
    lines.append("")
    for name, provider in config.ai.providers.items():
        lines.append(f"[ai.providers.{name}]")
        lines.append(f'type = "{toml_escape(provider.type)}"')
        lines.append(f'command = "{toml_escape(provider.command)}"')
        lines.append(f'enabled = {"true" if provider.enabled else "false"}')
        if provider.model:
            lines.append(f'model = "{toml_escape(provider.model)}"')
        lines.append("")
    return "\n".join(lines)


def save_config(config: MasconConfig) -> None:
    ensure_config_dir()
    CONFIG_FILE.write_text(build_config_toml(config), encoding="utf-8")


def backup_existing_config() -> Path | None:
    if not CONFIG_FILE.exists():
        return None
    ensure_config_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = CONFIG_DIR / f"config.toml.bak.{timestamp}"
    backup_path.write_text(CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path
