from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .config import AiConfig, AiProviderConfig, MasconConfig, expand_path
from .services import DoctorItem, which, run_cmd


@dataclass(slots=True)
class AiRequest:
    task: str
    prompt: str
    target_path: Path | None = None
    extra_context: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AiResponse:
    provider: str
    ok: bool
    stdout: str
    stderr: str
    exit_code: int


class AiProvider(Protocol):
    name: str
    config: AiProviderConfig

    def available(self) -> bool: ...

    def run(self, request: AiRequest) -> AiResponse: ...


@dataclass(slots=True)
class ProviderStatus:
    name: str
    type: str
    enabled: bool
    available: bool
    command: str
    model: str
    detail: str


class BaseCliProvider:
    def __init__(self, name: str, config: AiProviderConfig) -> None:
        self.name = name
        self.config = config

    def available(self) -> bool:
        return self.config.enabled and bool(self.config.command) and which(self.config.command)

    def build_command(self, request: AiRequest) -> list[str]:
        raise NotImplementedError

    def run(self, request: AiRequest) -> AiResponse:
        cmd = self.build_command(request)
        result = run_cmd(cmd)
        return AiResponse(
            provider=self.name,
            ok=result.ok,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.code,
        )


class CodexCliProvider(BaseCliProvider):
    def build_command(self, request: AiRequest) -> list[str]:
        return [self.config.command, request.prompt]


class ClaudeCliProvider(BaseCliProvider):
    def build_command(self, request: AiRequest) -> list[str]:
        return [self.config.command, "-p", request.prompt]


class OllamaProvider(BaseCliProvider):
    def build_command(self, request: AiRequest) -> list[str]:
        model = self.config.model or "qwen3-coder"
        return [self.config.command, "run", model, request.prompt]


def ai_doctor_item(key: str, status: str, detail: str) -> DoctorItem:
    return DoctorItem(key=key, status=status, detail=detail)


def get_ai_provider_config(ai_config: AiConfig, name: str) -> AiProviderConfig | None:
    return ai_config.providers.get(name)


def build_provider(name: str, config: AiProviderConfig) -> AiProvider:
    if name == "claude":
        return ClaudeCliProvider(name, config)
    if config.type == "ollama" or name == "local":
        return OllamaProvider(name, config)
    return CodexCliProvider(name, config)


def provider_statuses(ai_config: AiConfig) -> list[ProviderStatus]:
    statuses: list[ProviderStatus] = []
    for name, provider_config in ai_config.providers.items():
        provider = build_provider(name, provider_config)
        available = provider.available()
        detail = "available" if available else "not found"
        if not provider_config.enabled:
            detail = "disabled"
        if provider_config.type == "ollama" and not provider_config.model:
            detail = "model not configured"
        statuses.append(
            ProviderStatus(
                name=name,
                type=provider_config.type,
                enabled=provider_config.enabled,
                available=available,
                command=provider_config.command,
                model=provider_config.model,
                detail=detail,
            )
        )
    return statuses


def resolve_provider_name(config: MasconConfig, task: str, explicit_provider: str | None = None) -> str:
    if explicit_provider:
        return explicit_provider
    task_provider = config.ai.default_task_provider.get(task)
    if task_provider:
        return task_provider
    return config.ai.default_provider or config.ai.fallback_provider


def resolve_provider(config: MasconConfig, task: str, explicit_provider: str | None = None) -> AiProvider:
    provider_name = resolve_provider_name(config, task, explicit_provider=explicit_provider)
    provider_config = get_ai_provider_config(config.ai, provider_name)
    if provider_config is None:
        fallback = get_ai_provider_config(config.ai, config.ai.fallback_provider)
        if fallback is None:
            raise RuntimeError(f"Unknown AI provider: {provider_name}")
        return build_provider(config.ai.fallback_provider, fallback)
    return build_provider(provider_name, provider_config)


def build_task_prompt(task: str, target: str) -> str:
    if task == "review":
        return (
            f"Review the code or project at `{target}`. "
            "Focus on bugs, risks, regressions, and missing tests. Keep the response concise and actionable."
        )
    if task == "explain":
        return (
            f"Explain the file or directory at `{target}`. "
            "Summarize its purpose, main components, and how it is likely used."
        )
    if task == "plan":
        return (
            f"Create an implementation plan for this task: {target}. "
            "Focus on pragmatic steps, risks, and validation."
        )
    return target


def build_ai_request(task: str, target: str) -> AiRequest:
    path_target = None
    if task in {"review", "explain"}:
        path_target = expand_path(target) if target not in {".", ".."} else Path(target).resolve()
    return AiRequest(
        task=task,
        prompt=build_task_prompt(task, target),
        target_path=path_target,
    )


def run_ai_task(config: MasconConfig, task: str, target: str, explicit_provider: str | None = None) -> AiResponse:
    provider = resolve_provider(config, task, explicit_provider=explicit_provider)
    request = build_ai_request(task, target)
    if not provider.config.enabled:
        raise RuntimeError(f"AI provider `{provider.name}` is disabled in config.")
    if not provider.available():
        raise RuntimeError(f"AI provider `{provider.name}` is not available.")
    return provider.run(request)


def run_ai_prompt(config: MasconConfig, provider_name: str, prompt: str) -> AiResponse:
    provider = resolve_provider(config, "run", explicit_provider=provider_name)
    if not provider.config.enabled:
        raise RuntimeError(f"AI provider `{provider.name}` is disabled in config.")
    if not provider.available():
        raise RuntimeError(f"AI provider `{provider.name}` is not available.")
    return provider.run(AiRequest(task="run", prompt=prompt))


def collect_ai_doctor(config: MasconConfig) -> tuple[list[DoctorItem], list[str]]:
    items: list[DoctorItem] = [ai_doctor_item("ai config", "ok", "loaded")]
    suggestions: list[str] = []
    statuses = provider_statuses(config.ai)

    for status in statuses:
        enabled_label = "enabled" if status.enabled else "disabled"
        if not status.enabled:
            items.append(ai_doctor_item(f"{status.name}", "warn", f"{enabled_label}, {status.type}"))
            continue
        if status.available:
            items.append(ai_doctor_item(f"{status.name}", "ok", f"{status.type}, available"))
        else:
            severity = "warn"
            detail = f"{status.type}, {status.detail}"
            if status.type == "ollama" and not status.model:
                severity = "fail"
                suggestions.append("Set `ai.providers.local.model` in config.")
            else:
                suggestions.append(f"Install or expose `{status.command}` in PATH.")
            items.append(ai_doctor_item(f"{status.name}", severity, detail))

        if status.type == "ollama":
            if status.model:
                items.append(ai_doctor_item("local model", "ok", status.model))
            else:
                items.append(ai_doctor_item("local model", "fail", "model not configured"))

    if not statuses:
        items.append(ai_doctor_item("providers", "fail", "no AI providers configured"))
        suggestions.append("Add an `[ai.providers.*]` section to config.")

    return items, sorted(set(suggestions))
