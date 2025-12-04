import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.config import setup_logging, request_id_var, generate_request_id
from app.routes import pages, decks, logs

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting application")
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_logging_middleware(request: Request, call_next):
    request_id = generate_request_id()
    request_id_var.set(request_id)

    logger.info(
        "Request started",
        extra={"method": request.method, "path": request.url.path},
    )

    response: Response = await call_next(request)

    logger.info(
        "Request completed",
        extra={"method": request.method, "path": request.url.path, "status_code": response.status_code},
    )

    return response


app.include_router(pages.router)
app.include_router(decks.router)
app.include_router(logs.router)
