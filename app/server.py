"""Run the API server: ``uvicorn app.main:app``  (or ``python -m app.server``)."""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
