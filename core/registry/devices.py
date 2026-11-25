import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import WebSocket


@dataclass
class ComputerDevice:
    device_id: str
    name: str
    os_type: str
    websocket: WebSocket
    capabilities: List[str] = field(default_factory=list)
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


class ComputerRegistry:
    """管理通过 WebSocket 注册到中枢的 Windows / Mac 电脑设备"""

    def __init__(self) -> None:
        self._devices: Dict[str, ComputerDevice] = {}
        self._pending: Dict[str, asyncio.Future] = {}

    def register(
        self,
        device_id: str,
        name: str,
        os_type: str,
        websocket: WebSocket,
        capabilities: Optional[List[str]] = None,
    ) -> ComputerDevice:
        dev = ComputerDevice(
            device_id=device_id,
            name=name,
            os_type=os_type,
            websocket=websocket,
            capabilities=capabilities
            or ["lock_screen", "mute", "unmute", "shutdown_timer", "cancel_shutdown"],
        )
        self._devices[device_id] = dev
        return dev

    def unregister(self, device_id: str) -> None:
        self._devices.pop(device_id, None)

    def handle_agent_message(self, device_id: str, data: Dict[str, Any]) -> None:
        dev = self._devices.get(device_id)
        if dev:
            dev.last_seen = time.time()

        msg_type = data.get("type")
        if msg_type == "command_result":
            req_id = data.get("request_id")
            if req_id and req_id in self._pending:
                fut = self._pending.pop(req_id)
                if not fut.done():
                    fut.set_result(data)

    def list_devices(self) -> List[Dict[str, Any]]:
        return [
            {
                "device_id": d.device_id,
                "name": d.name,
                "os_type": d.os_type,
                "capabilities": d.capabilities,
                "online": True,
                "last_seen": int(d.last_seen),
            }
            for d in self._devices.values()
        ]

    def _find_device(self, target: str) -> Optional[ComputerDevice]:
        key = target.strip().lower()
        if key in self._devices:
            return self._devices[key]
        for dev in self._devices.values():
            if (
                key in dev.device_id.lower()
                or key in dev.name.lower()
                or key in dev.os_type.lower()
            ):
                return dev
        # 常见中文别名匹配
        if any(w in key for w in ("win", "台式", "电脑")):
            for dev in self._devices.values():
                if dev.os_type.lower() == "windows":
                    return dev
        if any(w in key for w in ("mac", "苹果", "mini")):
            for dev in self._devices.values():
                if dev.os_type.lower() in {"darwin", "macos", "mac"}:
                    return dev
        return None

    async def send_command(
        self,
        target_device: str,
        action: str,
        minutes: Optional[int] = None,
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        dev = self._find_device(target_device)
        if not dev:
            online_names = [f"{d.name}({d.device_id})" for d in self._devices.values()]
            raise RuntimeError(
                f"目标电脑 '{target_device}' 未在线。当前在线电脑: {online_names or '无'}"
            )

        req_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut

        payload = {
            "type": "command",
            "request_id": req_id,
            "action": action,
            "params": {"minutes": minutes} if minutes is not None else {},
        }
        try:
            await dev.websocket.send_json(payload)
            result = await asyncio.wait_for(fut, timeout=timeout)
            return {
                "ok": bool(result.get("ok", True)),
                "device_id": dev.device_id,
                "device_name": dev.name,
                "action": action,
                "message": result.get("message", f"已向 {dev.name} 下发 {action}"),
            }
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"等待电脑 {dev.name} 响应超时") from exc


computer_registry = ComputerRegistry()
