"""Phase 1 hello-world service.

Its only job: prove the platform loop works end-to-end —
build → push to Artifact Registry → Helm deploy to GKE → reachable → health checks pass.
Real services (agent, llm-proxy, approval) replace this in later phases.
"""
import os

from fastapi import FastAPI

app = FastAPI(title="sap-hello")

NODE = os.getenv("NODE_NAME", "unknown")
POD = os.getenv("POD_NAME", "unknown")


@app.get("/")
def root():
    return {
        "service": "sap-hello",
        "message": "Support Agent Platform — Phase 1 platform foundation is live.",
        "pod": POD,
        "node": NODE,
    }


@app.get("/healthz")
def healthz():
    """Liveness/readiness probe target."""
    return {"status": "ok"}
