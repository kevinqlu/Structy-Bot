import asyncio
import logging
from datetime import datetime
from typing import Any

import discord

from structy_bot import storage
from structy_bot.config import Config, load_or_exit
from structy_bot.handler import describe_sync, handle_message
from structy_bot.progress import split_message
from structy_bot.sessions import CORRUPT_NOTE
from structy_bot.sync import SyncRunner

NO_MENTIONS = discord.AllowedMentions.none()
SYNC_ERROR = "Sync error. Session saved."
log = logging.getLogger(__name__)


class StructyClient(discord.Client):
    def __init__(
        self, config: Config, intents: discord.Intents, sync_runner: SyncRunner | None = None
    ) -> None:
        super().__init__(intents=intents)
        self.config = config
        self.sync_runner = sync_runner or SyncRunner(
            config.sync_script_path, config.sync_log_path, config.sync_timeout_seconds
        )
        # One command at a time, in arrival order (SPEC 5 rule 7). The sync runs
        # OUTSIDE this lock so a slow sync never blocks later commands.
        self._lock = asyncio.Lock()

    async def on_ready(self) -> None:
        data_dir = self.config.data_dir
        channel = self.get_channel(self.config.channel_id)
        if channel is None:
            log.warning("Cannot see the configured channel; check CHANNEL_ID and permissions")
        # reconcile_startup cannot report corruption, so check first.
        _, corrupt = storage.read_current_session(data_dir)
        if corrupt and channel is not None:
            await channel.send(CORRUPT_NOTE.strip(), allowed_mentions=NO_MENTIONS)  # type: ignore[union-attr]
        storage.reconcile_startup(data_dir)

    async def on_message(self, message: discord.Message) -> None:
        await self.process_message(message)

    async def process_message(self, message: discord.Message) -> None:
        async with self._lock:
            result = handle_message(
                message.content, message.author.id, message.author.bot,
                message.channel.id, self.config, datetime.now().astimezone(),
            )  # fmt: skip
            if result is not None:
                await self._send_reply(message.channel, result.text)
        if result is not None and result.record_to_sync is not None:
            await self._sync_and_report(message.channel)

    async def _send_reply(self, channel: Any, text: str) -> None:
        # A failed send must not stop the sync for a session that is already recorded.
        try:
            for chunk in split_message(text):
                await channel.send(chunk, allowed_mentions=NO_MENTIONS)
        except Exception as error:
            log.error("sending reply failed with %s", type(error).__name__)

    async def _sync_and_report(self, channel: Any) -> None:
        # The record is already on disk; nothing here may lose it or kill the bot.
        try:
            outcome = await self.sync_runner.run()
            text = describe_sync(outcome, self.config.sync_timeout_seconds)
        except Exception as error:
            log.error("sync failed with %s", type(error).__name__)
            text = SYNC_ERROR
        try:
            await channel.send(text, allowed_mentions=NO_MENTIONS)
        except Exception as error:
            log.error("sending sync result failed with %s", type(error).__name__)


def create_client(config: Config) -> StructyClient:
    intents = discord.Intents.default()
    intents.message_content = True
    return StructyClient(config, intents)


def main() -> None:
    config = load_or_exit()
    create_client(config).run(config.discord_token)


if __name__ == "__main__":
    main()
