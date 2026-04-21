from __future__ import annotations

import asyncio

from app.api.dreams import _get_redis_client
from app.services.auto_sync import run_auto_sync_loop
from app.shared.database import get_session_factory


def main() -> None:
    asyncio.run(
        run_auto_sync_loop(
            redis_client=_get_redis_client(),
            session_factory=get_session_factory(),
        )
    )


if __name__ == "__main__":
    main()
