import json
import re
import difflib
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from .llm_client import LLMClient, LLMConfig
from .validator import validate_script
from .renpy_builder import RenpyBuilder
from .models import Script, RenpyFile, GenerationResult
from .image_provider import ImageProvider
from .asset_manager import AssetManager


class VNGenerator:
    def __init__(self,
                 script_llm_config: LLMConfig,
                 code_llm_config: Optional[LLMConfig] = None):
        self.script_client = LLMClient(script_llm_config)
        self.code_client = LLMClient(code_llm_config or script_llm_config)

    def generate(
        self,
        user_input: str,
        output_base_path: str = "./output",
        font_name: str = "auto",
        image_enabled: bool = False,
        image_provider_name: str = "none",
        image_model_name: str = "",
        local_sd_base_url: str = "http://127.0.0.1:7861",
    ) -> GenerationResult:
        print("🎬 阶段1: 生成剧本...")
        try:
            script_data = self.script_client.generate_script(user_input)
        except Exception as e:
            print(f"❌ 剧本生成失败: {e}")
            script_data = {
                "title": "生成失败-默认剧本",
                "metadata": {"genre": "error", "tone": "neutral"},
                "characters": [{"id": "narrator", "name": "旁白", "description": "旁白", "expressions": ["neutral"]}],
                "backgrounds": [{"id": "black", "description": "黑屏"}],
                "scenes": [{
                    "id": "error_scene",
                    "title": "错误",
                    "background": "black",
                    "sequences": [{"type": "narration", "text": "剧本生成失败，请重试。"}]
                }]
            }

        script_data = validate_script(script_data)

        if not script_data or not isinstance(script_data, dict):
            raise ValueError("剧本数据验证后仍为空")

        required_fields = ["title", "characters", "scenes"]
        missing = [f for f in required_fields if f not in script_data or not script_data[f]]
        if missing:
            raise ValueError(f"剧本缺少必要字段: {missing}")

        script = Script(**script_data)

        total_sequences = sum(len(scene.sequences) for scene in script.scenes)
        if total_sequences < 10:
            print(f"⚠️ 警告：剧本总序列较少，仅 {total_sequences} 个，可能内容偏短")

        print(f"  ✓ 标题: {script.title}")
        print(f"  ✓ 角色: {len(script.characters)}个")
        print(f"  ✓ 场景: {len(script.scenes)}个")
        print(f"  ✓ 总序列: {total_sequences}个")

        safe_title = "".join(c for c in script.title if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = safe_title.replace(' ', '_')
        output_path = f"{output_base_path}/{safe_title or 'VisualNovel'}"

        print("\n💻 阶段2: 生成Ren'Py代码...")
        code_data = None
        files = []
        normalized_assets_needed = []

        try:
            raw_code_data = self.code_client.generate_code(script_data)
            code_data = self._normalize_code_result(raw_code_data)

            files = [RenpyFile(**f) for f in code_data["files"]]
            files = self._normalize_file_paths(files)
            files = self._sanitize_generated_files(files, script)
            files = self._reconcile_labels_and_targets(files, script)
            self._validate_generated_files(files)

            normalized_assets_needed = self._normalize_assets_needed(
                code_data.get("assets_needed", [])
            )

            print(f"  ✓ 生成文件: {len(files)}个")
            print(f"  ✓ 资源需求: {len(normalized_assets_needed)}项")

        except Exception as e:
            print(f"⚠️ 代码生成失败: {e}，使用最小化默认代码")
            if code_data is not None:
                self._save_debug_code_response(code_data, output_base_path)

            files = self._generate_fallback_code(script)
            normalized_assets_needed = []

        print(f"\n📦 阶段3: 构建项目 (字体: {font_name})...")
        builder = RenpyBuilder(None, output_path)
        project_path = builder.create_project(files, script, font_name=font_name)
        print(f"  ✓ 项目路径: {project_path}")

        image_report_data = {
            "enabled": image_enabled,
            "provider": image_provider_name,
            "model": image_model_name,
            "local_sd_base_url": local_sd_base_url,
            "backgrounds": {"generated": [], "failed": [], "skipped": [], "details": []},
            "characters": {"generated": [], "failed": [], "skipped": [], "details": []},
        }

        # ===== 图片生成：背景图 + 角色立绘 =====
        if image_enabled and image_provider_name != "none":
            print(f"\n🖼️ 阶段4: 生成图片资源 ({image_provider_name})...")
            game_dir = Path(output_path) / "game"

            image_provider = ImageProvider(
                gemai_api_key=self.script_client.config.api_key,
                local_sd_base_url=local_sd_base_url
            )

            if image_provider_name == "local_sd":
                try:
                    info = image_provider.test_local_sd_connection()
                    print("  ✓ 本地 SD 连接成功")
                    current_model = info.get("sd_model_checkpoint", "")
                    if current_model:
                        print(f"  ✓ 当前本地 SD 模型: {current_model}")
                except Exception as e:
                    print(f"  ⚠️ 本地 SD 连接失败: {e}")
                    raise

            asset_manager = AssetManager(image_provider)

            bg_result = asset_manager.build_backgrounds(
                script=script,
                game_dir=str(game_dir),
                image_enabled=image_enabled,
                image_provider_name=image_provider_name,
                image_model_name=image_model_name,
                overwrite_existing=True
            )
            image_report_data["backgrounds"] = bg_result

            print(f"  ✓ 背景生成成功: {len(bg_result['generated'])}个")
            if bg_result["skipped"]:
                print(f"  - 背景跳过: {len(bg_result['skipped'])}个")
            if bg_result["failed"]:
                print(f"  ⚠️ 背景生成失败: {len(bg_result['failed'])}个")
                for item in bg_result["failed"][:5]:
                    print(f"    - {item.get('background_id')}: {item.get('error')}")

            char_result = asset_manager.build_characters(
                script=script,
                game_dir=str(game_dir),
                image_enabled=image_enabled,
                image_provider_name=image_provider_name,
                image_model_name=image_model_name,
                overwrite_existing=True
            )
            image_report_data["characters"] = char_result

            print(f"  ✓ 角色立绘生成成功: {len(char_result['generated'])}个")
            if char_result["skipped"]:
                print(f"  - 角色立绘跳过: {len(char_result['skipped'])}个")
            if char_result["failed"]:
                print(f"  ⚠️ 角色立绘生成失败: {len(char_result['failed'])}个")
                for item in char_result["failed"][:5]:
                    print(f"    - {item.get('character_id')}: {item.get('error')}")

        self._write_image_generation_report(
            output_path=output_path,
            script=script,
            image_report_data=image_report_data
        )

        self._save_intermediate(
            script_data,
            code_data if code_data else {
                "files": [f.model_dump() for f in files],
                "assets_needed": normalized_assets_needed
            },
            output_base_path
        )

        try:
            report_json_path = Path(output_path) / "image_generation_report.json"
            report_json_path.write_text(
                json.dumps(self._build_image_report_json(image_report_data), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"📄 图片生成JSON报告已保存: {report_json_path}")
        except Exception as e:
            print(f"⚠️ 写入图片生成JSON报告失败: {e}")

        return GenerationResult(
            script=script,
            files=files,
            assets_needed=normalized_assets_needed,
            output_path=output_path
        )

    def _write_image_generation_report(self, output_path: str, script: Script, image_report_data: dict):
        try:
            report_path = Path(output_path) / "image_generation_report.txt"
            lines = [
                "图片生成报告",
                "=" * 60,
                f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"作品标题: {script.title}",
                f"图片启用: {image_report_data.get('enabled')}",
                f"图片提供方: {image_report_data.get('provider')}",
                f"图片模型: {image_report_data.get('model')}",
                f"Local SD 地址: {image_report_data.get('local_sd_base_url')}",
                "",
            ]

            bg = image_report_data.get("backgrounds", {})
            ch = image_report_data.get("characters", {})

            lines.extend([
                "[背景图汇总]",
                f"成功: {len(bg.get('generated', []))}",
                f"失败: {len(bg.get('failed', []))}",
                f"跳过: {len(bg.get('skipped', []))}",
                "",
                "[角色图汇总]",
                f"成功: {len(ch.get('generated', []))}",
                f"失败: {len(ch.get('failed', []))}",
                f"跳过: {len(ch.get('skipped', []))}",
                "",
                "[背景图详细记录]",
            ])

            for item in bg.get("details", []):
                lines.append(str(item))

            if bg.get("failed"):
                lines.append("")
                lines.append("[背景图失败详情]")
                for item in bg["failed"]:
                    lines.append(
                        f"- {item.get('background_id')} | path={item.get('path')} | error={item.get('error')}"
                    )

            lines.extend([
                "",
                "[角色图详细记录]",
            ])

            for item in ch.get("details", []):
                lines.append(str(item))

            if ch.get("failed"):
                lines.append("")
                lines.append("[角色图失败详情]")
                for item in ch["failed"]:
                    lines.append(
                        f"- {item.get('character_id')} | error={item.get('error')}"
                    )

            report_path.write_text("\n".join(lines), encoding="utf-8")
            print(f"📄 图片生成报告已保存: {report_path}")
        except Exception as e:
            print(f"⚠️ 写入图片生成报告失败: {e}")

    def _build_image_report_json(self, image_report_data: dict) -> dict:
        return {
            "enabled": image_report_data.get("enabled"),
            "provider": image_report_data.get("provider"),
            "model": image_report_data.get("model"),
            "local_sd_base_url": image_report_data.get("local_sd_base_url"),
            "backgrounds": image_report_data.get("backgrounds", {}),
            "characters": image_report_data.get("characters", {}),
        }

    # ===== 以下保留你当前已有逻辑 =====

    def _sanitize_color(self, color: Any) -> Optional[str]:
        if color is None:
            return None
        s = str(color).strip()
        if not s:
            return None
        if not s.startswith("#"):
            s = "#" + s
        hex_part = s[1:]
        if re.fullmatch(r'[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}', hex_part):
            return "#" + hex_part.upper()
        return None

    def _escape_renpy_text(self, text: str) -> str:
        if text is None:
            return ""
        text = str(text)
        text = text.replace("\\", "\\\\")
        text = text.replace('"', '\\"')
        text = text.replace("\r\n", "\\n").replace("\n", "\\n")
        return text

    def _normalize_key(self, s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', str(s).lower())

    def _normalize_code_result(self, raw: Any) -> dict:
        if not isinstance(raw, dict):
            raise ValueError(f"代码结果不是对象: {type(raw).__name__}")

        if "files" in raw and isinstance(raw["files"], list):
            return {"files": raw["files"], "assets_needed": raw.get("assets_needed", [])}

        output = raw.get("output")
        if isinstance(output, dict) and "files" in output and isinstance(output["files"], list):
            return {"files": output["files"], "assets_needed": output.get("assets_needed", raw.get("assets_needed", []))}

        data = raw.get("data")
        if isinstance(data, dict) and "files" in data and isinstance(data["files"], list):
            return {"files": data["files"], "assets_needed": data.get("assets_needed", raw.get("assets_needed", []))}

        for alt_key in ["rpy_files", "renpy_files", "generated_files", "file_list"]:
            if alt_key in raw and isinstance(raw[alt_key], list):
                return {"files": raw[alt_key], "assets_needed": raw.get("assets_needed", [])}

        if "path" in raw and "content" in raw:
            return {"files": [{"path": raw["path"], "content": raw["content"]}], "assets_needed": raw.get("assets_needed", [])}

        if isinstance(raw.get("result"), list):
            result = raw["result"]
            if result and isinstance(result[0], dict) and "path" in result[0] and "content" in result[0]:
                return {"files": result, "assets_needed": raw.get("assets_needed", [])}

        for key, value in raw.items():
            if isinstance(value, dict) and "files" in value and isinstance(value["files"], list):
                return {"files": value["files"], "assets_needed": value.get("assets_needed", raw.get("assets_needed", []))}

        preview = json.dumps(raw, ensure_ascii=False, indent=2)[:1500]
        raise ValueError(f"代码模型返回缺少 files 字段，原始结构预览:\n{preview}")

    def _normalize_file_paths(self, files: list[RenpyFile]) -> list[RenpyFile]:
        normalized = []
        for f in files:
            path = f.path.replace("\\", "/").strip()

            if path.startswith("game/"):
                path = path[5:]

            filename = Path(path).name
            if path.endswith(".rpy") and "/" not in path:
                if filename not in {"script.rpy", "characters.rpy", "gui.rpy", "screens.rpy", "options.rpy"}:
                    path = f"scenes/{filename}"

            if path.startswith("./"):
                path = path[2:]
                filename = Path(path).name
                if "/" not in path and filename not in {"script.rpy", "characters.rpy", "gui.rpy", "screens.rpy", "options.rpy"}:
                    path = f"scenes/{filename}"

            normalized.append(RenpyFile(path=path, content=f.content))
        return normalized

    def _script_file_labels(self, content: str) -> list[str]:
        return re.findall(r'^\s*label\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:', content, flags=re.MULTILINE)

    def _script_file_called_labels(self, content: str) -> list[str]:
        return re.findall(r'^\s*call\s+([a-zA-Z_][a-zA-Z0-9_]*)', content, flags=re.MULTILINE)

    def _validate_single_file_mode(self, files: list[RenpyFile]) -> bool:
        file_map = {f.path: f.content for f in files}
        if "script.rpy" not in file_map:
            return False
        if any(p.startswith("scenes/") and p.endswith(".rpy") for p in file_map.keys()):
            return False
        script_content = file_map["script.rpy"]
        labels = self._script_file_labels(script_content)
        if "start" not in labels:
            return False
        non_start_labels = [x for x in labels if x != "start"]
        if not non_start_labels:
            return False
        called = self._script_file_called_labels(script_content)
        if called:
            missing = [x for x in called if x not in labels]
            if missing:
                return False
        return True

    def _find_best_character_id(self, raw_name: str, valid_ids: list[str]) -> Optional[str]:
        if raw_name in valid_ids:
            return raw_name
        normalized_target = self._normalize_key(raw_name)
        if not normalized_target:
            return None
        normalized_map = {self._normalize_key(cid): cid for cid in valid_ids}
        if normalized_target in normalized_map:
            return normalized_map[normalized_target]
        for norm_cid, cid in normalized_map.items():
            if normalized_target in norm_cid or norm_cid in normalized_target:
                return cid
        close = difflib.get_close_matches(normalized_target, list(normalized_map.keys()), n=1, cutoff=0.72)
        if close:
            return normalized_map[close[0]]
        return None

    def _fix_say_attribute_syntax(self, line: str, valid_ids: list[str]) -> list[str]:
        pattern = r'^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s+)([a-zA-Z_][a-zA-Z0-9_]*)(\s+)\"(.*)\"(\s*)$'
        m = re.match(pattern, line)
        if not m:
            return [line]

        indent, raw_char, _, expr, _, text_body, tail = m.groups()
        best_char = self._find_best_character_id(raw_char, valid_ids)
        if not best_char:
            return [line]

        reserved = {"scene", "show", "hide", "jump", "call", "return", "menu", "with", "play", "stop"}
        if raw_char in reserved:
            return [line]

        text_body = text_body.replace('\\"', '__ESCAPED_QUOTE__')
        text_body = text_body.replace('"', '\\"')
        text_body = text_body.replace('__ESCAPED_QUOTE__', '\\"')

        show_line = f"{indent}show {best_char} {expr} at center"
        say_line = f'{indent}{best_char} "{text_body}"{tail}'
        return [show_line, say_line]

    def _escape_inner_quotes_in_renpy_line(self, line: str) -> str:
        m_narr = re.match(r'^(\s*)\"(.+)\"(\s*)$', line)
        if m_narr:
            indent, body, tail = m_narr.groups()
            body = body.replace('\\"', '__ESCAPED_QUOTE__')
            body = body.replace('"', '\\"')
            body = body.replace('__ESCAPED_QUOTE__', '\\"')
            return f'{indent}"{body}"{tail}'

        m_dialogue = re.match(r'^(\s*[a-zA-Z_][a-zA-Z0-9_]*\s+)\"(.+)\"(\s*)$', line)
        if m_dialogue:
            prefix, body, tail = m_dialogue.groups()
            body = body.replace('\\"', '__ESCAPED_QUOTE__')
            body = body.replace('"', '\\"')
            body = body.replace('__ESCAPED_QUOTE__', '\\"')
            return f'{prefix}"{body}"{tail}'

        return line

    def _rewrite_scene_character_names(self, content: str, script: Script) -> str:
        valid_ids = [c.id for c in script.characters]
        if not valid_ids:
            return content

        content = re.sub(r'^\s*\"type:\s*narration,\s*text:\s*(.*?)\"\s*$', r'    "\1"', content, flags=re.MULTILINE)
        content = re.sub(r'^\s*\"type:\s*narration\"\s*$', '', content, flags=re.MULTILINE)

        lines = content.splitlines()
        rewritten = []

        for line in lines:
            m_show = re.match(r'^(\s*show\s+)([a-zA-Z_][a-zA-Z0-9_]*)(.*)$', line)
            if m_show:
                prefix, raw_char, suffix = m_show.groups()
                best = self._find_best_character_id(raw_char, valid_ids)
                if best:
                    line = f"{prefix}{best}{suffix}"

            m_hide = re.match(r'^(\s*hide\s+)([a-zA-Z_][a-zA-Z0-9_]*)(.*)$', line)
            if m_hide:
                prefix, raw_char, suffix = m_hide.groups()
                best = self._find_best_character_id(raw_char, valid_ids)
                if best:
                    line = f"{prefix}{best}{suffix}"

            fixed_lines = self._fix_say_attribute_syntax(line, valid_ids)

            for fixed_line in fixed_lines:
                m_say = re.match(r'^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s+)(\".*)$', fixed_line)
                if m_say:
                    indent, raw_char, space, rest = m_say.groups()
                    reserved = {"scene", "show", "hide", "jump", "call", "return", "menu", "with", "play", "stop"}
                    if raw_char not in reserved:
                        best = self._find_best_character_id(raw_char, valid_ids)
                        if best:
                            fixed_line = f"{indent}{best}{space}{rest}"

                fixed_line = self._escape_inner_quotes_in_renpy_line(fixed_line)
                rewritten.append(fixed_line)

        return "\n".join([ln for ln in rewritten if ln.strip() != ""])

    def _sanitize_generated_files(self, files: list[RenpyFile], script: Script) -> list[RenpyFile]:
        sanitized = []

        for f in files:
            content = f.content.replace("\r\n", "\n")
            content = content.replace("“", '"').replace("”", '"')
            content = content.replace("‘", "'").replace("’", "'")

            if f.path.endswith(".rpy"):
                content = self._rewrite_scene_character_names(content, script)

            content = "\n".join(self._escape_inner_quotes_in_renpy_line(line) for line in content.splitlines())
            sanitized.append(RenpyFile(path=f.path, content=content))

        return sanitized

    def _collect_all_labels(self, files: list[RenpyFile]) -> set[str]:
        labels = set()
        for f in files:
            if f.path.endswith(".rpy"):
                found = re.findall(r'^\s*label\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:', f.content, flags=re.MULTILINE)
                labels.update(found)
        return labels

    def _find_best_label(self, target: str, labels: set[str]) -> Optional[str]:
        if target in labels:
            return target
        normalized_target = self._normalize_key(target)
        normalized_map = {self._normalize_key(label): label for label in labels}
        if normalized_target in normalized_map:
            return normalized_map[normalized_target]
        for norm_label, label in normalized_map.items():
            if normalized_target in norm_label or norm_label in normalized_target:
                return label
        close = difflib.get_close_matches(normalized_target, list(normalized_map.keys()), n=1, cutoff=0.72)
        if close:
            return normalized_map[close[0]]
        return None

    def _rewrite_jump_and_call_targets(self, content: str, labels: set[str]) -> str:
        def repl_jump(match):
            prefix, target = match.groups()
            fixed = self._find_best_label(target, labels)
            return f"{prefix}{fixed or target}"

        def repl_call(match):
            prefix, target = match.groups()
            fixed = self._find_best_label(target, labels)
            return f"{prefix}{fixed or target}"

        content = re.sub(r'^(\s*jump\s+)([a-zA-Z_][a-zA-Z0-9_]*)', repl_jump, content, flags=re.MULTILINE)
        content = re.sub(r'^(\s*call\s+)([a-zA-Z_][a-zA-Z0-9_]*)', repl_call, content, flags=re.MULTILINE)
        return content

    def _reconcile_labels_and_targets(self, files: list[RenpyFile], script: Script) -> list[RenpyFile]:
        labels = self._collect_all_labels(files)
        if not labels:
            return files

        fixed_files = []
        for f in files:
            content = f.content
            if f.path.endswith(".rpy"):
                content = self._rewrite_jump_and_call_targets(content, labels)
            fixed_files.append(RenpyFile(path=f.path, content=content))

        return fixed_files

    def _infer_asset_type(self, path: str) -> str:
        p = path.lower().replace("\\", "/")
        if p.startswith("images/bg") or "/bg " in p or "/bg/" in p:
            return "background"
        if "images/characters" in p:
            return "character"
        if p.startswith("audio/bgm") or "/bgm/" in p:
            return "bgm"
        if p.startswith("audio/sfx") or "/sfx/" in p:
            return "sfx"
        if p.endswith((".png", ".jpg", ".jpeg", ".webp")):
            return "image"
        if p.endswith((".ogg", ".mp3", ".wav")):
            return "audio"
        return "asset"

    def _normalize_assets_needed(self, assets_needed: Any) -> list[dict]:
        normalized = []
        if not isinstance(assets_needed, list):
            return normalized

        for item in assets_needed:
            if isinstance(item, str):
                normalized.append({"path": item, "type": self._infer_asset_type(item)})
                continue

            if isinstance(item, dict):
                if "path" in item:
                    normalized.append({
                        "path": str(item["path"]),
                        "type": item.get("type") or self._infer_asset_type(str(item["path"])),
                        **{k: v for k, v in item.items() if k not in {"path", "type"}}
                    })
                    continue
                normalized.append(item)
                continue

            normalized.append({"path": str(item), "type": "asset"})

        return normalized

    def _looks_like_invalid_scene_content(self, content: str) -> bool:
        suspicious_patterns = [
            r'^\s*\"type:\s*\w+',
            r'^\s*type:\s*\w+',
            r'^\s*\{\s*\"type\"',
            r'^\s*\"character\":',
            r'^\s*\"text\":',
            r'^\s*\[\s*\{',
        ]

        lines = content.splitlines()
        hit_count = 0
        for line in lines[:60]:
            for pattern in suspicious_patterns:
                if re.search(pattern, line):
                    hit_count += 1
                    break

        return hit_count >= 2

    def _validate_generated_files(self, files: list[RenpyFile]):
        paths = {f.path for f in files}
        if "script.rpy" not in paths:
            raise ValueError("生成结果缺少 script.rpy")

        if any(p.startswith("scenes/") and p.endswith(".rpy") for p in paths):
            for f in files:
                if f.path.startswith("scenes/") and f.path.endswith(".rpy"):
                    if self._looks_like_invalid_scene_content(f.content):
                        raise ValueError(f"检测到疑似无效场景脚本: {f.path}")
            return

        raise ValueError("生成结果缺少 scenes/*.rpy")

    def _generate_fallback_code(self, script: Script) -> list[RenpyFile]:
        files = []

        char_lines = ['## 角色定义（降级生成）', '']
        colors = ["#C8FFC8", "#FFC8C8", "#C8C8FF", "#FFFFC8", "#FFC8FF", "#C8FFFF"]

        for i, char in enumerate(script.characters):
            color = self._sanitize_color(getattr(char, "text_color", None)) or colors[i % len(colors)]
            safe_name = char.id
            char_name = self._escape_renpy_text(char.name)
            char_lines.append(f'define {safe_name} = Character(_("{char_name}"), color="{color}")')

        files.append(RenpyFile(path="characters.rpy", content="\n".join(char_lines)))

        for scene in script.scenes:
            bg_name = scene.background if scene.background else "black"
            lines = [
                f'label {scene.id}:',
                f'    scene bg {bg_name}',
                '    with fade',
                ''
            ]

            for seq in scene.sequences:
                if seq.type == "narration" and seq.text:
                    txt = self._escape_renpy_text(seq.text)
                    lines.append(f'    "{txt}"')

                elif seq.type == "dialogue" and seq.character and seq.text:
                    txt = self._escape_renpy_text(seq.text)
                    expr = f" {seq.expression}" if seq.expression else ""
                    lines.append(f'    show {seq.character}{expr} at center')
                    lines.append(f'    {seq.character} "{txt}"')

                elif seq.type == "choice" and seq.options:
                    lines.append('    menu:')
                    for opt in seq.options:
                        opt_text = self._escape_renpy_text(opt.text)
                        jump_to = opt.jump_to if opt.jump_to else scene.id
                        lines.append(f'        "{opt_text}":')
                        lines.append(f'            jump {jump_to}')

                elif seq.type == "transition":
                    transition_type = seq.transition_type if seq.transition_type else "fade"
                    lines.append(f'    with {transition_type}')

            lines.append('')
            lines.append('    return')

            files.append(RenpyFile(path=f"scenes/{scene.id}.rpy", content="\n".join(lines)))

        start_scene = script.scenes[0].id if script.scenes else "scene_01"
        script_content = f'''## 游戏入口（降级生成）
label start:
    jump {start_scene}
'''
        files.append(RenpyFile(path="script.rpy", content=script_content))

        return files

    def _save_debug_code_response(self, code_data: dict, output_base_path: str):
        try:
            output = Path(output_base_path)
            output.mkdir(parents=True, exist_ok=True)
            with open(output / "debug_code_response.json", "w", encoding="utf-8") as f:
                json.dump(code_data, f, ensure_ascii=False, indent=2)
            print("🧪 已保存原始代码返回到 debug_code_response.json")
        except Exception as e:
            print(f"⚠️ 保存 debug_code_response.json 失败: {e}")

    def _save_intermediate(self, script: dict, code: dict, output_path: str):
        output = Path(output_path)
        output.mkdir(parents=True, exist_ok=True)

        try:
            with open(output / "script.json", "w", encoding="utf-8") as f:
                json.dump(script, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存script.json失败: {e}")

        try:
            with open(output / "code.json", "w", encoding="utf-8") as f:
                json.dump(code, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存code.json失败: {e}")

    def preview(self, output_path: str = "./output/game"):
        builder = RenpyBuilder("", output_path)
        return builder.launch_preview()
