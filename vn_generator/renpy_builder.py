import os
import shutil
import json
import re
import difflib
from pathlib import Path
from typing import List, Dict, Tuple, Set

from .models import RenpyFile, Script

RESERVED_NAMES = {
    'str', 'int', 'float', 'bool', 'list', 'dict', 'set', 'tuple', 'type', 'object',
    'name', 'input', 'output', 'call', 'jump', 'return', 'scene', 'show', 'hide',
    'with', 'menu', 'label', 'define', 'default', 'init', 'python', 'image',
    'character', 'window', 'pause', 'play', 'stop', 'fade', 'dissolve', 'cut',
    'true', 'false', 'none', 'null', 'screen', 'style', 'transform', 'animation',
    'break', 'continue', 'for', 'while', 'if', 'else', 'elif', 'in', 'not', 'and', 'or',
    'fraudster', 'thief', 'police', 'id'
}


class RenpyBuilder:
    def __init__(self, template_path: str, output_path: str):
        self.template_path = Path(template_path) if template_path else None
        self.output_path = Path(output_path)
        self.base_dir = Path(__file__).resolve().parent.parent
        self.source_font_dir = self.base_dir / "font"
        self._var_map = {}
        self._character_var_map = {}

    def _write_vn_transforms(self, game_dir: Path):
        content = '''## 自动生成的 VN 立绘站位与焦点变换

transform vn_center:
    xalign 0.5
    yalign 1.0
    zoom 0.78

transform vn_left:
    xalign 0.24
    yalign 1.0
    zoom 0.74

transform vn_right:
    xalign 0.76
    yalign 1.0
    zoom 0.74

transform vn_left_focus:
    xalign 0.24
    yalign 1.0
    zoom 0.80
    alpha 1.0

transform vn_right_focus:
    xalign 0.76
    yalign 1.0
    zoom 0.80
    alpha 1.0

transform vn_left_dim:
    xalign 0.24
    yalign 1.0
    zoom 0.72
    alpha 0.72

transform vn_right_dim:
    xalign 0.76
    yalign 1.0
    zoom 0.72
    alpha 0.72

transform vn_center_focus:
    xalign 0.5
    yalign 1.0
    zoom 0.82
    alpha 1.0
'''
        (game_dir / "transforms.rpy").write_text(content, encoding="utf-8")

    def _write_image_definitions(self, game_dir: Path, script: Script):
        """
        生成 Ren'Py 图片别名定义，解决：
        - scene bg xxx 无法找到背景图
        - show char expr 无法找到角色立绘
        """
        lines = ['## 图片资源定义', '']

        # ===== 背景图 =====
        bg_ids = set()
        for bg in script.backgrounds:
            bg_id = str(bg.id).strip()
            if not bg_id:
                continue
            bg_ids.add(bg_id)
            lines.append(f'image bg {bg_id} = "images/bg/{bg_id}.png"')

        # 保险补一个黑屏背景
        if "black" not in bg_ids:
            lines.append('image bg black = "images/bg/black.png"')

        lines.append('')

        # ===== 角色立绘 =====
        for char in script.characters:
            original_char_id = str(char.id).strip()
            if not original_char_id:
                continue

            final_var = self._character_var_map.get(original_char_id, original_char_id)

            expressions = char.expressions if char.expressions else ["neutral"]
            default_expr = char.default_expression or "neutral"
            if default_expr not in expressions:
                expressions = [default_expr] + [x for x in expressions if x != default_expr]

            seen_expr = set()
            for expr in expressions:
                expr = str(expr).strip() or "neutral"
                if expr in seen_expr:
                    continue
                seen_expr.add(expr)

                lines.append(
                    f'image {final_var} {expr} = "images/characters/{original_char_id}/{expr}.png"'
                )

        (game_dir / "images.rpy").write_text("\n".join(lines), encoding="utf-8")

    def create_project(self, files: List["RenpyFile"], script: Script, font_name: str = "auto") -> str:
        if self.output_path.exists():
            shutil.rmtree(self.output_path)

        if self.template_path and self.template_path.exists():
            shutil.copytree(self.template_path, self.output_path)
        else:
            self._create_minimal_structure()

        game_dir = self.output_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)

        self._ensure_resource_dirs(game_dir)
        self._copy_custom_fonts_to_game(game_dir)

        system_controlled = {
            "characters.rpy",
            "gui.rpy",
            "screens.rpy",
            "options.rpy",
            "script.rpy",
            "game_end_summary.rpy",
            "images.rpy",
            "transforms.rpy",
        }

        for file in files:
            if file.path in system_controlled:
                print(f"跳过 LLM 生成的系统文件: {file.path}")
                continue

            file_path = game_dir / file.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            cleaned = self._sanitize_rpy_content(file.content) if file.path.endswith(".rpy") else file.content
            file_path.write_text(cleaned, encoding="utf-8")

        self._generate_placeholders(game_dir, script)

        font_path, font_display, _ = self._get_font_config(game_dir, font_name)

        self._write_full_gui_config(game_dir, font_path, font_display)
        self._write_screens_config(game_dir, font_path, font_display)
        self._write_options(game_dir, script)
        self._write_characters(game_dir, script)
        self._write_image_definitions(game_dir, script)
        self._write_vn_transforms(game_dir)
        self._rewrite_scene_files_to_match_defined_characters(game_dir, script)
        self._ensure_all_characters_defined(game_dir, script)

        self._write_script_entry(game_dir, script)
        self._write_game_end_summary(game_dir, script)
        self._append_end_jump_to_leaf_scenes(game_dir, script)

        self._create_font_guide(game_dir)
        self._write_project_json(script)

        return str(self.output_path)

    def _sanitize_var_name(self, name: str) -> str:
        clean = re.sub(r'[^a-z0-9_]', '_', str(name).lower())
        if not clean or clean[0].isdigit():
            clean = 'c_' + clean
        if clean in RESERVED_NAMES:
            clean = clean + '_char'
        return clean

    def _escape_renpy_text(self, text: str) -> str:
        if text is None:
            return ""
        text = str(text)
        text = text.replace("\\", "\\\\")
        text = text.replace('"', '\\"')
        text = text.replace("\r\n", "\\n").replace("\n", "\\n")
        return text

    def _sanitize_rpy_content(self, content: str) -> str:
        """
        对 LLM 生成的 rpy 文本做最终兜底清洗，重点修复：
        1. 中文弯引号
        2. menu 选项里的未转义双引号
        3. 角色对白 / 旁白中的未转义双引号
        4. Windows 换行
        """

        def _escape_inner_quotes(text: str) -> str:
            """
            将字符串内部未转义的双引号转成 \"
            先保留已有的 \\"，避免重复转义。
            """
            placeholder = "__RENPY_ESCAPED_QUOTE__"
            text = text.replace('\\"', placeholder)
            text = text.replace('"', '\\"')
            text = text.replace(placeholder, '\\"')
            return text

        def _fix_menu_line(line: str) -> str:
            """
            修复 menu 选项行：
            "顺着对方的话问："是小军吧？"":
            ->
            "顺着对方的话问：\\"是小军吧？\\"":
            """
            stripped = line.strip()
            if not (stripped.startswith('"') and stripped.endswith('":')):
                return line

            indent = line[:len(line) - len(line.lstrip())]
            inner = stripped[1:-2]
            inner = _escape_inner_quotes(inner)
            return f'{indent}"{inner}":'

        def _fix_say_line(line: str) -> str:
            """
            修复旁白 / 对话行：
            narrator "她问："你是谁？""
            ->
            narrator "她问：\\"你是谁？\\""
            """
            stripped = line.strip()
            if not stripped:
                return line

            # 跳过明显不是对白的语句
            reserved_prefixes = (
                "label ", "menu:", "scene ", "show ", "hide ", "jump ", "call ",
                "return", "with ", "play ", "stop ", "queue ", "window ",
                "pause", "python:", "init ", "define ", "default ", "$"
            )
            for prefix in reserved_prefixes:
                if stripped.startswith(prefix):
                    return line

            # 匹配：角色对白 / 旁白
            # 示例：
            # narrator "xxx"
            # e "xxx"
            # "xxx"
            m_dialogue = re.match(r'^(\s*[a-zA-Z_][a-zA-Z0-9_]*\s+)(".*")(\s*)$', line)
            m_narration = re.match(r'^(\s*)(".*")(\s*)$', line)

            if m_dialogue:
                prefix, quoted, suffix = m_dialogue.groups()
                inner = quoted[1:-1]
                inner = _escape_inner_quotes(inner)
                return f'{prefix}"{inner}"{suffix}'

            if m_narration:
                prefix, quoted, suffix = m_narration.groups()
                inner = quoted[1:-1]
                inner = _escape_inner_quotes(inner)
                return f'{prefix}"{inner}"{suffix}'

            return line

        # 1) 基础字符清洗
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        content = content.replace("\u201c", '"').replace("\u201d", '"')
        content = content.replace("\u2018", "'").replace("\u2019", "'")
        content = content.replace("\u00a0", " ")

        fixed_lines = []
        in_menu_block = False

        for line in content.splitlines():
            stripped = line.strip()

            # 进入 menu 块
            if stripped == "menu:":
                in_menu_block = True
                fixed_lines.append(line)
                continue

            # menu 块结束判断：遇到非空且缩进回到 menu 同级/更外层的复杂情况很难完美判定，
            # 这里采用实用策略：只要当前行不是典型 menu 选项/其子块，就由正常对白修复逻辑处理。
            if in_menu_block:
                if stripped.startswith('"') and stripped.endswith('":'):
                    fixed_lines.append(_fix_menu_line(line))
                    continue

                # menu 下的动作行、空行、子块行，直接保留
                if (
                        stripped == ""
                        or stripped.startswith("jump ")
                        or stripped.startswith("call ")
                        or stripped.startswith("return")
                        or stripped.startswith("if ")
                        or stripped.startswith("elif ")
                        or stripped.startswith("else:")
                        or stripped.startswith("$")
                ):
                    fixed_lines.append(line)
                    continue

                # 如果是别的普通文本，也继续走普通修复
                # 但 menu 状态不强行维持
                in_menu_block = False

            # 普通对白 / 旁白修复
            fixed_lines.append(_fix_say_line(line))

        return "\n".join(fixed_lines)

    def _sanitize_color(self, color: str | None) -> str | None:
        if not color:
            return None
        c = str(color).strip()
        if not c.startswith("#"):
            c = "#" + c
        hex_part = c[1:]
        if re.fullmatch(r'[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}', hex_part):
            return "#" + hex_part.upper()
        return None

    def _create_minimal_structure(self):
        self.output_path.mkdir(parents=True, exist_ok=True)

    def _ensure_resource_dirs(self, game_dir: Path):
        (game_dir / "images" / "bg").mkdir(parents=True, exist_ok=True)
        (game_dir / "images" / "characters").mkdir(parents=True, exist_ok=True)
        (game_dir / "font").mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, text: str) -> str:
        safe = re.sub(r'[^a-zA-Z0-9_-]', '_', str(text))
        safe = safe[:50].strip('_')
        return safe or "VisualNovel"

    def _copy_custom_fonts_to_game(self, game_dir: Path):
        dst_font_dir = game_dir / "font"
        dst_font_dir.mkdir(parents=True, exist_ok=True)

        if not self.source_font_dir.exists():
            print(f"字体目录不存在: {self.source_font_dir}")
            return

        copied = 0
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            for font_file in self.source_font_dir.glob(ext):
                try:
                    shutil.copy2(font_file, dst_font_dir / font_file.name)
                    copied += 1
                except Exception as e:
                    print(f"复制字体失败: {font_file.name} -> {e}")

        print(f"已复制字体到项目: {copied} 个")

    def _scan_custom_fonts(self, base_dir: Path) -> Dict[str, str]:
        fonts = {}

        candidates = [
            base_dir / "font",
            base_dir / "game" / "font",
        ]

        for font_dir in candidates:
            if not font_dir.exists():
                continue

            for ext in [".ttf", ".otf", ".ttc"]:
                for font_file in font_dir.glob(f"*{ext}"):
                    rel_path = font_file.as_posix()

                    if "game/font/" in rel_path:
                        rel_path = rel_path.split("game/", 1)[1]
                    else:
                        rel_path = f"font/{font_file.name}"

                    fonts[font_file.stem] = rel_path

        return fonts

    def _scan_system_fonts(self) -> Dict[str, str]:
        system_fonts = {}
        candidates = [
            ("[系统] 微软雅黑", "C:/Windows/Fonts/msyh.ttc"),
            ("[系统] 微软雅黑粗体", "C:/Windows/Fonts/msyhbd.ttc"),
            ("[系统] 黑体", "C:/Windows/Fonts/simhei.ttf"),
            ("[系统] 宋体", "C:/Windows/Fonts/simsun.ttc"),
            ("[系统] 等线", "C:/Windows/Fonts/deng.ttf"),
            ("[系统] 苹方", "/System/Library/Fonts/PingFang.ttc"),
            ("[系统] 华文黑体", "/System/Library/Fonts/STHeiti Light.ttc"),
            ("[系统] 文泉驿正黑", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        ]

        for name, path in candidates:
            if os.path.exists(path):
                system_fonts[name] = path.replace("\\", "/")

        return system_fonts

    def get_available_fonts(self, base_dir: Path = None) -> Dict[str, str]:
        fonts = {}
        if base_dir:
            fonts.update(self._scan_custom_fonts(base_dir))

        fonts.update(self._scan_system_fonts())

        if not fonts:
            fonts["DejaVuSans"] = "DejaVuSans.ttf"

        return fonts

    def _normalize_font_key(self, s: str) -> str:
        return re.sub(r'[\s\-_]+', '', s).lower()

    def _pick_preferred_font(self, fonts: Dict[str, str]) -> Tuple[str, str]:
        if not fonts:
            return "", ""

        preferred = [
            "sourcehan", "notosanscjk", "notosans", "msyh", "simhei", "simsun", "wenkai",
            "思源", "微软雅黑", "黑体", "宋体", "文楷"
        ]

        for kw in preferred:
            for name, path in fonts.items():
                if kw in name.lower():
                    return name, path

        strong_system_priority = ["[系统] 微软雅黑", "[系统] 黑体", "[系统] 宋体", "[系统] 微软雅黑粗体"]
        for sys_name in strong_system_priority:
            if sys_name in fonts:
                return sys_name, fonts[sys_name]

        return next(iter(fonts.items()))

    def _find_best_custom_font(self, font_name: str) -> Tuple[str, str]:
        custom_fonts = self._scan_custom_fonts(self.base_dir)

        if font_name in custom_fonts:
            return font_name, custom_fonts[font_name]

        normalized_target = self._normalize_font_key(font_name)

        for name, path in custom_fonts.items():
            if self._normalize_font_key(name) == normalized_target:
                return name, path

        for name, path in custom_fonts.items():
            norm = self._normalize_font_key(name)
            if normalized_target in norm or norm in normalized_target:
                return name, path

        return "", ""

    def _get_font_size_profile(self, font_display: str) -> dict:
        return {
            "text_size": 28,
            "name_size": 30,
            "interface_size": 26,
            "button_size": 26,
            "choice_size": 26,
            "label_size": 30,
            "yesno_size": 28
        }

    def _get_font_config(self, game_dir: Path, font_name: str) -> Tuple[str, str, List[str]]:
        project_fonts = self._scan_custom_fonts(game_dir)

        if font_name == "auto":
            if project_fonts:
                font_display, font_path = self._pick_preferred_font(project_fonts)
                print(f"自动选择项目字体: {font_display}")
            else:
                base_fonts = self._scan_custom_fonts(self.base_dir)
                if base_fonts:
                    font_display, font_path = self._pick_preferred_font(base_fonts)
                    print(f"自动选择源字体目录字体: {font_display}")
                else:
                    system_fonts = self._scan_system_fonts()
                    if system_fonts:
                        font_display, font_path = self._pick_preferred_font(system_fonts)
                        print(f"自动选择系统字体: {font_display}")
                    else:
                        font_display = "DejaVuSans"
                        font_path = "DejaVuSans.ttf"
                        print("警告: 未找到可用中文字体，将显示方块字")
        else:
            if font_name.startswith("[系统]"):
                system_fonts = self._scan_system_fonts()
                if font_name in system_fonts:
                    font_display = font_name
                    font_path = system_fonts[font_name]
                    print(f"使用指定系统字体: {font_display}")
                else:
                    print(f"系统字体 '{font_name}' 未找到，回退自动检测")
                    return self._get_font_config(game_dir, "auto")
            else:
                if font_name in project_fonts:
                    font_display = font_name
                    font_path = project_fonts[font_name]
                    print(f"使用项目字体: {font_display}")
                else:
                    matched_name, matched_path = self._find_best_custom_font(font_name)
                    if matched_path:
                        font_display, font_path = matched_name, matched_path
                        print(f"使用指定字体: {font_display}")
                    else:
                        print(f"字体 '{font_name}' 未找到，回退自动检测")
                        return self._get_font_config(game_dir, "auto")

        config_lines = [
            f'define gui.text_font = "{font_path}"',
            f'define gui.name_text_font = "{font_path}"',
            f'define gui.interface_text_font = "{font_path}"',
            f'define gui.button_text_font = "{font_path}"',
            f'define gui.choice_button_text_font = "{font_path}"',
        ]
        return font_path, font_display, config_lines

    def _write_full_gui_config(self, game_dir: Path, font_path: str, font_display: str):
        size_profile = self._get_font_size_profile(font_display)
        lines = [
            "## 自动生成的 GUI 配置",
            f"## 字体: {font_display}",
            "",
            "init offset = -1",
            "",
            f'define gui.text_font = "{font_path}"',
            f'define gui.name_text_font = "{font_path}"',
            f'define gui.interface_text_font = "{font_path}"',
            f'define gui.button_text_font = "{font_path}"',
            f'define gui.choice_button_text_font = "{font_path}"',
            "",
            f'define gui.text_size = {size_profile["text_size"]}',
            f'define gui.name_text_size = {size_profile["name_size"]}',
            f'define gui.interface_text_size = {size_profile["interface_size"]}',
            f'define gui.button_text_size = {size_profile["button_size"]}',
            f'define gui.choice_button_text_size = {size_profile["choice_size"]}',
            f'define gui.label_text_size = {size_profile["label_size"]}',
            "",
            "define gui.text_color = '#ffffff'",
            "define gui.name_text_color = '#ffffff'",
            "define gui.interface_text_color = '#ffffff'",
            "",
            "define gui.textbox_height = 278",
            "define gui.name_xpos = 360",
            "define gui.name_ypos = 0",
            "define gui.dialogue_xpos = 402",
            "define gui.dialogue_ypos = 75",
            "define gui.dialogue_width = 1116",
            "",
        ]
        (game_dir / "gui.rpy").write_text("\n".join(lines), encoding="utf-8")

    def _write_screens_config(self, game_dir: Path, font_path: str, font_display: str):
        size_profile = self._get_font_size_profile(font_display)

        content = f'''## 自动生成的 screens 配置
init -2 python:
    style.say_dialogue.font = "{font_path}"
    style.say_label.font = "{font_path}"
    style.input.font = "{font_path}"
    style.button_text.font = "{font_path}"
    style.choice_button_text.font = "{font_path}"
    style.notify_text.font = "{font_path}"
    style.interface_text.font = "{font_path}"
    style.default.font = "{font_path}"

    style.say_dialogue.size = {size_profile["text_size"]}
    style.say_label.size = {size_profile["name_size"]}
    style.button_text.size = {size_profile["button_size"]}
    style.choice_button_text.size = {size_profile["choice_size"]}

style choice_vbox:
    xalign 0.5
    yalign 0.5
    spacing 18

style choice_button:
    xsize 780
    xalign 0.5
    yminimum 58
    padding (28, 16, 28, 16)
    background Frame(Solid("#1a1a2ecc"), 12, 12)
    hover_background Frame(Solid("#2a2a4aee"), 12, 12)

style choice_button_text:
    xalign 0.5
    text_align 0.5
    font "{font_path}"
    size {size_profile["choice_size"]}
    color "#f2f2f2"
    hover_color "#ffffff"
    insensitive_color "#888888"

screen choice(items):
    modal True
    zorder 100

    add Solid("#00000033")

    vbox:
        style "choice_vbox"
        xalign 0.5
        yalign 0.5
        xsize 860

        for i in items:
            textbutton i.caption:
                style "choice_button"
                text_style "choice_button_text"
                action i.action

style yesno_frame:
    xpadding 36
    ypadding 30
    xalign 0.5
    yalign 0.5
    background Frame(Solid("#111111ee"), 16, 16)

style yesno_prompt_text:
    xalign 0.5
    text_align 0.5
    font "{font_path}"
    size {size_profile["yesno_size"]}
    color "#ffffff"

style yesno_button:
    xminimum 180
    yminimum 52
    xpadding 20
    ypadding 10
    background Frame(Solid("#2a2a4acc"), 10, 10)
    hover_background Frame(Solid("#4a4a7acc"), 10, 10)

style yesno_button_text:
    xalign 0.5
    text_align 0.5
    font "{font_path}"
    size {size_profile["button_size"]}
    color "#ffffff"

screen yesno_prompt(message, yes_action, no_action):
    modal True
    zorder 200

    add Solid("#00000088")

    frame:
        style "yesno_frame"
        xalign 0.5
        yalign 0.5
        xmaximum 900

        vbox:
            spacing 24
            xalign 0.5
            yalign 0.5

            text message style "yesno_prompt_text"

            hbox:
                spacing 30
                xalign 0.5

                textbutton _("确定"):
                    style "yesno_button"
                    text_style "yesno_button_text"
                    action yes_action

                textbutton _("取消"):
                    style "yesno_button"
                    text_style "yesno_button_text"
                    action no_action
'''
        (game_dir / "screens.rpy").write_text(content, encoding="utf-8")

    def _write_options(self, game_dir: Path, script: Script):
        safe_dir = self._sanitize_filename(script.title)
        game_name = self._escape_renpy_text(script.title)
        content = f'''## 游戏基础配置
define config.name = _("{game_name}")
define config.version = "1.0.0"
define config.save_directory = "{safe_dir}-1.0"

define gui.show_name = True

define config.has_sound = True
define config.has_music = True
define config.has_voice = False

define config.enter_transition = fade
define config.exit_transition = fade
define config.intra_transition = dissolve
define config.main_game_transition = fade
define config.game_main_transition = fade
define config.end_splash_transition = fade
define config.end_game_transition = fade

init python:
    import os
    build.directory_name = "{safe_dir}"
    build.executable_name = "{safe_dir}"

    if os.path.exists(os.path.join(config.gamedir, "font")):
        build.classify("game/font/**", "archive")

    build.classify("game/images/**", "archive")
    build.classify("game/gui/**", "archive")

define config.default_text_cps = 0
define config.allow_skipping = True
define config.fast_skipping = False
'''
        (game_dir / "options.rpy").write_text(content, encoding="utf-8")

    def _write_characters(self, game_dir: Path, script: Script):
        lines = ['## 角色定义', '']
        colors = ["#C8FFC8", "#FFC8C8", "#C8C8FF", "#FFFFC8", "#FFC8FF", "#C8FFFF", "#FFCC99"]
        self._character_var_map = {}

        for i, char in enumerate(script.characters):
            safe_id = self._sanitize_var_name(char.id)
            if safe_id != char.id:
                print(f"角色 ID 修正: {char.id} -> {safe_id}")

            var_name = safe_id
            if var_name in self._character_var_map.values():
                var_name = f"{safe_id}_{i}"

            self._character_var_map[char.id] = var_name
            color = self._sanitize_color(getattr(char, "text_color", None))
            if not color:
                color = colors[i % len(colors)]

            char_name = self._escape_renpy_text(char.name)
            lines.append(f'define {var_name} = Character(_("{char_name}"), color="{color}")')
            lines.append(f'## 立绘路径: images/characters/{char.id}/{{expression}}.png')

        if not script.characters:
            lines.extend([
                'define narrator = Character(_("旁白"), color="#FFFFFF")',
                'define me = Character(_("我"), color="#C8FFC8")',
            ])

        self._var_map = self._character_var_map.copy()
        (game_dir / "characters.rpy").write_text("\n".join(lines), encoding="utf-8")

    def _normalize_key(self, s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', str(s).lower())

    def _find_best_character_var(self, raw_name: str, script: Script) -> str:
        if raw_name in self._var_map.values():
            return raw_name

        if raw_name in self._character_var_map:
            return self._character_var_map[raw_name]

        normalized_target = self._normalize_key(raw_name)
        if not normalized_target:
            return raw_name

        candidates = {}
        for char in script.characters:
            final_var = self._character_var_map.get(char.id, char.id)
            candidates[self._normalize_key(char.id)] = final_var
            candidates[self._normalize_key(final_var)] = final_var

        if normalized_target in candidates:
            return candidates[normalized_target]

        for norm_name, final_var in candidates.items():
            if normalized_target in norm_name or norm_name in normalized_target:
                return final_var

        close = difflib.get_close_matches(normalized_target, list(candidates.keys()), n=1, cutoff=0.72)
        if close:
            return candidates[close[0]]

        return raw_name

    def _rewrite_scene_files_to_match_defined_characters(self, game_dir: Path, script: Script):
        scenes_dir = game_dir / "scenes"
        if not scenes_dir.exists():
            return

        for scene_file in scenes_dir.glob("*.rpy"):
            content = scene_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            rewritten = []

            for line in lines:
                m_show = re.match(r'^(\s*show\s+)([a-zA-Z_][a-zA-Z0-9_]*)(.*)$', line)
                if m_show:
                    prefix, raw_char, suffix = m_show.groups()
                    best = self._find_best_character_var(raw_char, script)
                    line = f"{prefix}{best}{suffix}"

                m_hide = re.match(r'^(\s*hide\s+)([a-zA-Z_][a-zA-Z0-9_]*)(.*)$', line)
                if m_hide:
                    prefix, raw_char, suffix = m_hide.groups()
                    best = self._find_best_character_var(raw_char, script)
                    line = f"{prefix}{best}{suffix}"

                m_say = re.match(r'^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s+)(\".*)$', line)
                if m_say:
                    indent, raw_char, space, rest = m_say.groups()
                    reserved = {"scene", "show", "hide", "jump", "call", "return", "menu", "with", "play", "stop"}
                    if raw_char not in reserved:
                        best = self._find_best_character_var(raw_char, script)
                        line = f"{indent}{best}{space}{rest}"

                rewritten.append(line)

            scene_file.write_text("\n".join(rewritten), encoding="utf-8")

    def _ensure_all_characters_defined(self, game_dir: Path, script: Script):
        scenes_dir = game_dir / "scenes"
        if not scenes_dir.exists():
            return

        used_chars: Set[str] = set()
        for scene_file in scenes_dir.glob("*.rpy"):
            content = scene_file.read_text(encoding="utf-8")
            for match in re.finditer(r'^(\w+)(?:\s+\w+)?\s+\"', content, re.MULTILINE):
                char_name = match.group(1)
                if char_name not in RESERVED_NAMES and char_name not in self._var_map.values():
                    used_chars.add(char_name)

        if not used_chars:
            return

        char_file = game_dir / "characters.rpy"
        existing = char_file.read_text(encoding="utf-8")
        new_lines = ['', '## 自动补全的缺失角色']
        colors = ["#C8FFC8", "#FFC8C8", "#C8C8FF", "#FFFFC8", "#FFC8FF", "#C8FFFF", "#FFCC99"]

        for char_name in sorted(used_chars):
            if f"define {char_name} =" not in existing:
                safe_name = self._sanitize_var_name(char_name)
                color = colors[len(self._var_map) % len(colors)]
                display_name = self._escape_renpy_text(char_name)

                new_lines.append(f'define {safe_name} = Character(_("{display_name}"), color="{color}")')
                if safe_name != char_name:
                    new_lines.append(f'define {char_name} = {safe_name}')
                self._var_map[char_name] = safe_name
                print(f"未定义角色，自动创建: {char_name} -> {safe_name}")

        if len(new_lines) > 2:
            char_file.write_text(existing + "\n" + "\n".join(new_lines), encoding="utf-8")

    def _write_script_entry(self, game_dir: Path, script: Script):
        start_scene = script.scenes[0].id if script.scenes else "scene_01"

        content = f'''## 系统生成的游戏入口
label start:
    jump {start_scene}
'''
        (game_dir / "script.rpy").write_text(content, encoding="utf-8")

    def _write_game_end_summary(self, game_dir: Path, script: Script):
        title = self._escape_renpy_text(script.title)
        char_count = len(script.characters)
        scene_count = len(script.scenes)
        seq_count = sum(len(s.sequences) for s in script.scenes)

        content = f'''## 系统生成的结算页
label game_end_summary:
    scene bg black
    with fade

    "本次故事已经结束。"
    "标题：《{title}》"
    "角色数：{char_count}"
    "场景数：{scene_count}"
    "总序列数：{seq_count}"
    "感谢游玩。"

    menu:
        "重新开始":
            jump start
        "结束游戏":
            return
'''
        (game_dir / "game_end_summary.rpy").write_text(content, encoding="utf-8")

    def _append_end_jump_to_leaf_scenes(self, game_dir: Path, script: Script):
        scenes_dir = game_dir / "scenes"
        if not scenes_dir.exists():
            return

        scene_ids = {scene.id for scene in script.scenes}

        for scene_file in scenes_dir.glob("*.rpy"):
            content = scene_file.read_text(encoding="utf-8")

            if "jump game_end_summary" in content:
                continue

            has_branch_jump = False
            for sid in scene_ids:
                if f"jump {sid}" in content:
                    has_branch_jump = True
                    break

            if has_branch_jump:
                continue

            lines = content.splitlines()

            while lines and lines[-1].strip() == "":
                lines.pop()

            if lines and lines[-1].strip() == "return":
                lines[-1] = "    jump game_end_summary"
            else:
                lines.append("    jump game_end_summary")

            scene_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _create_font_guide(self, game_dir: Path):
        guide_path = game_dir / "font" / "字体放置说明.txt"
        content = f"""VN Generator 字体配置说明

程序字体源目录:
{self.source_font_dir}

生成后字体会被复制到:
game/font/

推荐正文字体:
- SourceHanSansSC-Regular.otf
- NotoSansCJKsc-Regular.otf
- msyh.ttc
- simhei.ttf
- LXGWWenKai-Regular.ttf

注意:
1. 出现方块字时，请优先改用支持完整中文字符集的字体
2. 自动检测会优先尝试项目内中文字体，再尝试系统中文字体
3. 本项目已统一字号，避免不同字体忽大忽小
4. 分支结束会自动进入总结页，不会直接回到开头
"""
        guide_path.write_text(content, encoding="utf-8")

    def _generate_placeholders(self, game_dir: Path, script: Script):
        try:
            from PIL import Image, ImageDraw, ImageFont

            bg_dir = game_dir / "images" / "bg"
            bg_ids = {"black", "room", "office", "street", "school", "bedroom"}
            if script.backgrounds:
                bg_ids.update([b.id for b in script.backgrounds])

            for bg in bg_ids:
                target = bg_dir / f"{bg}.png"
                if target.exists():
                    continue

                img = Image.new('RGB', (1920, 1080), (25, 25, 35))
                draw = ImageDraw.Draw(img)
                draw.rectangle([2, 2, 1917, 1077], outline=(80, 80, 100), width=2)

                try:
                    font = ImageFont.truetype("arial.ttf", 80)
                except Exception:
                    font = ImageFont.load_default()

                label = f"[Background: {bg}]"
                bbox = draw.textbbox((0, 0), label, font=font)
                w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text(((1920 - w) / 2, (1080 - h) / 2), label, fill=(200, 200, 220), font=font)
                img.save(target)

            chars_dir = game_dir / "images" / "characters"
            for char in script.characters:
                char_dir = chars_dir / char.id
                char_dir.mkdir(parents=True, exist_ok=True)
                expressions = char.expressions if char.expressions else ["neutral", "happy", "sad"]

                for expr in expressions:
                    target = char_dir / f"{expr}.png"
                    if target.exists():
                        continue

                    img = Image.new('RGBA', (600, 800), (80, 80, 100, 255))
                    draw = ImageDraw.Draw(img)
                    try:
                        font = ImageFont.truetype("arial.ttf", 40)
                    except Exception:
                        font = ImageFont.load_default()

                    char_name = char.name if char.name else char.id
                    nb = draw.textbbox((0, 0), char_name, font=font)
                    draw.text(((600 - (nb[2] - nb[0])) / 2, 360), char_name,
                              fill=(255, 255, 255, 230), font=font)

                    eb = draw.textbbox((0, 0), f"[{expr}]", font=font)
                    draw.text(((600 - (eb[2] - eb[0])) / 2, 420), f"[{expr}]",
                              fill=(200, 200, 200, 200), font=font)

                    img.save(target)

        except ImportError:
            (game_dir / "images" / "PLACEHOLDER_GUIDE.txt").write_text(
                "请安装 Pillow 以自动生成占位图: pip install pillow",
                encoding="utf-8"
            )

    def _write_project_json(self, script: Script):
        project = {
            "name": script.title,
            "safe_name": self._sanitize_filename(script.title),
            "version": "1.0.0",
            "stats": {
                "characters": len(script.characters),
                "backgrounds": len(script.backgrounds),
                "scenes": len(script.scenes),
                "sequences": sum(len(s.sequences) for s in script.scenes)
            }
        }
        (self.output_path / "project.json").write_text(
            json.dumps(project, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def launch_preview(self) -> bool:
        import subprocess

        renpy_paths = [
            r"A:\Dev\RenPy\renpy-8.5.2-sdk\renpy.exe",
            "renpy.exe",
            "/Applications/RenPy/renpy.app/Contents/MacOS/renpy",
            "renpy",
        ]

        try:
            for renpy in renpy_paths:
                if shutil.which(renpy) or Path(renpy).exists():
                    subprocess.Popen([renpy, str(self.output_path)])
                    return True

            print(f"未找到 Ren'Py，请手动打开: {self.output_path}")
            return False
        except Exception as e:
            print(f"启动失败: {e}")
            return False
