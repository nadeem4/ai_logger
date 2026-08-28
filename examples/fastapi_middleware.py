"""FastAPI middleware that routes unhandled exceptions through logscribe.

fastapi and uvicorn are deliberately NOT logscribe dependencies (in any
extra) -- importing this file in CI would break every environment that
doesn't happen to have them installed. tests/test_examples.py therefore
only verifies this file py_compile's; its runtime behaviour is not
verified there. Run it manually to see it work.

Install:
    pip install "logscribe[openai]" fastapi uvicorn

Run:
    uvicorn examples.fastapi_middleware:app --reload
    curl http://127.0.0.1:8000/boom
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from logscribe import AIHandler, get_async_logging_setup

logger = logging.getLogger("logscribe.examples.fastapi_middleware")
logger.setLevel(logging.INFO)

# AIHandler needs OPENAI_API_KEY (or ANTHROPIC_API_KEY + LOGSCRIBE_PROVIDER=anthropic)
# set in the environment to actually call an LLM -- see README's Quickstart.
_ai_handler = AIHandler(level=logging.ERROR)
_queue_handler, _listener = get_async_logging_setup(_ai_handler)
logger.addHandler(_queue_handler)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _listener.start()
    try:
        yield
    finally:
        _listener.stop()
        _ai_handler.close()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(Exception)
async def logscribe_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Logs every unhandled exception through AIHandler before returning a
    generic 500 to the client, instead of leaking a traceback."""
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/boom")
async def boom() -> None:
    """Deliberately raises, to exercise the exception handler above."""
    raise RuntimeError("simulated failure for the logscribe fastapi example")
