from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    demo_mode: bool
    # Which integrations have credentials configured (never the keys themselves!)
    integrations: dict[str, bool]
