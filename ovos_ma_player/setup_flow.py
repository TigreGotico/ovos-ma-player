"""Interactive setup for the OVOS player provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType

if TYPE_CHECKING:
    from music_assistant.models.setup_flow import SetupSession


async def run_setup(session: SetupSession) -> None:
    values = await session.form(
        [
            ConfigEntry(
                key="host",
                type=ConfigEntryType.STRING,
                label="OVOS messagebus host",
                required=True,
                default_value="localhost",
                description="Hostname or IP of the OVOS messagebus. Must be reachable from MA.",
            ),
            ConfigEntry(
                key="port",
                type=ConfigEntryType.INTEGER,
                label="OVOS messagebus port",
                required=True,
                default_value=8181,
            ),
        ],
        last_step=True,
    )
    await session.finish(values)
