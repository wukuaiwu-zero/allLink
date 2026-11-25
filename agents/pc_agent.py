"""
AllLink 跨平台电脑控制代理 (支持 Windows & macOS)

启动示例：
  Windows:
    python pc_agent.py --hub ws://<MacMini局域网IP>:8000 --id windows-pc --name "书房Windows电脑"
  Mac mini:
    python pc_agent.py --hub ws://127.0.0.1:8000 --id mac-mini --name "客厅MacMini"
"""

import argparse
import asyncio
import ctypes
import json
import logging
import platform
import subprocess
from typing import Any, Dict, Optional
from urllib.parse import quote

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("alllink.pc_agent")

OS_NAME = platform.system().lower()  # 'windows' / 'darwin' / 'linux'
_mac_shutdown_task: Optional[asyncio.Task] = None


def _windows_toggle_mute() -> None:
    """无额外依赖实现 Windows 系统静音切换 (VK_VOLUME_MUTE = 0xAD)"""
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    VK_VOLUME_MUTE = 0xAD
    user32 = ctypes.windll.user32
    user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_EXTENDEDKEY, 0)
    user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


async def _mac_delayed_shutdown(minutes: int) -> None:
    await asyncio.sleep(minutes * 60)
    subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to shut down'],
        check=False,
    )


async def execute_local_action(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    global _mac_shutdown_task

    try:
        if action == "lock_screen":
            if OS_NAME == "windows":
                ctypes.windll.user32.LockWorkStation()
            elif OS_NAME == "darwin":
                subprocess.run(["pmset", "displaysleepnow"], check=True)
            else:
                subprocess.run(["loginctl", "lock-session"], check=False)
            return {"ok": True, "message": f"{OS_NAME} 已执行锁屏"}

        if action == "mute":
            if OS_NAME == "windows":
                _windows_toggle_mute()
            elif OS_NAME == "darwin":
                subprocess.run(
                    ["osascript", "-e", "set volume with output muted"], check=True
                )
            return {"ok": True, "message": f"{OS_NAME} 已静音"}

        if action == "unmute":
            if OS_NAME == "windows":
                _windows_toggle_mute()
            elif OS_NAME == "darwin":
                subprocess.run(
                    ["osascript", "-e", "set volume without output muted"], check=True
                )
            return {"ok": True, "message": f"{OS_NAME} 已取消静音"}

        if action == "shutdown_timer":
            minutes = int(params.get("minutes") or 30)
            if OS_NAME == "windows":
                seconds = minutes * 60
                subprocess.run(["shutdown", "/s", "/t", str(seconds)], check=True)
            elif OS_NAME == "darwin":
                if _mac_shutdown_task and not _mac_shutdown_task.done():
                    _mac_shutdown_task.cancel()
                _mac_shutdown_task = asyncio.create_task(_mac_delayed_shutdown(minutes))
            return {"ok": True, "message": f"{OS_NAME} 已设置 {minutes} 分钟后自动关机"}

        if action == "cancel_shutdown":
            if OS_NAME == "windows":
                subprocess.run(["shutdown", "/a"], check=False)
            elif OS_NAME == "darwin":
                if _mac_shutdown_task and not _mac_shutdown_task.done():
                    _mac_shutdown_task.cancel()
                    _mac_shutdown_task = None
            return {"ok": True, "message": f"{OS_NAME} 已取消定时关机"}

        return {"ok": False, "message": f"不支持的动作: {action}"}
    except Exception as exc:
        logger.exception("执行动作 %s 失败", action)
        return {"ok": False, "message": f"执行失败: {exc}"}


async def run_agent(hub_url: str, device_id: str, device_name: str) -> None:
    ws_url = (
        f"{hub_url.rstrip('/')}/ws/agent/{quote(device_id)}"
        f"?name={quote(device_name)}&os={quote(OS_NAME)}"
    )

    while True:
        try:
            logger.info("正在连接 AllLink 中枢: %s", ws_url)
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                logger.info("已成功注册到中枢！设备 ID: %s (%s)", device_id, OS_NAME)
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("type") == "command":
                        req_id = data.get("request_id")
                        action = data.get("action", "")
                        params = data.get("params") or {}
                        logger.info("收到中枢指令: action=%s params=%s", action, params)
                        res = await execute_local_action(action, params)
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "command_result",
                                    "request_id": req_id,
                                    **res,
                                },
                                ensure_ascii=False,
                            )
                        )
        except Exception as exc:
            logger.warning("连接断开或失败 (%s)，3 秒后自动重连...", exc)
            await asyncio.sleep(3)


def main() -> None:
    parser = argparse.ArgumentParser(description="AllLink PC Control Agent")
    parser.add_argument(
        "--hub",
        default="ws://127.0.0.1:8000",
        help="中枢 WebSocket 地址，例如 ws://192.168.1.10:8000",
    )
    parser.add_argument(
        "--id",
        default=f"{OS_NAME}-pc",
        help="设备唯一 ID，例如 windows-pc 或 mac-mini",
    )
    parser.add_argument(
        "--name",
        default=platform.node() or f"{OS_NAME}-pc",
        help="设备显示名称",
    )
    args = parser.parse_args()
    asyncio.run(run_agent(args.hub, args.id, args.name))


if __name__ == "__main__":
    main()
