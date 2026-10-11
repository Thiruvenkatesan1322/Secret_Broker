"""FastAPI app factories: a locked-down agent API and a separate admin (approval) API."""

from __future__ import annotations

import datetime
import json

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import proxy as proxy_mod
from . import tasks as tasks_mod
from .errors import ValidationError
from .security import constant_time_compare
from .state import BrokerState

_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _auth_dependency(expected_token: str, header_name: str):
    async def dependency(request: Request) -> None:
        supplied = request.headers.get(header_name)
        if not constant_time_compare(supplied, expected_token):
            raise HTTPException(status_code=401, detail="invalid or missing token")

    return dependency


def create_agent_app(state: BrokerState) -> FastAPI:
    """Agent-facing API. Has NO approval endpoints by construction."""
    app = FastAPI(
        title="secret-broker agent API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    auth = _auth_dependency(state.settings.broker_token, "x-broker-token")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/tasks", dependencies=[Depends(auth)])
    async def list_tasks() -> dict:
        return {
            "tasks": [
                {"name": name, "auto_approve": spec.auto_approve, "args": list(spec.args)}
                for name, spec in state.tasks.tasks.items()
            ]
        }

    @app.post("/tasks/{name}", dependencies=[Depends(auth)])
    async def submit_task(name: str, request: Request) -> JSONResponse:
        task = state.tasks.tasks.get(name)
        if task is None:
            state.audit.record(
                kind="task_submit", task=name, decision="deny",
                reason="unknown task", status=404,
            )
            raise HTTPException(status_code=404, detail="unknown task")

        body = await request.body()
        payload: dict = {}
        if body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="invalid JSON body") from exc
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="body must be a JSON object")
        raw_args = payload.get("args", payload) if "args" in payload else payload

        try:
            validated = tasks_mod.validate_args(task, raw_args)
            command = tasks_mod.resolve_command(task, validated)
        except ValidationError as exc:
            state.audit.record(
                kind="task_submit", task=name, decision="reject",
                reason=str(exc), status=400,
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        request_obj = state.store.create(
            name=name,
            args=validated,
            command=command,
            cwd=task.cwd,
            auto_approve=task.auto_approve,
            status="pending",
            caller="agent",
        )
        state.audit.record(
            kind="task_submit", task=name, args=validated,
            request_id=request_obj.id, decision="pending", status=202,
        )

        if task.auto_approve:
            state.audit.record(
                kind="task_auto_approve", task=name,
                request_id=request_obj.id, decision="approve", status=200,
            )
            await tasks_mod.execute(state, request_obj)
            request_obj = state.store.get(request_obj.id)

        return JSONResponse(
            status_code=202,
            content={"request_id": request_obj.id, "status": request_obj.status},
        )

    @app.get("/tasks/requests/{request_id}", dependencies=[Depends(auth)])
    async def get_request(request_id: str) -> dict:
        request_obj = state.store.get(request_id)
        if request_obj is None:
            raise HTTPException(status_code=404, detail="unknown request")
        return request_obj.public()

    @app.api_route(
        "/proxy/{service}/{path:path}", methods=_PROXY_METHODS, dependencies=[Depends(auth)]
    )
    async def proxy(service: str, path: str, request: Request):
        return await proxy_mod.handle_proxy(state, service, path, request)

    @app.api_route("/proxy/{service}", methods=_PROXY_METHODS, dependencies=[Depends(auth)])
    async def proxy_root(service: str, request: Request):
        return await proxy_mod.handle_proxy(state, service, "", request)

    return app


def create_admin_app(state: BrokerState) -> FastAPI:
    """Admin-facing API (separate port + token). The only place approvals can happen."""
    app = FastAPI(
        title="secret-broker admin API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    auth = _auth_dependency(state.settings.admin_token, "x-admin-token")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/requests", dependencies=[Depends(auth)])
    async def list_requests(status: str | None = None) -> dict:
        items = state.store.list()
        if status:
            items = [req for req in items if req.status == status]
        return {"requests": [req.admin_view() for req in items]}

    @app.get("/requests/{request_id}", dependencies=[Depends(auth)])
    async def show_request(request_id: str) -> dict:
        request_obj = state.store.get(request_id)
        if request_obj is None:
            raise HTTPException(status_code=404, detail="unknown request")
        return request_obj.admin_view()

    @app.post("/requests/{request_id}/approve", dependencies=[Depends(auth)])
    async def approve(request_id: str) -> dict:
        result = state.store.transition(
            request_id, expected="pending", new_status="approved",
            decided_at=_now(), approver="admin",
        )
        if result is None:
            raise HTTPException(status_code=404, detail="unknown request")
        if result is False:
            current = state.store.get(request_id)
            raise HTTPException(
                status_code=409,
                detail=f"request is not pending (status={current.status})",
            )
        state.audit.record(
            kind="approval", request_id=request_id, task=result.name,
            decision="approve", caller="admin", status=200,
        )
        await tasks_mod.execute(state, result)
        return state.store.get(request_id).admin_view()

    @app.post("/requests/{request_id}/deny", dependencies=[Depends(auth)])
    async def deny(request_id: str) -> dict:
        result = state.store.transition(
            request_id, expected="pending", new_status="denied",
            decided_at=_now(), finished_at=_now(), approver="admin",
        )
        if result is None:
            raise HTTPException(status_code=404, detail="unknown request")
        if result is False:
            current = state.store.get(request_id)
            raise HTTPException(
                status_code=409,
                detail=f"request is not pending (status={current.status})",
            )
        state.audit.record(
            kind="approval", request_id=request_id, task=result.name,
            decision="deny", caller="admin", status=200,
        )
        return state.store.get(request_id).admin_view()

    return app
