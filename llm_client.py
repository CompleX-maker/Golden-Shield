import json
import time
import random
from typing import Optional, Callable
from pathlib import Path
import openai
from dataclasses import dataclass


@dataclass
class LLMConfig:
    api_key: str
    base_url: Optional[str] = None
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_retries: int = 3
    timeout: float = 120.0


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.client = openai.OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout
        )
        self.config = config
        self.fallback_models = []  # 你现在不想走自动降级
        self.debug_dir = Path("./output")
        self.debug_dir.mkdir(parents=True, exist_ok=True)

        print(f"LLMCLIENT_VERSION = DEBUG_SPLIT_V2 | model={self.config.model}")

    def _save_debug_text(self, filename: str, content: str):
        try:
            path = self.debug_dir / filename
            path.write_text(content or "", encoding="utf-8")
        except Exception as e:
            print(f"⚠️ 保存调试文件失败 {filename}: {e}")

    def _classify_non_json(self, text: str) -> str:
        t = (text or "").strip().lower()

        if not t:
            return "EMPTY_RESPONSE"

        if t.startswith("<!doctype html") or t.startswith("<html") or "<html" in t:
            return "HTML_RESPONSE"

        if "bad gateway" in t or "gateway" in t:
            return "GATEWAY_ERROR"

        if "upstream" in t or "proxy" in t:
            return "PROXY_ERROR"

        if t.startswith("error:") or t.startswith("error "):
            return "PLAIN_ERROR_TEXT"

        if t.startswith("data:"):
            return "SSE_STYLE_RESPONSE"

        if t.startswith("{") and not t.endswith("}"):
            return "TRUNCATED_JSON"

        return "NON_JSON_TEXT"

    def _extract_json_from_text(self, text: str, debug_prefix: str) -> dict:
        if text is None:
            self._save_debug_text(f"last_{debug_prefix}_raw_response.txt", "__NONE__")
            raise ValueError("LLM返回 content=None")

        text = str(text).strip()
        self._save_debug_text(f"last_{debug_prefix}_raw_response.txt", text)

        if not text:
            raise ValueError("LLM返回空内容")

        # 1. 直接整体解析
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except Exception:
            pass

        # 2. 从任意 { 开始找第一个合法 JSON 对象
        decoder = json.JSONDecoder()
        for i, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[i:])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue

        kind = self._classify_non_json(text)
        preview = text[:600].replace("\n", "\\n")
        raise ValueError(f"无法解析JSON [{kind}]，原始响应预览: {preview}")

    def _request_once(self, model: str, prompt: str, debug_prefix: str, timeout: Optional[float] = None) -> dict:
        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.temperature,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout

        # 先清一下上一次的原始响应，避免误判
        self._save_debug_text(f"last_{debug_prefix}_raw_response.txt", "")
        self._save_debug_text(f"last_{debug_prefix}_error.txt", "")

        try:
            response = self.client.chat.completions.create(
                **kwargs,
                response_format={"type": "json_object"}
            )
        except Exception:
            response = self.client.chat.completions.create(**kwargs)

        # 尽量把原始 response 先转出来
        content = None
        try:
            content = response.choices[0].message.content
        except Exception as e:
            self._save_debug_text(f"last_{debug_prefix}_raw_response.txt", "__NO_CONTENT_FIELD__")
            raise ValueError(f"无法读取 response.choices[0].message.content: {e}")

        return self._extract_json_from_text(content, debug_prefix)

    def generate(self, prompt: str, validator: Optional[Callable] = None, debug_prefix: str = "generic") -> dict:
        last_exception = None

        for attempt in range(self.config.max_retries):
            try:
                print(f"📡 请求模型: {self.config.model} (尝试 {attempt + 1}/{self.config.max_retries})")
                result = self._request_once(self.config.model, prompt, debug_prefix=debug_prefix)

                if not result or result == {}:
                    raise ValueError("LLM返回空JSON对象{}")

                if validator:
                    validated_result = validator(result)
                    if isinstance(validated_result, dict):
                        result = validated_result
                    else:
                        print("⚠️ Validator返回非字典，使用原始解析结果")

                return result

            except Exception as e:
                last_exception = e
                error_str = str(e).lower()
                self._save_debug_text(f"last_{debug_prefix}_error.txt", str(e))

                is_rate_limit = (
                    "429" in str(e)
                    or "rate limit" in error_str
                    or "too many requests" in error_str
                    or "limit" in error_str
                )
                is_timeout = "timeout" in error_str or "timed out" in error_str
                is_json_error = (
                    "无法解析json" in error_str
                    or "expecting value" in error_str
                    or "json" in error_str
                    or "content=none" in error_str
                )

                if is_rate_limit:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    print(f"⏳ 遇到限流(429)，等待{wait_time:.1f}秒后重试... (模型: {self.config.model})")
                    time.sleep(wait_time)
                elif is_timeout:
                    wait_time = 1.5 + random.uniform(0, 1)
                    print(f"⏳ 请求超时，等待{wait_time:.1f}秒后重试... (模型: {self.config.model})")
                    time.sleep(wait_time)
                elif is_json_error:
                    wait_time = 1.0 + random.uniform(0, 0.8)
                    print(f"⚠️ 返回内容不是合法JSON，等待{wait_time:.1f}秒后重试...")
                    print(f"   已保存原始响应到 output/last_{debug_prefix}_raw_response.txt")
                    time.sleep(wait_time)
                else:
                    wait_time = 0.8 + 0.6 * attempt
                    print(f"⚠️ 第{attempt + 1}次重试... (错误: {str(e)[:120]})")
                    time.sleep(wait_time)

        raise Exception(f"LLM生成失败（已尝试{self.config.max_retries}次）: {last_exception}")

    def generate_script(self, user_input: str) -> dict:
        from .validator import validate_script
        from .prompts import SCRIPT_GENERATOR_PROMPT

        prompt = SCRIPT_GENERATOR_PROMPT.replace("{USER_INPUT}", user_input)
        return self.generate(prompt, validator=validate_script, debug_prefix="script")

    def generate_code(self, script: dict) -> dict:
        from .prompts import CODE_GENERATOR_PROMPT

        ref_dir = Path(__file__).parent.parent / "assets" / "reference" / "tutorial" / "game"
        reference_code = ""

        if ref_dir.exists():
            parts = []
            for rpy_file in sorted(ref_dir.glob("*.rpy")):
                parts.append(f"\n\n=== {rpy_file.name} ===\n")
                parts.append(rpy_file.read_text(encoding="utf-8"))
            reference_code = "".join(parts)
        else:
            reference_code = "# 未找到参考项目，使用标准语法\n"

        script_json = json.dumps(script, ensure_ascii=False, indent=2)
        prompt = CODE_GENERATOR_PROMPT.replace("{REFERENCE_CODE}", reference_code).replace("{SCRIPT_JSON}", script_json)

        return self.generate(prompt, debug_prefix="code")
