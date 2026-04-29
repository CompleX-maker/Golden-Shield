import json
import copy
import re
from jsonschema import validate, ValidationError
from typing import Any


SCRIPT_SCHEMA = {
    "type": "object",
    "required": ["title", "characters", "scenes"],
    "properties": {
        "title": {"type": "string"},
        "characters": {"type": "array"},
        "backgrounds": {"type": "array"},
        "scenes": {"type": "array"}
    }
}


def normalize_identifier(value: Any, prefix: str, index: int) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r'[^a-z0-9_]+', '_', value)
    value = re.sub(r'_+', '_', value).strip('_')
    if not value:
        value = f"{prefix}_{index}"
    if value[0].isdigit():
        value = f"{prefix}_{value}"
    return value


def normalize_color(value: Any) -> str | None:
    """
    将颜色修正为合法 hex 格式，不合法时返回 None。
    """
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    if not s.startswith("#"):
        # 允许模型给 "87CEEB" 这种
        s = "#" + s

    hex_part = s[1:]

    # 合法长度：3 / 4 / 6 / 8
    if re.fullmatch(r'[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}', hex_part):
        return "#" + hex_part.upper()

    # 常见错误：5位 / 7位，直接判无效
    return None


def _extract_text_from_structured_string(text: str) -> str:
    if not isinstance(text, str):
        return str(text)

    s = text.strip()

    try:
        if s.startswith("{") and '"text"' in s:
            obj = json.loads(s)
            if isinstance(obj, dict) and obj.get("text"):
                return str(obj["text"]).strip()
    except Exception:
        pass

    m = re.search(r'text\s*[:=]\s*(.+)$', s, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip().strip('"').strip("'")
        if candidate:
            return candidate

    s = re.sub(r'^\s*type\s*[:=]\s*[a-zA-Z_]+\s*,?\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^\s*character\s*[:=]\s*[a-zA-Z0-9_]+\s*,?\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^\s*expression\s*[:=]\s*[a-zA-Z0-9_]+\s*,?\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^\s*text\s*[:=]\s*', '', s, flags=re.IGNORECASE)

    return s.strip().strip('"').strip("'")


def _normalize_sequence_string(item: str) -> dict:
    s = _extract_text_from_structured_string(item)
    if not s:
        s = "……"
    return {
        "type": "narration",
        "text": s
    }


def _expand_sparse_scene_sequences(scene_title: str, sequences: list[dict]) -> list[dict]:
    if len(sequences) >= 5:
        return sequences

    expanded = list(sequences)

    seed_text = None
    for seq in expanded:
        if seq.get("type") == "narration" and seq.get("text"):
            seed_text = seq["text"]
            break

    if not seed_text:
        seed_text = f"{scene_title}场景展开。"

    templates = [
        {"type": "narration", "text": seed_text},
        {"type": "narration", "text": "空气里浮着一种不安，事情显然没有表面上那么简单。"},
        {"type": "narration", "text": "短暂的沉默之后，新的信息开始一点点浮出水面。"},
        {"type": "narration", "text": "这一刻的决定，会让故事走向不同的方向。"},
        {"type": "narration", "text": "她意识到，眼前的每一个细节都可能影响最终结果。"},
    ]

    i = 0
    while len(expanded) < 5:
        expanded.append(templates[min(i, len(templates) - 1)])
        i += 1

    return expanded


def _guess_contextual_choice_options(scene: dict, scene_ids: list[str]) -> list[dict]:
    full_text_parts = []
    for seq in scene.get("sequences", []):
        if not isinstance(seq, dict):
            continue
        if seq.get("text"):
            full_text_parts.append(str(seq.get("text")))
        if seq.get("type") == "choice":
            return []

    full_text = " ".join(full_text_parts)

    next_scene = scene_ids[1] if len(scene_ids) > 1 else scene_ids[0]
    fallback_scene = scene_ids[-1] if scene_ids else scene.get("id", "scene_01")

    if any(k in full_text for k in ["电话", "手机", "来电", "诈骗", "转账", "银行", "公安", "儿子", "小军"]):
        return [
            {"text": "先稳住对方，继续听下去确认细节", "jump_to": next_scene},
            {"text": "立刻挂断电话，联系家人或银行核实", "jump_to": fallback_scene}
        ]

    if any(k in full_text for k in ["线索", "现场", "照片", "调查", "真相", "秘密"]):
        return [
            {"text": "顺着线索继续追查下去", "jump_to": next_scene},
            {"text": "先回头整理现有信息，再决定下一步", "jump_to": fallback_scene}
        ]

    if any(k in full_text for k in ["同学", "教室", "操场", "喜欢", "告白", "约定"]):
        return [
            {"text": "鼓起勇气把心里的话说出来", "jump_to": next_scene},
            {"text": "暂时把情绪压下去，先观察对方反应", "jump_to": fallback_scene}
        ]

    return [
        {"text": "顺着眼前的事继续走下去", "jump_to": next_scene},
        {"text": "先停下来想清楚，再决定下一步", "jump_to": fallback_scene}
    ]


def validate_and_fix(data: dict) -> dict:
    print("🔧 开始强制修复剧本数据...")

    if not isinstance(data, dict):
        print("⚠️ 根数据不是对象，创建新对象")
        data = {}

    if "title" not in data or not isinstance(data["title"], str) or not data["title"].strip():
        data["title"] = "未命名作品"

    if "characters" not in data or not isinstance(data["characters"], list) or not data["characters"]:
        data["characters"] = [{
            "id": "protagonist",
            "name": "主角",
            "description": "故事主角",
            "default_expression": "neutral",
            "expressions": ["neutral", "happy", "sad"],
            "text_color": "#C8FFC8"
        }]

    fixed_characters = []
    used_char_ids = set()

    for i, char in enumerate(data["characters"]):
        if not isinstance(char, dict):
            char = {}

        char_id = normalize_identifier(char.get("id"), "char", i)
        if char_id in used_char_ids:
            char_id = f"{char_id}_{i}"
        used_char_ids.add(char_id)

        fixed_characters.append({
            "id": char_id,
            "name": str(char.get("name") or f"角色{i}"),
            "description": str(char.get("description") or ""),
            "default_expression": str(char.get("default_expression") or "neutral"),
            "expressions": char.get("expressions") if isinstance(char.get("expressions"), list) and char.get("expressions") else ["neutral"],
            "text_color": normalize_color(char.get("text_color"))
        })

    data["characters"] = fixed_characters
    character_ids = {c["id"] for c in fixed_characters}

    if "scenes" not in data or not isinstance(data["scenes"], list) or not data["scenes"]:
        data["scenes"] = [{
            "id": "scene_01",
            "title": "开始",
            "background": "room",
            "sequences": [{"type": "narration", "text": "故事开始。"}]
        }]

    fixed_scenes = []
    used_scene_ids = set()

    for i, scene in enumerate(data["scenes"]):
        if not isinstance(scene, dict):
            scene = {}

        scene_id = normalize_identifier(scene.get("id"), "scene", i)
        if scene_id in used_scene_ids:
            scene_id = f"{scene_id}_{i}"
        used_scene_ids.add(scene_id)

        title = str(scene.get("title") or f"场景{i + 1}")
        background = normalize_identifier(scene.get("background"), "room", i)

        raw_sequences = scene.get("sequences")
        if not isinstance(raw_sequences, list):
            if isinstance(raw_sequences, str):
                raw_sequences = [_normalize_sequence_string(raw_sequences)]
            else:
                raw_sequences = [{"type": "narration", "text": f"{title}场景开始。"}]

        fixed_sequences = []
        for seq in raw_sequences:
            if isinstance(seq, str):
                fixed_sequences.append(_normalize_sequence_string(seq))
                continue

            if not isinstance(seq, dict):
                fixed_sequences.append({
                    "type": "narration",
                    "text": _extract_text_from_structured_string(str(seq))
                })
                continue

            seq_type = str(seq.get("type") or "narration").strip().lower()
            if seq_type not in {"narration", "dialogue", "choice", "transition"}:
                seq_type = "narration"

            if seq_type == "narration":
                text = _extract_text_from_structured_string(str(seq.get("text") or "……"))
                fixed_sequences.append({
                    "type": "narration",
                    "text": text or "……"
                })

            elif seq_type == "dialogue":
                char_id = seq.get("character")
                if char_id not in character_ids:
                    char_id = next(iter(character_ids))

                text = _extract_text_from_structured_string(str(seq.get("text") or "……"))
                expression = str(seq.get("expression") or "neutral")

                fixed_sequences.append({
                    "type": "dialogue",
                    "character": char_id,
                    "expression": expression,
                    "text": text or "……"
                })

            elif seq_type == "choice":
                options = seq.get("options", [])
                fixed_options = []

                if isinstance(options, list):
                    for j, opt in enumerate(options):
                        if not isinstance(opt, dict):
                            continue
                        fixed_options.append({
                            "text": str(opt.get("text") or f"选项{j + 1}"),
                            "jump_to": str(opt.get("jump_to") or scene_id)
                        })

                if len(fixed_options) < 2:
                    fixed_options = [
                        {"text": "继续当前行动", "jump_to": scene_id},
                        {"text": "换一种方式处理", "jump_to": scene_id}
                    ]

                fixed_sequences.append({
                    "type": "choice",
                    "options": fixed_options
                })

            elif seq_type == "transition":
                transition_type = str(seq.get("transition_type") or "fade")
                if transition_type not in {"fade", "dissolve", "cut"}:
                    transition_type = "fade"

                try:
                    duration = float(seq.get("duration") or 1.0)
                except Exception:
                    duration = 1.0

                fixed_sequences.append({
                    "type": "transition",
                    "transition_type": transition_type,
                    "duration": duration
                })

        fixed_sequences = _expand_sparse_scene_sequences(title, fixed_sequences)

        fixed_scenes.append({
            "id": scene_id,
            "title": title,
            "background": background,
            "bgm": scene.get("bgm"),
            "sfx": scene.get("sfx"),
            "sequences": fixed_sequences
        })
        print(f"✅ 场景修复完成: {scene_id} ({len(fixed_sequences)}个序列)")

    data["scenes"] = fixed_scenes

    if "backgrounds" not in data or not isinstance(data["backgrounds"], list):
        data["backgrounds"] = []

    fixed_backgrounds = []
    bg_ids = set()

    for i, bg in enumerate(data["backgrounds"]):
        if not isinstance(bg, dict):
            continue
        bg_id = normalize_identifier(bg.get("id"), "bg", i)
        if bg_id in bg_ids:
            continue
        bg_ids.add(bg_id)
        fixed_backgrounds.append({
            "id": bg_id,
            "description": str(bg.get("description") or f"{bg_id}场景背景")
        })

    for scene in fixed_scenes:
        bg = scene["background"]
        if bg not in bg_ids:
            fixed_backgrounds.append({
                "id": bg,
                "description": f"{bg}场景背景"
            })
            bg_ids.add(bg)
            print(f"🔧 创建背景: {bg}")

    data["backgrounds"] = fixed_backgrounds

    if "metadata" not in data or not isinstance(data["metadata"], dict):
        data["metadata"] = {
            "genre": "视觉小说",
            "tone": "中性",
            "estimated_duration": "约20分钟"
        }

    print("📋 最终Schema验证...")
    try:
        validate(instance=data, schema=SCRIPT_SCHEMA)
        print("✅ 验证通过！")
    except ValidationError as e:
        print(f"⚠️ 验证警告: {e.message}")

    return data


def ensure_branching_structure(data: dict) -> dict:
    scenes = data.get("scenes", [])
    if not scenes:
        return data

    scene_ids = [s["id"] for s in scenes if isinstance(s, dict) and s.get("id")]
    scene_id_set = set(scene_ids)

    choice_count = 0
    ending_count = 0

    for scene in scenes:
        title = str(scene.get("title", "")).lower()
        sid = str(scene.get("id", "")).lower()

        if (
            "ending" in title or "结局" in title or "终章" in title or "尾声" in title
            or any(k in sid for k in ["ending", "end", "good", "bad", "true", "normal"])
        ):
            ending_count += 1

        for seq in scene.get("sequences", []):
            if isinstance(seq, dict) and seq.get("type") == "choice":
                choice_count += 1
                for opt in seq.get("options", []):
                    if isinstance(opt, dict):
                        if opt.get("jump_to") not in scene_id_set:
                            opt["jump_to"] = scene_ids[-1] if scene_ids else "scene_01"

    if choice_count == 0 and len(scenes) >= 2:
        print("🔧 未检测到choice，自动补充分支选项")
        default_opts = _guess_contextual_choice_options(scenes[0], scene_ids)
        scenes[0]["sequences"].append({
            "type": "choice",
            "options": default_opts
        })

    if ending_count < 2:
        print("🔧 结局数量不足，自动补全多结局")

        bg_ids = {b["id"] for b in data.get("backgrounds", []) if isinstance(b, dict) and "id" in b}
        if "black" not in bg_ids:
            data.setdefault("backgrounds", []).append({"id": "black", "description": "黑屏背景"})

        existing_ids = {s.get("id") for s in scenes if isinstance(s, dict)}

        if "ending_bad" not in existing_ids:
            scenes.append({
                "id": "ending_bad",
                "title": "Bad Ending",
                "background": "black",
                "sequences": [
                    {"type": "narration", "text": "你错过了改变命运的最后机会，一切无可挽回。"},
                    {"type": "narration", "text": "回过神时，已经太迟了。"},
                    {"type": "narration", "text": "最后留下的只有无法弥补的遗憾。"},
                    {"type": "narration", "text": "Bad Ending"}
                ]
            })

        if "ending_good" not in existing_ids:
            scenes.append({
                "id": "ending_good",
                "title": "Good Ending",
                "background": "black",
                "sequences": [
                    {"type": "narration", "text": "在一次次选择之后，你终于迎来了较为圆满的结局。"},
                    {"type": "narration", "text": "曾经摇摆不定的命运，也终于落在了更好的方向上。"},
                    {"type": "narration", "text": "你长长松了一口气，心里终于安定下来。"},
                    {"type": "narration", "text": "Good Ending"}
                ]
            })

    data["scenes"] = scenes
    return data


def validate_script(data: dict) -> dict:
    data_copy = copy.deepcopy(data) if data else {}
    fixed_data = validate_and_fix(data_copy)
    fixed_data = ensure_branching_structure(fixed_data)

    if not fixed_data or not isinstance(fixed_data, dict):
        print("❌ 修复失败，创建紧急默认结构")
        fixed_data = {
            "title": "紧急默认作品",
            "metadata": {"genre": "默认", "tone": "中性", "estimated_duration": "5分钟"},
            "characters": [{"id": "hero", "name": "主角", "description": "默认主角", "expressions": ["neutral"]}],
            "backgrounds": [{"id": "room", "description": "默认房间"}],
            "scenes": [{
                "id": "scene_01",
                "title": "开始",
                "background": "room",
                "sequences": [{"type": "narration", "text": "故事加载中..."}]
            }]
        }

    return fixed_data
