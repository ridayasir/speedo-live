"""Small API layer on top of Starlette: declarative routes with pydantic validation,
JWT auth + role checks, per-route rate limits, uniform errors and OpenAPI output."""
from __future__ import annotations

import inspect
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .config import settings
from .db import get_db
from .errors import ApiError
from .security import decode_token, rate_limiter

log = logging.getLogger("speedo.http")
TRUST_PROXY = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes")


def client_ip(request: Request) -> str:
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@dataclass
class Ctx:
    request: Request
    path: dict
    user: dict | None = None
    claims: dict | None = None
    body: Any = None
    query: Any = None

    @property
    def user_id(self) -> int:
        return self.user["id"]


@dataclass
class Spec:
    method: str
    path: str
    handler: Callable
    auth: str | tuple | None          # None=public, "optional", "any", or tuple of roles
    body: type[BaseModel] | None
    query: type[BaseModel] | None
    summary: str
    tags: list[str]
    rate: int | None
    status: int = 200
    responses: dict = field(default_factory=dict)


def json_error(status: int, code: str, message: str, details=None, headers=None) -> JSONResponse:
    payload = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(payload, status_code=status, headers=headers)


def authenticate(request: Request, token: str | None = None) -> tuple[dict | None, dict | None]:
    if token is None:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return None, None
        token = header[7:].strip()
    claims = decode_token(token)
    if not claims:
        raise ApiError(401, "invalid_token", "Your session has expired. Please sign in again.")
    user = get_db().one("SELECT id, name, email, phone, role, is_active FROM users WHERE id = ?", (int(claims["sub"]),))
    if not user or not user["is_active"]:
        raise ApiError(401, "account_disabled", "This account is not active")
    if user["role"] != claims.get("role"):
        raise ApiError(401, "role_changed", "Your role changed. Please sign in again.")
    return user, claims


class ApiRouter:
    def __init__(self) -> None:
        self.specs: list[Spec] = []

    def route(self, method: str, path: str, *, auth=None, body=None, query=None, summary="", tags=(), rate=None, status=200):
        def deco(fn):
            self.specs.append(Spec(method.upper(), path, fn, auth, body, query, summary or (fn.__doc__ or "").strip().split("\n")[0],
                                   list(tags), rate, status))
            return fn
        return deco

    def get(self, path, **kw): return self.route("GET", path, **kw)
    def post(self, path, **kw): return self.route("POST", path, **kw)
    def put(self, path, **kw): return self.route("PUT", path, **kw)
    def patch(self, path, **kw): return self.route("PATCH", path, **kw)
    def delete(self, path, **kw): return self.route("DELETE", path, **kw)

    def _endpoint(self, spec: Spec):
        async def endpoint(request: Request) -> Response:
            try:
                if spec.rate:
                    ok, retry = rate_limiter.allow(f"{spec.method}:{spec.path}:{client_ip(request)}", spec.rate)
                    if not ok:
                        return json_error(429, "rate_limited", "Too many requests. Try again shortly.", headers={"Retry-After": str(retry)})
                ctx = Ctx(request=request, path=dict(request.path_params))
                if spec.auth is not None:
                    user, claims = await run_in_threadpool(authenticate, request)
                    if user is None and spec.auth != "optional":
                        raise ApiError(401, "auth_required", "Sign in to continue")
                    if isinstance(spec.auth, tuple) and user["role"] not in spec.auth:
                        raise ApiError(403, "forbidden", "You do not have permission for this action")
                    ctx.user, ctx.claims = user, claims
                if spec.query is not None:
                    ctx.query = spec.query.model_validate({k: v for k, v in request.query_params.items() if v != ""})
                if spec.body is not None:
                    raw = await request.body()
                    try:
                        data = json.loads(raw or b"{}")
                    except json.JSONDecodeError:
                        raise ApiError(400, "invalid_json", "Request body must be valid JSON")
                    ctx.body = spec.body.model_validate(data)
                if inspect.iscoroutinefunction(spec.handler):
                    result = await spec.handler(ctx)
                else:
                    result = await run_in_threadpool(spec.handler, ctx)
                if isinstance(result, Response):
                    return result
                return JSONResponse(result, status_code=spec.status)
            except ApiError as e:
                return json_error(e.status, e.code, e.message, e.details)
            except ValidationError as e:
                details = [{"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]} for err in e.errors()]
                return json_error(422, "validation_error", "Some fields are invalid", details)
            except Exception:
                log.exception("unhandled error on %s %s", spec.method, spec.path)
                return json_error(500, "server_error", "Something went wrong on our side")
        endpoint.__name__ = spec.handler.__name__
        return endpoint

    def starlette_routes(self) -> list[Route]:
        grouped: dict[str, dict[str, Spec]] = {}
        for s in self.specs:
            grouped.setdefault(s.path, {})[s.method] = s
        routes = []
        for path, methods in grouped.items():
            handlers = {m: self._endpoint(s) for m, s in methods.items()}

            def make(handlers=handlers):
                async def dispatch(request: Request):
                    h = handlers.get(request.method)
                    if h is None:
                        return json_error(405, "method_not_allowed", "Method not allowed")
                    return await h(request)
                return dispatch
            routes.append(Route(path, make(), methods=list(methods)))
        return routes

    # ------------------------------------------------------------- OpenAPI
    def openapi(self) -> dict:
        components: dict[str, Any] = {}
        paths: dict[str, Any] = {}

        def schema_of(model: type[BaseModel]) -> dict:
            sch = model.model_json_schema(ref_template="#/components/schemas/{model}")
            for name, d in sch.pop("$defs", {}).items():
                components[name] = d
            components[model.__name__] = sch
            return {"$ref": f"#/components/schemas/{model.__name__}"}

        for s in self.specs:
            oa_path = re.sub(r"\{(\w+):\w+\}", r"{\1}", s.path)
            op: dict[str, Any] = {"summary": s.summary, "tags": s.tags or ["misc"], "operationId": s.handler.__name__ + "_" + s.method.lower(),
                                  "responses": {str(s.status): {"description": "Success"},
                                                "422": {"description": "Validation error"}}}
            params = [{"name": n, "in": "path", "required": True, "schema": {"type": "integer" if ":int" in s.path else "string"}}
                      for n in re.findall(r"\{(\w+)(?::\w+)?\}", s.path)]
            if s.query is not None:
                qs = s.query.model_json_schema()
                for name, prop in qs.get("properties", {}).items():
                    params.append({"name": name, "in": "query", "required": name in qs.get("required", []), "schema": prop,
                                   "description": prop.get("description", "")})
            if params:
                op["parameters"] = params
            if s.body is not None:
                op["requestBody"] = {"required": True, "content": {"application/json": {"schema": schema_of(s.body)}}}
            if s.auth is not None and s.auth != "optional":
                op["security"] = [{"bearerAuth": []}]
                op["responses"]["401"] = {"description": "Not signed in"}
                if isinstance(s.auth, tuple):
                    op["responses"]["403"] = {"description": f"Requires role: {', '.join(s.auth)}"}
                    op["description"] = f"Roles: {', '.join(s.auth)}"
            if s.rate:
                op["responses"]["429"] = {"description": f"Rate limited ({s.rate}/min per client)"}
            paths.setdefault(oa_path, {})[s.method.lower()] = op
        return {
            "openapi": "3.1.0",
            "info": {"title": "Speedo Live API", "version": "1.0.0",
                     "description": "Smart Speedo bus tracking and route navigation for Lahore. "
                                    f"Running in **{settings.mode.upper()}** mode." +
                                    (" All routes, buses and positions are DEMO data." if settings.is_demo else "")},
            "paths": paths,
            "components": {"schemas": components,
                           "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}},
        }


api = ApiRouter()
