from __future__ import annotations

import argparse
import asyncio
import os
import socket

from svara_api.config import get_settings
from svara_api.database import Database
from svara_api.services.clerk_invitations import build_invitation_provider
from svara_api.services.invitation_outbox import process_ready_invitation_jobs


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process durable Clerk invitation and revocation jobs."
    )
    parser.add_argument("--watch", action="store_true", help="Keep polling until interrupted.")
    parser.add_argument("--batch-size", type=int, default=20, choices=range(1, 101))
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    return parser.parse_args()


async def _run(*, watch: bool, batch_size: int, poll_seconds: float) -> None:
    if poll_seconds < 0.5 or poll_seconds > 300:
        raise ValueError("--poll-seconds must be between 0.5 and 300")
    settings = get_settings()
    database = Database(settings)
    provider = build_invitation_provider(settings)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    try:
        while True:
            results = await process_ready_invitation_jobs(
                database.session_factory,
                provider=provider,
                settings=settings,
                worker_id=worker_id,
                limit=batch_size,
            )
            succeeded = sum(result.state == "succeeded" for result in results)
            retried = sum(result.state == "retry_scheduled" for result in results)
            dead = sum(result.state == "dead_letter" for result in results)
            if results:
                print(
                    f"processed={len(results)} succeeded={succeeded} "
                    f"retry_scheduled={retried} dead_letter={dead}",
                    flush=True,
                )
            if not watch:
                return
            await asyncio.sleep(poll_seconds)
    finally:
        await database.dispose()


def main() -> None:
    arguments = _arguments()
    asyncio.run(
        _run(
            watch=arguments.watch,
            batch_size=arguments.batch_size,
            poll_seconds=arguments.poll_seconds,
        )
    )


if __name__ == "__main__":
    main()
