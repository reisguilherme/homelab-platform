"""Private same-origin API and portal. Run exactly one worker for memory sessions."""

import asyncio
import logging
import os
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .audit import (
    MAINTENANCE_BATCH_SIZE,
    MAINTENANCE_LOCK_TIMEOUT_SECONDS,
    MAINTENANCE_SQL_BUDGET_SECONDS,
    OperationStore,
)
from .auth import COOKIE, SessionStore, check_csrf, check_origin
from .models import (
    Acl,
    Action,
    ControlError,
    CreateVM,
    Deletion,
    Login,
    Resources,
    Settings,
    Tfa,
    require,
)
from .operations import Governance
from .proxmox import ProxmoxClient

MAINTENANCE_INTERVAL_SECONDS = 3600
logger = logging.getLogger(__name__)


async def maintain_journal(store, retention_days):
    stop = threading.Event()
    while True:
        work = asyncio.create_task(asyncio.to_thread(store.maintain, retention_days, cancel=stop))
        try:
            # Cancellation must drain a running transaction before lifespan exits.
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                stop.set()
                # A second cancellation must not detach a still-running SQLite writer.
                while not work.done():
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                with suppress(Exception):
                    work.result()
                raise
        except Exception:
            logger.warning("Journal maintenance failed; retrying at the next interval.")
        await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)


def create_app(settings, proxmox=None, audit=None):
    pve = proxmox or ProxmoxClient(settings)
    store = audit or OperationStore(settings.db_path)

    @asynccontextmanager
    async def lifespan(_app):
        maintenance = asyncio.create_task(maintain_journal(store, settings.audit_retention_days))
        try:
            yield
        finally:
            maintenance.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    sessions = SessionStore()
    service = Governance(settings, pve, store)
    app.state.sessions, app.state.governance = sessions, service

    def error(request, status, code, message):
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "requestId": getattr(request.state, "request_id", "unknown"),
                }
            },
        )

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        if exc.status == 401:
            sessions.drop(request.cookies.get(COOKIE))
        return error(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, _exc):
        # Pydantic's default includes input values, including passwords. Never return them.
        return error(request, 422, "invalid_fields", "Campos inválidos ou não permitidos.")

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, _exc):
        return error(
            request,
            503,
            "journal_unavailable",
            "Registro durável indisponível; confira a operação antes de tentar novamente.",
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, _exc):
        return error(request, 503, "service_unavailable", "Não foi possível confirmar a operação.")

    @app.middleware("http")
    async def boundary(request, call_next):
        request.state.request_id = secrets.token_hex(16)
        try:
            if request.url.path.startswith("/api/") and request.method in (
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
            ):
                check_origin(request, settings.origin)
                require(
                    len(await request.body()) <= 16384,
                    "body_limit",
                    "Requisição muito grande.",
                    413,
                )
            response = await call_next(request)
        except ControlError as exc:
            response = error(request, exc.status, exc.code, exc.message)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    def authenticated(request: Request):
        session = sessions.get(request.cookies.get(COOKIE))
        if request.method in ("POST", "PATCH", "PUT", "DELETE"):
            check_csrf(request, session)
        return session

    session_dependency = Depends(authenticated)

    def session_result(result, response):
        key, body = sessions.accept(result)
        if key:
            response.set_cookie(
                COOKIE, key, max_age=7200, secure=True, httponly=True, samesite="strict", path="/"
            )
        return body

    def operation_key(request):
        return request.headers.get("Idempotency-Key", "")

    @app.get("/healthz")
    def health():
        return {"status": "alive"}

    @app.get("/api/v1/session")
    def session_get(request: Request):
        try:
            return sessions.dto(sessions.get(request.cookies.get(COOKIE)))
        except ControlError:
            return {"authenticated": False, "user": None, "csrfToken": None}

    @app.post("/api/v1/session")
    def session_create(body: Login, request: Request, response: Response):
        sessions.rate_limit((request.client.host, body.username))
        sessions.rate_limit(("client", request.client.host))
        return session_result(pve.login(body.username, body.password, body.otp), response)

    @app.post("/api/v1/session/tfa")
    def session_tfa(body: Tfa, request: Request, response: Response):
        sessions.rate_limit(("tfa", request.client.host))
        challenge = sessions.challenge(body.challengeId)
        result = pve.tfa(challenge, body.code)
        require(
            not result.get("NeedTFA") and "!tfa!" not in result.get("ticket", ""),
            "tfa_incomplete",
            "Autenticação de dois fatores incompleta.",
            401,
        )
        return session_result(result, response)

    @app.delete("/api/v1/session", status_code=204)
    def session_delete(request: Request, response: Response, _session=session_dependency):
        sessions.drop(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict", path="/")

    @app.get("/api/v1/overview")
    def overview(session=session_dependency):
        return service.overview(session)

    @app.get("/api/v1/profiles")
    def profiles(session=session_dependency):
        return service.profiles(session)

    @app.get("/api/v1/vms")
    def vms(session=session_dependency):
        return service.list_vms(session)

    @app.get("/api/v1/vms/{vmid}")
    def vm(vmid: int, session=session_dependency):
        return service.details(session, vmid)[0]

    @app.post("/api/v1/vms", status_code=202)
    def create_vm(body: CreateVM, request: Request, session=session_dependency):
        return service.create(session, operation_key(request), body)

    @app.patch("/api/v1/vms/{vmid}/resources", status_code=202)
    def resources(vmid: int, body: Resources, request: Request, session=session_dependency):
        return service.mutate_vm(session, operation_key(request), vmid, "resources", body)

    @app.post("/api/v1/vms/{vmid}/actions", status_code=202)
    def action(vmid: int, body: Action, request: Request, session=session_dependency):
        return service.mutate_vm(session, operation_key(request), vmid, "power", body)

    @app.post("/api/v1/vms/{vmid}/deletion-preview")
    def preview(vmid: int, session=session_dependency):
        return service.deletion_preview(session, vmid)

    @app.delete("/api/v1/vms/{vmid}", status_code=202)
    def delete_vm(vmid: int, body: Deletion, request: Request, session=session_dependency):
        return service.mutate_vm(session, operation_key(request), vmid, "delete", body)

    @app.get("/api/v1/vms/{vmid}/acl")
    def acl_get(vmid: int, session=session_dependency):
        return service.acl(session, vmid)

    @app.put("/api/v1/vms/{vmid}/acl", status_code=202)
    def acl_put(vmid: int, body: Acl, request: Request, session=session_dependency):
        return service.mutate_vm(session, operation_key(request), vmid, "acl-add", body)

    @app.delete("/api/v1/vms/{vmid}/acl", status_code=202)
    def acl_delete(vmid: int, body: Acl, request: Request, session=session_dependency):
        return service.mutate_vm(session, operation_key(request), vmid, "acl-remove", body)

    @app.get("/api/v1/operations/{identifier}")
    def operation(identifier: str, session=session_dependency):
        return service.operation(session, identifier)

    @app.get("/api/v1/audit")
    def audit_get(cursor: int = Query(default=0, ge=0, le=100000), session=session_dependency):
        return service.audit(session, cursor)

    @app.get("/api/v1/audit/maintenance")
    def maintenance_get(_session=session_dependency):
        return {
            "retentionDays": settings.audit_retention_days,
            "intervalSeconds": MAINTENANCE_INTERVAL_SECONDS,
            "batchSize": MAINTENANCE_BATCH_SIZE,
            "lockTimeoutSeconds": MAINTENANCE_LOCK_TIMEOUT_SECONDS,
            "sqlBudgetSeconds": MAINTENANCE_SQL_BUDGET_SECONDS,
            **store.maintenance_status(),
        }

    static = Path(__file__).parent / "static"
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=static), name="static")

        @app.get("/")
        def index():
            return FileResponse(static / "index.html")

    return app


app = create_app(Settings.from_env()) if "PLATFORM_ORIGIN" in os.environ else None
