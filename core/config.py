from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    hub_host: str = "0.0.0.0"
    hub_port: int = 8000

    # LLM (OpenAI 兼容接口或本地 Ollama)
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    # HomePod & TTS
    homepod_default_name: str = ""
    tts_voice: str = "zh-CN-XiaoxiaoNeural"

    # Home Assistant 适配器 (mock / real)
    ha_mode: str = "mock"
    ha_url: str = "http://127.0.0.1:8123"
    ha_token: str = ""


settings = Settings()
