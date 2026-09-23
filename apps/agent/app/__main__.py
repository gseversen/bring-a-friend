import uvicorn

from app.config import settings

# `python -m app` so the port comes from the shared .env rather than a CLI flag.
uvicorn.run("app.main:app", host="127.0.0.1", port=settings.agent_port, reload=True)
