from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class HomePodVolumeRequest(BaseModel):
    level: float = Field(..., ge=0, le=100, description="音量百分比 0-100")
    device_name: Optional[str] = Field(None, description="目标 HomePod 名称，留空使用默认")


class HomePodPlaybackRequest(BaseModel):
    action: Literal["play", "pause", "toggle", "stop"]
    device_name: Optional[str] = None


class HomePodTTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    device_name: Optional[str] = None
    voice: Optional[str] = None


class ComputerCommandRequest(BaseModel):
    target_device: str = Field(..., description="电脑设备 ID 或名称，如 windows-pc / mac-mini")
    action: Literal["lock_screen", "mute", "unmute", "shutdown_timer", "cancel_shutdown"]
    minutes: Optional[int] = Field(None, ge=1, le=1440, description="定时关机分钟数")


class SmartDeviceCommandRequest(BaseModel):
    entity_id: str = Field(..., description="如 light.living_room_main / climate.bedroom_ac")
    action: Literal["turn_on", "turn_off", "set_brightness", "set_temperature"]
    value: Optional[Any] = None


class ChatCommandRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    source: str = Field("web", description="来源终端，如 android / windows / mac")
