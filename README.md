# AllLink (Stage 1 MVP)

跨平台 AI 智能家居与音频中枢（支持 Mac mini 开发起步，Docker 零改动迁移至 ARM64 Linux 盒子）。

## 快速启动（Mac mini 宿主机）

```bash
cp .env.example .env
# 编辑 .env 填入你的 LLM_API_KEY（支持 DeepSeek / OpenAI / 通义千问 / 本地 Ollama）

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 启动中枢服务
uvicorn core.main:app --host 0.0.0.0 --port 8000 --reload
```

## 启动电脑控制代理

在 **Mac mini** 上：
```bash
pip install -r agents/requirements-agent.txt
python3 agents/pc_agent.py --hub ws://127.0.0.1:8000 --id mac-mini --name "客厅MacMini"
```

在 **无蓝牙 Windows 电脑** 上：
```powershell
pip install -r agents/requirements-agent.txt
python agents/pc_agent.py --hub ws://<MacMini局域网IP>:8000 --id windows-pc --name "书房Windows"
```

## 浏览器访问

在 Android 手机、Windows 或 Mac 浏览器打开：`http://<MacMini局域网IP>:8000`
