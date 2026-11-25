import asyncio
import logging
import os
import tempfile
import uuid
from typing import Any, Dict, List, Optional

import edge_tts
import pyatv
from pyatv.const import Protocol

from core.config import settings

logger = logging.getLogger(__name__)


class HomePodPlugin:
    """基于 pyatv + edge-tts 的 HomePod 发现、控制与语音播报插件"""

    def __init__(self) -> None:
        self._devices_cache: List[pyatv.interface.BaseConfig] = []
        self._stream_lock = asyncio.Lock()

    async def discover(self, timeout: int = 3) -> List[Dict[str, Any]]:
        """扫描局域网内支持 AirPlay / RAOP 的设备（优先识别 HomePod）"""
        loop = asyncio.get_running_loop()
        atvs = await pyatv.scan(loop, timeout=timeout)

        # 过滤具备 AirPlay 或 RAOP 服务的设备
        valid = [
            dev
            for dev in atvs
            if dev.get_service(Protocol.AirPlay) or dev.get_service(Protocol.RAOP)
        ]
        self._devices_cache = valid

        results = []
        for dev in valid:
            model_str = str(dev.device_info.model) if dev.device_info else "Unknown"
            results.append(
                {
                    "name": dev.name,
                    "address": str(dev.address),
                    "identifier": dev.identifier,
                    "model": model_str,
                    "is_homepod": "homepod" in model_str.lower()
                    or "homepod" in dev.name.lower(),
                }
            )
        return results

    async def _resolve_device(
        self, device_name: Optional[str] = None
    ) -> pyatv.interface.BaseConfig:
        """解析目标 HomePod，若缓存为空则自动触发一次扫描"""
        if not self._devices_cache:
            await self.discover()

        if not self._devices_cache:
            raise RuntimeError(
                "未在局域网内发现任何 HomePod / AirPlay 设备。"
                "请确认在同一局域网且已在苹果「家庭」App 中开启「允许同一网络中的任何人访问」。"
            )

        target_name = device_name or settings.homepod_default_name
        if target_name:
            for dev in self._devices_cache:
                if target_name.lower() in dev.name.lower():
                    return dev
            # 重新扫描一次以防设备刚上线
            await self.discover()
            for dev in self._devices_cache:
                if target_name.lower() in dev.name.lower():
                    return dev
            raise RuntimeError(f"未找到名称包含 '{target_name}' 的 HomePod 设备")

        # 默认优先返回名字或型号包含 HomePod 的设备，否则返回第一台
        for dev in self._devices_cache:
            model_str = str(dev.device_info.model) if dev.device_info else ""
            if "homepod" in model_str.lower() or "homepod" in dev.name.lower():
                return dev
        return self._devices_cache[0]

    async def set_volume(
        self, level: float, device_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """设置 HomePod 音量 (0-100)"""
        config = await self._resolve_device(device_name)
        loop = asyncio.get_running_loop()
        atv = await pyatv.connect(config, loop)
        try:
            await atv.audio.set_volume(float(level))
            return {
                "ok": True,
                "device": config.name,
                "volume": level,
                "message": f"已将 {config.name} 音量调节至 {int(level)}%",
            }
        finally:
            atv.close()

    async def playback(
        self, action: str, device_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """控制播放 / 暂停 / 停止"""
        config = await self._resolve_device(device_name)
        loop = asyncio.get_running_loop()
        atv = await pyatv.connect(config, loop)
        try:
            rc = atv.remote_control
            if action == "play":
                await rc.play()
            elif action == "pause":
                await rc.pause()
            elif action == "toggle":
                await rc.play_pause()
            elif action == "stop":
                await rc.stop()
            else:
                raise ValueError(f"不支持的播放动作: {action}")
            return {
                "ok": True,
                "device": config.name,
                "action": action,
                "message": f"已对 {config.name} 执行 {action}",
            }
        finally:
            atv.close()

    async def speak(
        self,
        text: str,
        device_name: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> Dict[str, Any]:
        """将文本通过 Edge-TTS 转为音频，并通过 AirPlay/RAOP 推送到 HomePod 播报"""
        config = await self._resolve_device(device_name)
        chosen_voice = voice or settings.tts_voice
        tmp_file = os.path.join(
            tempfile.gettempdir(), f"alllink_tts_{uuid.uuid4().hex}.mp3"
        )

        async with self._stream_lock:
            try:
                communicate = edge_tts.Communicate(text=text, voice=chosen_voice)
                await communicate.save(tmp_file)

                loop = asyncio.get_running_loop()
                atv = await pyatv.connect(config, loop)
                try:
                    await atv.stream.stream_file(tmp_file)
                finally:
                    atv.close()

                return {
                    "ok": True,
                    "device": config.name,
                    "text": text,
                    "voice": chosen_voice,
                    "message": f"已在 {config.name} 播报完成",
                }
            finally:
                if os.path.exists(tmp_file):
                    try:
                        os.remove(tmp_file)
                    except OSError:
                        pass


homepod_plugin = HomePodPlugin()
