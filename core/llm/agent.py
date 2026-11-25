import json
import logging
import re
from typing import Any, Dict, List

from openai import AsyncOpenAI

from core.adapters.home_assistant import ha_adapter
from core.config import settings
from core.plugins.homepod import homepod_plugin
from core.registry.devices import computer_registry

logger = logging.getLogger(__name__)

TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "speak_on_homepod",
            "description": "让 HomePod 语音播报一段文字内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "需要播报的文本"},
                    "device_name": {"type": "string", "description": "可选，HomePod 名称"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_homepod_volume",
            "description": "调节 HomePod 音量（0 到 100 之间的百分比）",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "number", "description": "音量百分比 0-100"},
                    "device_name": {"type": "string", "description": "可选，HomePod 名称"},
                },
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_homepod_playback",
            "description": "控制 HomePod 的播放状态：play(播放)、pause(暂停)、toggle(切换)、stop(停止)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "toggle", "stop"],
                    },
                    "device_name": {"type": "string", "description": "可选，HomePod 名称"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_computer",
            "description": "控制已注册的 Windows 电脑或 Mac mini（锁屏、静音、取消静音、定时关机、取消定时关机）",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_device": {
                        "type": "string",
                        "description": "电脑标识，如 windows-pc、mac-mini、windows、mac",
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "lock_screen",
                            "mute",
                            "unmute",
                            "shutdown_timer",
                            "cancel_shutdown",
                        ],
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "定时关机分钟数（仅 shutdown_timer 时需要）",
                    },
                },
                "required": ["target_device", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_smart_device",
            "description": "控制智能家居设备（灯光、空调等，通过 Home Assistant 适配器）",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "设备实体ID或名称，如 light.living_room_main、light.desk_lamp、climate.bedroom_ac",
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "turn_on",
                            "turn_off",
                            "set_brightness",
                            "set_temperature",
                        ],
                    },
                    "value": {
                        "type": "number",
                        "description": "可选数值，如亮度(0-100)或温度(16-30)",
                    },
                },
                "required": ["entity_id", "action"],
            },
        },
    },
]


async def _execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if name == "speak_on_homepod":
            return await homepod_plugin.speak(
                text=args["text"], device_name=args.get("device_name")
            )
        if name == "set_homepod_volume":
            return await homepod_plugin.set_volume(
                level=float(args["level"]), device_name=args.get("device_name")
            )
        if name == "control_homepod_playback":
            return await homepod_plugin.playback(
                action=args["action"], device_name=args.get("device_name")
            )
        if name == "control_computer":
            return await computer_registry.send_command(
                target_device=args["target_device"],
                action=args["action"],
                minutes=args.get("minutes"),
            )
        if name == "control_smart_device":
            return await ha_adapter.execute(
                entity_id=args["entity_id"],
                action=args["action"],
                value=args.get("value"),
            )
        return {"ok": False, "message": f"未知工具: {name}"}
    except Exception as exc:
        logger.exception("Tool execution failed: %s", name)
        return {"ok": False, "message": str(exc)}


async def _fallback_rule_parse(message: str) -> Dict[str, Any]:
    """当未配置 LLM_API_KEY 时的轻量本地兜底解析，方便零配置快速联调"""
    text = message.strip()
    actions: List[Dict[str, Any]] = []

    if "锁屏" in text:
        target = "mac-mini" if "mac" in text.lower() else "windows-pc"
        res = await _execute_tool(
            "control_computer", {"target_device": target, "action": "lock_screen"}
        )
        actions.append({"tool": "control_computer", "result": res})
    elif "静音" in text:
        target = "mac-mini" if "mac" in text.lower() else "windows-pc"
        act = "unmute" if "取消" in text else "mute"
        res = await _execute_tool(
            "control_computer", {"target_device": target, "action": act}
        )
        actions.append({"tool": "control_computer", "result": res})
    elif "关机" in text:
        target = "mac-mini" if "mac" in text.lower() else "windows-pc"
        if "取消" in text:
            res = await _execute_tool(
                "control_computer",
                {"target_device": target, "action": "cancel_shutdown"},
            )
        else:
            m = re.search(r"(\d+)\s*分钟", text)
            mins = int(m.group(1)) if m else 30
            res = await _execute_tool(
                "control_computer",
                {
                    "target_device": target,
                    "action": "shutdown_timer",
                    "minutes": mins,
                },
            )
        actions.append({"tool": "control_computer", "result": res})
    elif "播报" in text or "说" in text:
        spoken = re.sub(r"^.*?(播报|说)[：:，,\s]*", "", text) or text
        res = await _execute_tool("speak_on_homepod", {"text": spoken})
        actions.append({"tool": "speak_on_homepod", "result": res})
    elif "音量" in text:
        m = re.search(r"(\d+)", text)
        lvl = int(m.group(1)) if m else 40
        res = await _execute_tool("set_homepod_volume", {"level": lvl})
        actions.append({"tool": "set_homepod_volume", "result": res})
    elif "暂停" in text:
        res = await _execute_tool("control_homepod_playback", {"action": "pause"})
        actions.append({"tool": "control_homepod_playback", "result": res})
    elif "播放" in text:
        res = await _execute_tool("control_homepod_playback", {"action": "play"})
        actions.append({"tool": "control_homepod_playback", "result": res})
    elif "灯" in text or "空调" in text:
        eid = (
            "climate.bedroom_ac"
            if "空调" in text
            else ("light.desk_lamp" if "台灯" in text else "light.living_room_main")
        )
        act = "turn_off" if "关" in text else "turn_on"
        res = await _execute_tool(
            "control_smart_device", {"entity_id": eid, "action": act}
        )
        actions.append({"tool": "control_smart_device", "result": res})

    if actions:
        summary = "；".join(a["result"].get("message", "") for a in actions)
        return {"reply": f"[本地规则模式] {summary}", "actions": actions}

    return {
        "reply": "当前未配置 LLM_API_KEY（已启用本地关键词兜底模式）。请尝试输入如：'Windows 锁屏'、'让 HomePod 播报吃饭了'、'把客厅主灯打开'，或在 .env 中配置 DeepSeek/Ollama 接口解锁完整自然语言理解。",
        "actions": [],
    }


async def run_ai_command(message: str, source: str = "web") -> Dict[str, Any]:
    """调用 OpenAI 兼容 / Ollama LLM 的 Function Calling 执行自然语言指令"""
    if not settings.llm_api_key:
        return await _fallback_rule_parse(message)

    computers = computer_registry.list_devices()
    ha_devices = await ha_adapter.list_devices()

    system_prompt = (
        "你是 AllLink 本地智能家居与跨端音频中枢的 AI 管家。"
        "请根据用户的自然语言指令，精准调用提供的工具完成操作，并用简短自然的中文回复执行结果。\n"
        f"当前在线电脑列表: {json.dumps(computers, ensure_ascii=False)}\n"
        f"当前智能家居设备列表: {json.dumps(ha_devices, ensure_ascii=False)}\n"
        f"指令来源终端: {source}\n"
        "注意：当用户提到'电脑'但未指明哪一台时，若只有一台 Windows 电脑在线，默认操作 Windows 电脑；"
        "允许在单次回复中并行调用多个工具（例如同时关灯、暂停音箱并锁屏）。"
    )

    client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]

    resp = await client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",
        temperature=0.2,
    )

    assistant_msg = resp.choices[0].message
    tool_calls = assistant_msg.tool_calls or []
    executed_actions: List[Dict[str, Any]] = []

    if not tool_calls:
        return {"reply": assistant_msg.content or "已收到指令。", "actions": []}

    messages.append(assistant_msg.model_dump(exclude_none=True))

    for tc in tool_calls:
        fn_name = tc.function.name
        fn_args = json.loads(tc.function.arguments or "{}")
        result = await _execute_tool(fn_name, fn_args)
        executed_actions.append({"tool": fn_name, "args": fn_args, "result": result})
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

    final_resp = await client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=0.3,
    )
    reply_text = final_resp.choices[0].message.content or "操作已执行完成。"
    return {"reply": reply_text, "actions": executed_actions}
