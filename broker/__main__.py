"""Entry point: run the agent and admin APIs together on one asyncio loop."""

from __future__ import annotations

import asyncio

import uvicorn

from .app import create_agent_app, create_admin_app
from .config import Settings
from .state import build_state


async def _serve() -> None:
    settings = Settings.from_env()
    state = build_state(settings)

    agent_app = create_agent_app(state)
    admin_app = create_admin_app(state)

    agent_cfg = uvicorn.Config(
        agent_app, host=settings.agent_host, port=settings.agent_port,
        log_level="info", access_log=False,
    )
    admin_cfg = uvicorn.Config(
        admin_app, host=settings.admin_host, port=settings.admin_port,
        log_level="info", access_log=False,
    )
    agent_server = uvicorn.Server(agent_cfg)
    admin_server = uvicorn.Server(admin_cfg)

    try:
        await asyncio.gather(agent_server.serve(), admin_server.serve())
    finally:
        await state.http.aclose()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
