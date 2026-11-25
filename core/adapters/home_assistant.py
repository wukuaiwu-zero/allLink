from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings


class SmartHomeAdapter(ABC):
    """智能家居底座统一适配接口（面向 Home Assistant / Matter 扩展）"""

    @abstractmethod
    async def list_devices(self) -> List[Dict[str, Any]]:
        """列出所有纳管设备及其当前状态"""

    @abstractmethod
    async def execute(
        self, entity_id: str, action: str, value: Optional[Any] = None
    ) -> Dict[str, Any]:
        """执行设备控制动作"""


class MockHomeAssistantAdapter(SmartHomeAdapter):
    """阶段 1 虚拟设备模拟器：用于无真实网关/米家设备时的完整联调"""

    def __init__(self) -> None:
        self._entities: Dict[str, Dict[str, Any]] = {
            "light.living_room_main": {
                "entity_id": "light.living_room_main",
                "name": "客厅主灯",
                "domain": "light",
                "state": "off",
                "attributes": {"brightness": 80},
            },
            "light.desk_lamp": {
                "entity_id": "light.desk_lamp",
                "name": "书桌台灯",
                "domain": "light",
                "state": "on",
                "attributes": {"brightness": 65},
            },
            "climate.bedroom_ac": {
                "entity_id": "climate.bedroom_ac",
                "name": "卧室空调",
                "domain": "climate",
                "state": "off",
                "attributes": {"temperature": 25, "hvac_mode": "cool"},
            },
        }

    async def list_devices(self) -> List[Dict[str, Any]]:
        return list(self._entities.values())

    async def execute(
        self, entity_id: str, action: str, value: Optional[Any] = None
    ) -> Dict[str, Any]:
        entity = self._entities.get(entity_id)
        if not entity:
            # 支持按中文名模糊匹配
            for item in self._entities.values():
                if entity_id in item["name"]:
                    entity = item
                    break
        if not entity:
            raise ValueError(f"未找到虚拟设备: {entity_id}")

        if action == "turn_on":
            entity["state"] = "on"
        elif action == "turn_off":
            entity["state"] = "off"
        elif action == "set_brightness":
            entity["state"] = "on"
            entity["attributes"]["brightness"] = max(0, min(100, int(value or 50)))
        elif action == "set_temperature":
            entity["state"] = "on"
            entity["attributes"]["temperature"] = max(16, min(30, int(value or 25)))
        else:
            raise ValueError(f"不支持的动作: {action}")

        return {
            "ok": True,
            "mode": "mock",
            "device": entity,
            "message": f"[模拟HA] 已对 {entity['name']} 执行 {action}"
            + (f" ({value})" if value is not None else ""),
        }


class RealHomeAssistantAdapter(SmartHomeAdapter):
    """真实 Home Assistant REST API 适配器（.env 设置 HA_MODE=real 即可一键切换）"""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def list_devices(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/api/states", headers=self.headers
            )
            resp.raise_for_status()
            states = resp.json()

        devices = []
        for item in states:
            eid = item.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else ""
            if domain in {"light", "switch", "climate", "fan", "media_player"}:
                devices.append(
                    {
                        "entity_id": eid,
                        "name": item.get("attributes", {}).get("friendly_name", eid),
                        "domain": domain,
                        "state": item.get("state"),
                        "attributes": item.get("attributes", {}),
                    }
                )
        return devices

    async def execute(
        self, entity_id: str, action: str, value: Optional[Any] = None
    ) -> Dict[str, Any]:
        domain = entity_id.split(".")[0]
        payload: Dict[str, Any] = {"entity_id": entity_id}

        if action in {"turn_on", "turn_off"}:
            service = action
        elif action == "set_brightness":
            service = "turn_on"
            payload["brightness_pct"] = max(0, min(100, int(value or 50)))
        elif action == "set_temperature":
            service = "set_temperature"
            payload["temperature"] = int(value or 25)
        else:
            raise ValueError(f"不支持的动作: {action}")

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/api/services/{domain}/{service}",
                headers=self.headers,
                json=payload,
            )
            resp.raise_for_status()

        return {
            "ok": True,
            "mode": "real",
            "entity_id": entity_id,
            "action": action,
            "message": f"[Home Assistant] 已调用 {domain}.{service} -> {entity_id}",
        }


def create_ha_adapter() -> SmartHomeAdapter:
    if settings.ha_mode.lower() == "real" and settings.ha_token:
        return RealHomeAssistantAdapter(settings.ha_url, settings.ha_token)
    return MockHomeAssistantAdapter()


ha_adapter: SmartHomeAdapter = create_ha_adapter()
