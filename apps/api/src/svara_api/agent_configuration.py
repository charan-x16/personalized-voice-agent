from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Protocol

DEFAULT_AGENT_DISPLAY_NAME = "Asha"
DEFAULT_AGENT_OPENING_MESSAGE = "Hello {first_name}, how can I help you today?"
FALLBACK_AGENT_OPENING_MESSAGE = "Hello, how can I help you today?"
DEFAULT_AGENT_TONE = "professional"
DEFAULT_AGENT_INSTRUCTIONS = (
    "Help the customer clearly, use only verified account information, and protect their privacy."
)
AGENT_TONES = frozenset({"concise", "professional", "warm"})
MAX_RUNTIME_OPENING_MESSAGE_LENGTH = 500


class StoredAgentConfiguration(Protocol):
    display_name: str
    opening_message: str
    tone: str
    instructions: str
    revision: int


@dataclass(frozen=True, slots=True)
class AgentConfigurationSnapshot:
    display_name: str
    opening_message: str
    tone: str
    instructions: str
    revision: int


def is_supported_opening_message_template(value: str) -> bool:
    """Accept plain text plus at most one exact ``{first_name}`` field."""

    position = 0
    first_name_fields = 0
    while position < len(value):
        if value.startswith("{{", position) or value.startswith("}}", position):
            position += 2
        elif value.startswith("{first_name}", position):
            first_name_fields += 1
            if first_name_fields > 1:
                return False
            position += len("{first_name}")
        elif value[position] in "{}":
            return False
        else:
            position += 1
    return True


def resolve_agent_configuration(
    configuration: StoredAgentConfiguration | None,
) -> AgentConfigurationSnapshot:
    """Return bounded, runtime-safe values, including for a missing or malformed row."""

    if configuration is None:
        return AgentConfigurationSnapshot(
            display_name=DEFAULT_AGENT_DISPLAY_NAME,
            opening_message=DEFAULT_AGENT_OPENING_MESSAGE,
            tone=DEFAULT_AGENT_TONE,
            instructions=DEFAULT_AGENT_INSTRUCTIONS,
            revision=1,
        )

    display_name = configuration.display_name.strip()[:80] or DEFAULT_AGENT_DISPLAY_NAME
    opening_message = configuration.opening_message.strip()
    if (
        not opening_message
        or len(opening_message) > MAX_RUNTIME_OPENING_MESSAGE_LENGTH
        or not is_supported_opening_message_template(opening_message)
    ):
        opening_message = DEFAULT_AGENT_OPENING_MESSAGE
    tone = configuration.tone if configuration.tone in AGENT_TONES else DEFAULT_AGENT_TONE
    return AgentConfigurationSnapshot(
        display_name=display_name,
        opening_message=opening_message,
        tone=tone,
        instructions=configuration.instructions.strip()[:2_000],
        revision=max(configuration.revision, 1),
    )


def render_opening_message(template: str, *, first_name: str) -> str:
    """Render a persisted template, falling back if expansion exceeds its bound."""

    safe_template = (
        template
        if is_supported_opening_message_template(template)
        else DEFAULT_AGENT_OPENING_MESSAGE
    )
    rendered: list[str] = []
    for literal_text, field_name, _, _ in Formatter().parse(safe_template):
        rendered.append(literal_text)
        if field_name == "first_name":
            rendered.append(first_name)
    message = "".join(rendered)
    if len(message) > MAX_RUNTIME_OPENING_MESSAGE_LENGTH:
        return FALLBACK_AGENT_OPENING_MESSAGE
    return message
