from __future__ import annotations

from mangum import Mangum

from .api_v1_endpoints import app


handler = Mangum(app, lifespan="off")
