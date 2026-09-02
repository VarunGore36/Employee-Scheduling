"""Optional FastAPI adapter over the same service layer: pip install fastapi uvicorn."""

from __future__ import annotations

import secrets

from . import service
from .api import MAX_BODY_BYTES, sample_instance
from .ruleinfo import catalog


def create_app(token: str = "", cors_origin: str = "", max_body: int = MAX_BODY_BYTES):
    """FastAPI is imported here so the package itself stays dependency-free."""
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="Roster generator", version="1.0",
                  description="Rules in, legal roster out.")
    if cors_origin:
        app.add_middleware(CORSMiddleware, allow_origins=[cors_origin],
                           allow_methods=["GET", "POST", "OPTIONS"],
                           allow_headers=["Content-Type", "Authorization", "X-Roster-Token"])

    def check(request: Request) -> None:
        if not token:
            return
        header = request.headers.get("authorization", "")
        given = header[7:].strip() if header[:7].lower() == "bearer " else \
            request.headers.get("x-roster-token", "")
        if not secrets.compare_digest(given, token):
            raise HTTPException(401, {"error": "authorisation required", "field": ""})

    async def payload_of(request: Request) -> dict:
        size = int(request.headers.get("content-length") or 0)
        if size > max_body:
            raise HTTPException(413, {"error": f"request body over {max_body} bytes",
                                      "field": ""})
        if not size:
            return {}
        try:
            data = await request.json()
        except ValueError as exc:
            raise HTTPException(400, {"error": f"body is not valid JSON: {exc}",
                                      "field": ""}) from exc
        if not isinstance(data, dict):
            raise HTTPException(400, {"error": "request body must be a JSON object",
                                      "field": ""})
        return data

    def run(name: str, payload: dict) -> dict:
        try:
            return service.handle(name, payload)
        except service.ServiceError as exc:
            raise HTTPException(400, exc.to_dict()) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, {"error": str(exc), "field": ""}) from exc

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "rule_types": len(service.REGISTRY),
                "endpoints": sorted(service.ENDPOINTS), "authenticated": bool(token)}

    @app.get("/rules")
    def rules(request: Request) -> dict:
        check(request)
        entries = catalog()
        return {"rule_types": entries, "count": len(entries)}

    @app.get("/schema")
    def schema(request: Request) -> dict:
        check(request)
        return service.schema_payload({})

    @app.get("/sample")
    def sample(request: Request, start: str = "2026-09-12", days: int = 31,
               employees: int = 44, seed: int = 7, small: bool = False) -> dict:
        check(request)
        try:
            return {"instance": sample_instance(start, days, employees, seed, small).to_dict()}
        except service.ServiceError as exc:
            raise HTTPException(400, exc.to_dict()) from exc

    for name in sorted(service.ENDPOINTS):
        async def post_endpoint(request: Request, _name: str = name) -> dict:
            check(request)
            return run(_name, await payload_of(request))

        app.post(f"/{name}", name=name)(post_endpoint)

    return app


def serve(host: str = "127.0.0.1", port: int = 8000, token: str = "",
          cors_origin: str = "") -> int:
    """uvicorn in-process, for when the dependencies are installed."""
    import uvicorn

    uvicorn.run(create_app(token, cors_origin), host=host, port=port)
    return 0
