import os
from typing import Dict, List
from .llm_client import LLMConfig

DEFAULT_SCRIPT_MODEL = "[满血A]gemini-3.1-pro-preview-maxthinking"
DEFAULT_CODE_MODEL = "claude-sonnet-4-6"

MODEL_REGISTRY: Dict[str, Dict] = {
    # ===== Gemini =====
    "[满血A]gemini-3-pro-preview-maxthinking": {
        "display_name": "Gemini 3 Pro Preview MaxThinking",
        "roles": ["script", "code"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },
    "[满血A]gemini-3.1-pro-preview-maxthinking": {
        "display_name": "Gemini 3.1 Pro Preview MaxThinking",
        "roles": ["script", "code"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },

    # ===== GPT =====
    "gpt-5.1": {
        "display_name": "GPT-5.1",
        "roles": ["script", "code"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },
    "gpt-5.4": {
        "display_name": "GPT-5.4",
        "roles": ["script", "code"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },
    "gpt-5.3-codex": {
        "display_name": "GPT-5.3 Codex",
        "roles": ["code"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },
    "gpt-5.2-codex": {
        "display_name": "GPT-5.2 Codex",
        "roles": ["code"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },
    "gpt-5.1-codex-max": {
        "display_name": "GPT-5.1 Codex Max",
        "roles": ["code"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },

    # ===== Claude =====
    "claude-sonnet-4-6": {
        "display_name": "Claude Sonnet 4.6",
        "roles": ["code"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },

    # ===== Qwen =====
    "qwen-max": {
        "display_name": "Qwen Max",
        "roles": ["script"],
        "provider": "dashscope",
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },
    "qwen-plus": {
        "display_name": "Qwen Plus",
        "roles": ["code"],
        "provider": "dashscope",
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },

    # ===== Gemma =====
    "gemma-4-31b": {
        "display_name": "Gemma 4 31B",
        "roles": ["script"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 120.0,
        "max_retries": 2,
    },

    # ===== Image =====
    "[官]gemini-3.1-flash-image-preview": {
        "display_name": "Gemini 3.1 Flash Image Preview",
        "roles": ["image"],
        "provider": "gemai",
        "api_key_env": "GEMAI_API_KEY",
        "base_url": "https://api.gemai.cc/v1",
        "temperature_script": 0.3,
        "temperature_code": 0.1,
        "timeout": 180.0,
        "max_retries": 2,
    },
}


def list_script_models() -> List[str]:
    return [name for name, meta in MODEL_REGISTRY.items() if "script" in meta["roles"]]


def list_code_models() -> List[str]:
    return [name for name, meta in MODEL_REGISTRY.items() if "code" in meta["roles"]]


def list_image_models() -> List[str]:
    return [name for name, meta in MODEL_REGISTRY.items() if "image" in meta["roles"]]


def get_model_meta(model_name: str) -> Dict:
    if model_name not in MODEL_REGISTRY:
        available = ", ".join(MODEL_REGISTRY.keys())
        raise ValueError(f"未注册的模型: {model_name}\n可用模型: {available}")
    return MODEL_REGISTRY[model_name]


def get_model_display_name(model_name: str) -> str:
    meta = get_model_meta(model_name)
    return meta.get("display_name", model_name)


def list_script_display_names() -> List[str]:
    return [get_model_display_name(name) for name in list_script_models()]


def list_code_display_names() -> List[str]:
    return [get_model_display_name(name) for name in list_code_models()]


def build_llm_config(model_name: str, role: str) -> LLMConfig:
    meta = get_model_meta(model_name)

    if role not in meta["roles"]:
        raise ValueError(f"模型 {model_name} 不支持角色 {role}")

    api_key = os.getenv(meta["api_key_env"])
    temperature = meta["temperature_script"] if role == "script" else meta["temperature_code"]

    return LLMConfig(
        api_key=api_key,
        base_url=meta["base_url"],
        model=model_name,
        temperature=temperature,
        max_retries=meta["max_retries"],
        timeout=meta["timeout"],
    )


def get_script_model_name() -> str:
    return os.getenv("SCRIPT_MODEL", DEFAULT_SCRIPT_MODEL)


def get_code_model_name() -> str:
    return os.getenv("CODE_MODEL", DEFAULT_CODE_MODEL)


def get_image_model_name() -> str:
    return os.getenv("IMAGE_MODEL", "[官]gemini-3.1-flash-image-preview")


def build_script_config() -> LLMConfig:
    return build_llm_config(get_script_model_name(), "script")


def build_code_config() -> LLMConfig:
    return build_llm_config(get_code_model_name(), "code")
