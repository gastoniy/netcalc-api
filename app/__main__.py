"""Entrypoint so the app runs as `python -m app`.

Using the module form (rather than the `uvicorn` console script) matters
for distroless images: there's no shell and the script may not be on PATH,
but `python -m app` always works.
"""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - must bind all interfaces inside a container
        port=int(os.getenv("PORT", "8000")),
    )
