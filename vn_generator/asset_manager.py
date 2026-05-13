import json
import hashlib
from pathlib import Path
from typing import Dict, Any

from .image_provider import ImageProvider
from .models import Script, Character, Background


class AssetManager:
    def __init__(self, image_provider: ImageProvider):
        self.image_provider = image_provider

    # =========================
    # 工具
    # =========================
    def _stable_seed(self, text: str) -> int:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 2147483647

    def _safe_tone(self, script: Script) -> str:
        metadata = script.metadata or {}
        tone = str(metadata.get("tone") or "neutral")
        genre = str(metadata.get("genre") or "visual novel")
        return f"{genre}, {tone}"

    def _build_background_prompt(self, bg: Background, script: Script) -> str:
        tone = self._safe_tone(script)
        return (
            f"{bg.description}, "
            f"visual novel background, {tone}, wide cinematic scene, high detail, "
            f"story atmosphere, environmental storytelling, anime-realistic style, "
            f"clean composition, no subtitles, no watermark, no UI, no text, no people"
        )

    def _build_character_base_prompt(self, char: Character, script: Script) -> str:
        """
        调整为更适合 VN 的半身立绘：
        - 不要只剩腿
        - 不要大头近景
        - 不要全身构图过低
        - 要求单人单头单脸
        """
        tone = self._safe_tone(script)
        expr = char.default_expression or "neutral"

        return (
            f"masterpiece, best quality, visual novel character sprite, "
            f"single character, one person only, solo, one head only, single face, "
            f"waist-up portrait, half body, upper body visible, clear face, "
            f"front view, natural standing pose, "
            f"leave enough margin around the character, not close-up, not face close-up, "
            f"not full body, not cropped head, not cropped face, "
            f"plain clean background, simple background, transparent background style, "
            f"no text, no watermark, no subtitles, no scene background, "
            f"character name: {char.name}, "
            f"character design: {char.description}, "
            f"fixed identity, fixed face, fixed age, fixed gender presentation, "
            f"fixed hairstyle, fixed hair color, fixed outfit, fixed accessories, "
            f"{expr} expression, "
            f"{tone}, anime style, game sprite"
        )

    def _build_character_expression_prompt(self, char: Character, expression: str, script: Script) -> str:
        tone = self._safe_tone(script)
        return (
            f"same character as reference image, same person, same identity, "
            f"same face, same age, same gender presentation, same hairstyle, same hair color, "
            f"same outfit, same accessories, "
            f"only change facial expression to {expression}, "
            f"single character, one person only, solo, one head only, single face, "
            f"waist-up portrait, half body, upper body visible, clear face, "
            f"front view, natural standing pose, "
            f"leave enough margin around the character, not close-up, not face close-up, "
            f"not full body, not cropped head, not cropped face, "
            f"visual novel character sprite, "
            f"plain clean background, simple background, transparent background style, "
            f"no extra people, no text, no watermark, no subtitles, no scene background, "
            f"character design: {char.description}, "
            f"{tone}, anime style, game sprite"
        )

    # =========================
    # 背景图
    # =========================
    def build_backgrounds(
        self,
        script: Script,
        game_dir: str,
        image_enabled: bool = False,
        image_provider_name: str = "none",
        image_model_name: str = "",
        overwrite_existing: bool = True,
    ) -> Dict[str, Any]:
        result = {
            "generated": [],
            "failed": [],
            "skipped": [],
            "details": []
        }

        if not image_enabled or image_provider_name == "none":
            print("  - 背景图生成已关闭")
            return result

        bg_dir = Path(game_dir) / "images" / "bg"
        bg_dir.mkdir(parents=True, exist_ok=True)

        print(f"  - 背景总数: {len(script.backgrounds)}")
        print(f"  - 背景输出目录: {bg_dir}")

        for bg in script.backgrounds:
            output_path = bg_dir / f"{bg.id}.png"

            if output_path.exists() and not overwrite_existing:
                msg = f"[背景][跳过] {bg.id} -> {output_path}"
                print(f"  {msg}")
                result["skipped"].append(str(output_path))
                result["details"].append(msg)
                continue

            prompt = self._build_background_prompt(bg, script)
            seed = self._stable_seed(f"bg:{bg.id}")

            print(f"  [背景][开始] {bg.id}")
            print(f"    路径: {output_path}")
            print(f"    Seed: {seed}")
            print(f"    Prompt: {prompt[:180]}{'...' if len(prompt) > 180 else ''}")

            try:
                self.image_provider.generate_background(
                    prompt=prompt,
                    output_path=str(output_path),
                    provider=image_provider_name,
                    model_name=image_model_name,
                    seed=seed
                )
                msg = f"[背景][成功] {bg.id} -> {output_path}"
                print(f"  {msg}")
                result["generated"].append(str(output_path))
                result["details"].append(msg)
            except Exception as e:
                msg = f"[背景][失败] {bg.id} -> {e}"
                print(f"  {msg}")
                result["failed"].append({
                    "background_id": bg.id,
                    "path": str(output_path),
                    "error": str(e)
                })
                result["details"].append(msg)

        return result

    # =========================
    # 角色立绘
    # =========================
    def build_characters(
        self,
        script: Script,
        game_dir: str,
        image_enabled: bool = False,
        image_provider_name: str = "none",
        image_model_name: str = "",
        overwrite_existing: bool = True,
    ) -> Dict[str, Any]:
        result = {
            "generated": [],
            "failed": [],
            "skipped": [],
            "details": []
        }

        if not image_enabled or image_provider_name == "none":
            print("  - 角色立绘生成已关闭")
            return result

        chars_dir = Path(game_dir) / "images" / "characters"
        chars_dir.mkdir(parents=True, exist_ok=True)

        print(f"  - 角色总数: {len(script.characters)}")
        print(f"  - 角色输出目录: {chars_dir}")

        for char in script.characters:
            try:
                char_dir = chars_dir / char.id
                char_dir.mkdir(parents=True, exist_ok=True)

                expressions = char.expressions if char.expressions else ["neutral"]
                default_expr = char.default_expression or "neutral"
                if default_expr not in expressions:
                    expressions = [default_expr] + [x for x in expressions if x != default_expr]

                base_seed = self._stable_seed(f"char:{char.id}")
                base_path = char_dir / f"{default_expr}.png"

                print(f"  [角色][开始] {char.id} / {char.name}")
                print(f"    默认表情: {default_expr}")
                print(f"    表情列表: {expressions}")
                print(f"    Seed: {base_seed}")

                if not base_path.exists() or overwrite_existing:
                    base_prompt = self._build_character_base_prompt(char, script)
                    print(f"    [基准图][开始] {base_path}")
                    print(f"    [基准图][Prompt] {base_prompt[:240]}{'...' if len(base_prompt) > 240 else ''}")

                    self.image_provider.generate_character_base(
                        prompt=base_prompt,
                        output_path=str(base_path),
                        provider=image_provider_name,
                        model_name=image_model_name,
                        seed=base_seed
                    )
                    msg = f"[角色][基准图][成功] {char.id}/{default_expr} -> {base_path}"
                    print(f"    {msg}")
                    result["generated"].append(str(base_path))
                    result["details"].append(msg)
                else:
                    msg = f"[角色][基准图][跳过] {char.id}/{default_expr} -> {base_path}"
                    print(f"    {msg}")
                    result["skipped"].append(str(base_path))
                    result["details"].append(msg)

                for expr in expressions:
                    expr_path = char_dir / f"{expr}.png"

                    if expr == default_expr:
                        continue

                    if expr_path.exists() and not overwrite_existing:
                        msg = f"[角色][表情][跳过] {char.id}/{expr} -> {expr_path}"
                        print(f"    {msg}")
                        result["skipped"].append(str(expr_path))
                        result["details"].append(msg)
                        continue

                    expr_prompt = self._build_character_expression_prompt(char, expr, script)
                    print(f"    [表情图][开始] {char.id}/{expr}")
                    print(f"    [表情图][路径] {expr_path}")
                    print(f"    [表情图][Prompt] {expr_prompt[:240]}{'...' if len(expr_prompt) > 240 else ''}")

                    self.image_provider.generate_character_expression(
                        reference_image_path=str(base_path),
                        prompt=expr_prompt,
                        output_path=str(expr_path),
                        provider=image_provider_name,
                        model_name=image_model_name,
                        seed=base_seed
                    )
                    msg = f"[角色][表情][成功] {char.id}/{expr} -> {expr_path}"
                    print(f"    {msg}")
                    result["generated"].append(str(expr_path))
                    result["details"].append(msg)

                meta = {
                    "character_id": char.id,
                    "character_name": char.name,
                    "default_expression": default_expr,
                    "expressions": expressions,
                    "seed": base_seed,
                    "model_name": image_model_name,
                    "provider": image_provider_name,
                }
                (char_dir / "_meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )

            except Exception as e:
                msg = f"[角色][失败] {char.id} -> {e}"
                print(f"  {msg}")
                result["failed"].append({
                    "character_id": char.id,
                    "error": str(e)
                })
                result["details"].append(msg)

        return result
