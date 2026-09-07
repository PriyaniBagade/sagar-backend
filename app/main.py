from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config.database import engine, Base

# Register all models so create_all picks them up
import app.models.port  # noqa: F401
import app.models.vessel_class  # noqa: F401
import app.models.feature_store  # noqa: F401
import app.models.forecast  # noqa: F401
import app.models.vessel  # noqa: F401
import app.models.charter_schedule  # noqa: F401

from app.routers.vessel_optimization import router as vessel_router
from app.routers.forecast import router as forecast_router
from app.routers.idle import router as idle_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sagar API", swagger_ui_parameters={"persistAuthorization": True})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vessel_router)
app.include_router(forecast_router)
app.include_router(idle_router)


@app.get("/")
def root():
    return {"message": "API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}
