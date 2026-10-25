"""Loopback-only update API for the packaged desktop app."""

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.routes.public_model_settings import require_local_access
from app.services.desktop_updates import check_for_update, launch_verified_installer

router = APIRouter(prefix="/desktop-update", tags=["desktop-update"])


@router.get("/check", dependencies=[Depends(require_local_access)])
async def check(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return await check_for_update()


@router.post("/install", dependencies=[Depends(require_local_access)])
async def install(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        launch_verified_installer()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"accepted": True}
