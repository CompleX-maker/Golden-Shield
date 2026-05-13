import base64
import hashlib
from pathlib import Path
from typing import Optional, List

import requests
from PIL import Image


class ImageProvider:
    def __init__(self, gemai_api_key: Optional[str] = None, local_sd_base_url: Optional[str] = None):
        self.gemai_api_key = gemai_api_key
        self.local_sd_base_url = (local_sd_base_url or "http://127.0.0.1:7861").rstrip("/")
        self.gemai_base_url = "https://api.gemai.cc/v1"

    # =========================
    # 公共工具
    # =========================
    def _post_json(self, url: str, payload: dict, timeout: int = 180, headers: Optional[dict] = None):
        resp = requests.post(url, json=payload, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def _get_json(self, url: str, timeout: int = 30, headers: Optional[dict] = None):
        resp = requests.get(url, timeout=timeout, headers=headers)
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

    def _download_and_save_image(self, image_url: str, output_path: str) -> str:
        resp = requests.get(image_url, timeout=180)
        resp.raise_for_status()

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(resp.content)

        return output_path

    def _image_to_base64(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _stable_seed(self, text: str) -> int:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 2147483647

    def _force_png_rgba(self, output_path: str) -> str:
        path = Path(output_path)
        if not path.exists():
            return output_path

        try:
            with Image.open(path) as img:
                img = img.convert("RGBA")
                img.save(path, format="PNG")
        except Exception as e:
            print(f"⚠️ RGBA 转换失败: {output_path} -> {e}")

        return output_path

    def _remove_background_for_character(self, output_path: str) -> str:
        """
        透明抠图：
        - 如果本地已有 u2net 模型，就用 rembg
        - 如果没有模型，则跳过，不再反复联网下载
        """
        path = Path(output_path)
        if not path.exists():
            return output_path

        model_path = Path.home() / ".u2net" / "u2net.onnx"
        if not model_path.exists():
            print(f"⚠️ rembg 模型不存在，跳过透明抠图: {model_path}")
            return self._force_png_rgba(output_path)

        try:
            from rembg import remove

            raw = path.read_bytes()
            result = remove(raw)
            path.write_bytes(result)

            with Image.open(path) as img:
                img = img.convert("RGBA")
                img.save(path, format="PNG")
        except ImportError:
            print("⚠️ 未安装 rembg，跳过自动透明抠图。可执行: pip install rembg onnxruntime")
            self._force_png_rgba(output_path)
        except Exception as e:
            print(f"⚠️ 自动透明抠图失败，保留原图: {output_path} -> {e}")
            self._force_png_rgba(output_path)

        return output_path

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

        if provider in {"gemini", "remote_api"}:
            return self._generate_background_remote_api(
                prompt=prompt,
                output_path=output_path,
                model_name=model_name or "[官]gemini-3.1-flash-image-preview"
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
                "cropped, duplicate, extra limbs, deformed, ugly, oversaturated, nsfw, "
                "person, people, human, character"
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

    def _generate_background_remote_api(
        self,
        prompt: str,
        output_path: str,
        model_name: str
    ) -> str:
        if not self.gemai_api_key:
            raise ValueError("GEMAI_API_KEY 未配置，无法使用远程图片生成")

        headers = {
            "Authorization": f"Bearer {self.gemai_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model_name,
            "prompt": prompt,
            "size": "1280x720"
        }

        try:
            data = self._post_json(
                f"{self.gemai_base_url}/images/generations",
                payload=payload,
                timeout=180,
                headers=headers
            )
        except Exception as e:
            raise ValueError(f"远程图片接口调用失败（/images/generations）: {e}")

        result_list = data.get("data") or []
        if not result_list:
            raise ValueError(f"远程图片接口未返回 data 字段: {data}")

        first = result_list[0]
        if isinstance(first, dict):
            if first.get("b64_json"):
                return self._decode_and_save_base64_image(first["b64_json"], output_path)
            if first.get("url"):
                return self._download_and_save_image(first["url"], output_path)

        raise ValueError(f"远程图片接口返回格式暂不支持: {first}")

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

        if provider in {"gemini", "remote_api"}:
            saved_path = self._generate_background_remote_api(
                prompt=prompt,
                output_path=output_path,
                model_name=model_name or "[官]gemini-3.1-flash-image-preview"
            )
            return self._remove_background_for_character(saved_path)

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
                "low quality, blurry, bad anatomy, extra fingers, extra arms, extra legs, "
                "extra people, multiple people, group, crowd, two people, three people, "
                "multiple heads, two heads, extra head, duplicate head, head duplication, "
                "extra face, duplicate face, face duplication, "
                "text, watermark, logo, cropped, close-up, face close-up, portrait crop, "
                "head cut off, cropped head, cropped face, "
                "different outfit, child, loli, toddler, baby, old man, elderly man, "
                "male if female, female if male, realistic photo background, complex background, "
                "white background block, solid white backdrop, nsfw"
            ),
            "steps": 30,
            "width": 768,
            "height": 1024,
            "cfg_scale": 8,
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

        saved_path = self._decode_and_save_base64_image(images[0], output_path)
        return self._remove_background_for_character(saved_path)

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

        if provider in {"gemini", "remote_api"}:
            saved_path = self._generate_background_remote_api(
                prompt=prompt,
                output_path=output_path,
                model_name=model_name or "[官]gemini-3.1-flash-image-preview"
            )
            return self._remove_background_for_character(saved_path)

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
                "different person, different face, different hairstyle, different hair color, "
                "different clothes, different outfit, different accessories, "
                "extra people, multiple people, group, crowd, second person, "
                "multiple heads, two heads, extra head, duplicate head, head duplication, "
                "extra face, duplicate face, face duplication, "
                "text, watermark, logo, blurry, low quality, "
                "close-up, face close-up, portrait crop, "
                "head cut off, cropped head, cropped face, "
                "age changed, younger, child, loli, toddler, baby, old man, elderly man, "
                "male if female, female if male, white background block, solid white backdrop, nsfw"
            ),
            "steps": 24,
            "width": 768,
            "height": 1024,
            "cfg_scale": 8,
            "sampler_name": "DPM++ 2M Karras",
            "denoising_strength": 0.22,
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

        saved_path = self._decode_and_save_base64_image(images[0], output_path)
        return self._remove_background_for_character(saved_path)
