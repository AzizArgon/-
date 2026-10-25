from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, catalog, reference, seller
from app.core.config import settings
from app.db.database import init_db
from app.services.importer import fail_stale_imports


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    fail_stale_imports()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Local-only app: Vite may move to 5174+ when 5173 is busy
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(seller.router, prefix="/api")
app.include_router(reference.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
