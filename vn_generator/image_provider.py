import base64
import hashlib
from pathlib import Path
from typing import Optional, List

import requests


class ImageProvider:
    def __init__(self, gemai_api_key: Optional[str] = None, local_sd_base_url: Optional[str] = None):
        self.gemai_api_key = gemai_api_key
        self.local_sd_base_url = (local_sd_base_url or "http://127.0.0.1:7861").rstrip("/")

    # =========================
    # 公共工具
    # =========================
    def _post_json(self, url: str, payload: dict, timeout: int = 180):
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _get_json(self, url: str, timeout: int = 30):
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _decode_and_save_base64_image(self, image_b64: str, output_path: str) -> str:
        if "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1]

        image_bytes = base64.b64decode(image_b64)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "wb") as f:
            f.write(image_bytes)

        return output_path

    def _image_to_base64(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _stable_seed(self, text: str) -> int:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 2147483647

    # =========================
    # 本地 SD 连接/模型
    # =========================
    def test_local_sd_connection(self) -> dict:
        return self._get_json(f"{self.local_sd_base_url}/sdapi/v1/options", timeout=15)

    def list_local_sd_models(self) -> List[str]:
        data = self._get_json(f"{self.local_sd_base_url}/sdapi/v1/sd-models", timeout=20)
        models = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    title = item.get("title") or item.get("model_name") or item.get("name")
                    if title:
                        models.append(str(title))
        return models

    def _set_local_sd_checkpoint(self, model_name: str):
        if not model_name:
            return

        options_url = f"{self.local_sd_base_url}/sdapi/v1/options"
        current_options = self._get_json(options_url, timeout=30)

        current_checkpoint = current_options.get("sd_model_checkpoint", "")
        if current_checkpoint == model_name:
            return

        payload = {
            "sd_model_checkpoint": model_name
        }

        resp = requests.post(options_url, json=payload, timeout=120)
        resp.raise_for_status()

    # =========================
    # 对外方法：背景图
    # =========================
    def generate_background(
        self,
        prompt: str,
        output_path: str,
        provider: str = "local_sd",
        model_name: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> str:
        provider = (provider or "none").strip().lower()

        if provider == "none":
            return ""

        if provider == "local_sd":
            return self._generate_background_local_sd(
                prompt=prompt,
                output_path=output_path,
                model_name=model_name,
                seed=seed
            )

        if provider == "gemini":
            return self._generate_background_gemini(
                prompt=prompt,
                output_path=output_path,
                model_name=model_name
            )

        raise ValueError(f"未知图片提供方: {provider}")

    def _generate_background_local_sd(
        self,
        prompt: str,
        output_path: str,
        model_name: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> str:
        if model_name:
            self._set_local_sd_checkpoint(model_name)

        payload = {
            "prompt": prompt,
            "negative_prompt": (
                "low quality, blurry, distorted, bad anatomy, text, watermark, logo, "
                "cropped, duplicate, extra limbs, deformed, ugly, oversaturated, nsfw"
            ),
            "steps": 24,
            "width": 1280,
            "height": 720,
            "cfg_scale": 7,
            "sampler_name": "DPM++ 2M Karras",
            "batch_size": 1,
            "n_iter": 1,
            "seed": seed if seed is not None else -1
        }

        data = self._post_json(
            f"{self.local_sd_base_url}/sdapi/v1/txt2img",
            payload=payload,
            timeout=180
        )

        images = data.get("images") or []
        if not images:
            raise ValueError("本地 SD 未返回背景图")

        return self._decode_and_save_base64_image(images[0], output_path)

    # =========================
    # 对外方法：角色立绘基准图
    # =========================
    def generate_character_base(
        self,
        prompt: str,
        output_path: str,
        provider: str = "local_sd",
        model_name: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> str:
        provider = (provider or "none").strip().lower()

        if provider == "none":
            return ""

        if provider == "local_sd":
            return self._generate_character_base_local_sd(
                prompt=prompt,
                output_path=output_path,
                model_name=model_name,
                seed=seed
            )

        if provider == "gemini":
            raise NotImplementedError("Gemini 角色立绘生成暂未接入")

        raise ValueError(f"未知图片提供方: {provider}")

    def _generate_character_base_local_sd(
        self,
        prompt: str,
        output_path: str,
        model_name: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> str:
        if model_name:
            self._set_local_sd_checkpoint(model_name)

        payload = {
            "prompt": prompt,
            "negative_prompt": (
                "low quality, blurry, bad anatomy, extra fingers, extra arms, extra people, "
                "text, watermark, logo, cropped, duplicate face, different outfit, nsfw"
            ),
            "steps": 28,
            "width": 768,
            "height": 1024,
            "cfg_scale": 7,
            "sampler_name": "DPM++ 2M Karras",
            "batch_size": 1,
            "n_iter": 1,
            "seed": seed if seed is not None else -1
        }

        data = self._post_json(
            f"{self.local_sd_base_url}/sdapi/v1/txt2img",
            payload=payload,
            timeout=180
        )

        images = data.get("images") or []
        if not images:
            raise ValueError("本地 SD 未返回角色基准图")

        return self._decode_and_save_base64_image(images[0], output_path)

    # =========================
    # 对外方法：角色表情变体（img2img）
    # =========================
    def generate_character_expression(
        self,
        reference_image_path: str,
        prompt: str,
        output_path: str,
        provider: str = "local_sd",
        model_name: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> str:
        provider = (provider or "none").strip().lower()

        if provider == "none":
            return ""

        if provider == "local_sd":
            return self._generate_character_expression_local_sd(
                reference_image_path=reference_image_path,
                prompt=prompt,
                output_path=output_path,
                model_name=model_name,
                seed=seed
            )

        if provider == "gemini":
            raise NotImplementedError("Gemini 表情变体生成暂未接入")

        raise ValueError(f"未知图片提供方: {provider}")

    def _generate_character_expression_local_sd(
        self,
        reference_image_path: str,
        prompt: str,
        output_path: str,
        model_name: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> str:
        if not Path(reference_image_path).exists():
            raise FileNotFoundError(f"参考角色图不存在: {reference_image_path}")

        if model_name:
            self._set_local_sd_checkpoint(model_name)

        init_image_b64 = self._image_to_base64(reference_image_path)

        payload = {
            "init_images": [init_image_b64],
            "prompt": prompt,
            "negative_prompt": (
                "different person, different hairstyle, different clothes, extra people, "
                "text, watermark, logo, blurry, low quality, duplicate face, nsfw"
            ),
            "steps": 24,
            "width": 768,
            "height": 1024,
            "cfg_scale": 7,
            "sampler_name": "DPM++ 2M Karras",
            "denoising_strength": 0.28,
            "resize_mode": 0,
            "batch_size": 1,
            "n_iter": 1,
            "seed": seed if seed is not None else -1
        }

        data = self._post_json(
            f"{self.local_sd_base_url}/sdapi/v1/img2img",
            payload=payload,
            timeout=180
        )

        images = data.get("images") or []
        if not images:
            raise ValueError("本地 SD 未返回角色表情图")

        return self._decode_and_save_base64_image(images[0], output_path)

    # =========================
    # Gemini 占位
    # =========================
    def _generate_background_gemini(
        self,
        prompt: str,
        output_path: str,
        model_name: Optional[str] = None
    ) -> str:
        model_name = model_name or "[官]gemini-3.1-flash-image-preview"

        if not self.gemai_api_key:
            raise ValueError("GEMAI_API_KEY 未配置，无法使用 Gemini 图片生成")

        raise NotImplementedError(
            f"Gemini 图片生成骨架已预留，当前尚未接入具体返回解析逻辑。模型={model_name}"
        )
