from fastapi import FastAPI

from app.routes.admin import router as admin_router
from app.routes.queue import router as queue_router
from app.routes.requests import router as requests_router

app = FastAPI(title="Item Request Portal")
app.include_router(requests_router)
app.include_router(queue_router)
app.include_router(admin_router)
