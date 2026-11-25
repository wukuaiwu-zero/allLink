import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.adapters.home_assistant import ha_adapter
from core.config import settings
from core.llm.agent import run_ai_command
from core.plugins.homepod import homepod_plugin
from core.registry.devices import computer_registry
from core.schemas import (
    ChatCommandRequest,
    ComputerCommandRequest,
    HomePodPlaybackRequest,
    HomePodTTSRequest,
    HomePodVolumeRequest,
    SmartDeviceCommandRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("alllink.hub")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="AllLink Hub (Stage 1 MVP)",
    description="跨平台 AI 智能家居与音频中枢服务",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_web_ui():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Web UI not found")
    return FileResponse(str(index_file))


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "llm_configured": bool(settings.llm_api_key),
        "llm_model": settings.llm_model,
        "ha_mode": settings.ha_mode,
    }


# ==================== 1. HomePod 控制接口 ====================


@app.get("/api/homepod/discover")
async def discover_homepods(timeout: int = 3):
    try:
        devices = await homepod_plugin.discover(timeout=timeout)
        return {"ok": True, "count": len(devices), "devices": devices}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/homepod/volume")
async def set_homepod_volume(req: HomePodVolumeRequest):
    try:
        return await homepod_plugin.set_volume(
            level=req.level, device_name=req.device_name
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/homepod/playback")
async def control_homepod_playback(req: HomePodPlaybackRequest):
    try:
        return await homepod_plugin.playback(
            action=req.action, device_name=req.device_name
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/homepod/tts")
async def homepod_tts(req: HomePodTTSRequest):
    try:
        return await homepod_plugin.speak(
            text=req.text, device_name=req.device_name, voice=req.voice
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ==================== 2. 电脑设备注册与控制接口 ====================


@app.get("/api/computers")
async def list_computers():
    return {"ok": True, "devices": computer_registry.list_devices()}


@app.post("/api/computers/command")
async def send_computer_command(req: ComputerCommandRequest):
    try:
        return await computer_registry.send_command(
            target_device=req.target_device,
            action=req.action,
            minutes=req.minutes,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.websocket("/ws/agent/{device_id}")
async def computer_agent_ws(websocket: WebSocket, device_id: str):
    """Windows / Mac mini 电脑代理通过此 WebSocket 注册并接收中枢指令"""
    await websocket.accept()
    name = websocket.query_params.get("name", device_id)
    os_type = websocket.query_params.get("os", "unknown")

    computer_registry.register(
        device_id=device_id,
        name=name,
        os_type=os_type,
        websocket=websocket,
    )
    logger.info("PC Agent 已上线: %s (%s / %s)", device_id, name, os_type)

    try:
        while True:
            data = await websocket.receive_json()
            computer_registry.handle_agent_message(device_id, data)
    except WebSocketDisconnect:
        logger.info("PC Agent 已离线: %s", device_id)
    finally:
        computer_registry.unregister(device_id)


# ==================== 3. Home Assistant 适配器接口 ====================


@app.get("/api/smart-home/devices")
async def list_smart_home_devices():
    try:
        devices = await ha_adapter.list_devices()
        return {"ok": True, "mode": settings.ha_mode, "devices": devices}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/smart-home/command")
async def control_smart_home_device(req: SmartDeviceCommandRequest):
    try:
        return await ha_adapter.execute(
            entity_id=req.entity_id,
            action=req.action,
            value=req.value,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ==================== 4. AI 自然语言指令入口 ====================


@app.post("/api/chat")
async def ai_chat_command(req: ChatCommandRequest):
    try:
        result = await run_ai_command(message=req.message, source=req.source)
        return {"ok": True, **result}
    except Exception as exc:
        logger.exception("AI 指令执行异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
