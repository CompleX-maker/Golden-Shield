import os
import sys
import shutil
import time
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path if env_path.exists() else None)

BASE_DIR = Path(__file__).parent.resolve()
FONT_DIR = BASE_DIR / "font"

sys.path.insert(0, str(BASE_DIR))

from vn_generator.generator import VNGenerator
from vn_generator.renpy_builder import RenpyBuilder
from vn_generator.model_registry import (
    build_script_config,
    build_code_config,
    get_script_model_name,
    get_code_model_name,
    get_image_model_name,
    get_model_display_name,
    list_script_models,
    list_code_models,
    list_image_models,
)

SCRIPT_CONFIG = build_script_config()
CODE_CONFIG = build_code_config()


def env_bool(name: str, default: bool = False) -> bool:
    value = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return value in {"1", "true", "yes", "on", "y"}


def get_default_image_provider() -> str:
    provider = os.getenv("IMAGE_PROVIDER", "none").strip().lower()
    if provider == "gemini":
        provider = "remote_api"
    return provider if provider in {"none", "local_sd", "remote_api"} else "none"


def get_default_local_sd_url() -> str:
    return os.getenv("LOCAL_SD_BASE_URL", "http://127.0.0.1:7861").strip() or "http://127.0.0.1:7861"


def get_default_image_model(provider: str):
    env_model = os.getenv("IMAGE_MODEL", "").strip()

    if provider == "remote_api":
        return env_model or get_image_model_name()

    if provider == "local_sd":
        return r"sd1.5\anything-v5.safetensors [7f96a1a9ca]"

    return None


def get_local_sd_model_choices():
    configured = os.getenv("LOCAL_SD_MODEL_CHOICES", "").strip()
    if configured:
        values = [x.strip() for x in configured.split(",") if x.strip()]
        if values:
            return values

    return [
        r"sd1.5\anything-v5.safetensors [7f96a1a9ca]",
        "majicmixRealistic_v7",
        "awportrait_v11",
        "anything-v5",
        "ghostmix_v20",
        "dreamshaper_8",
    ]


def safe_get_font_choices():
    try:
        builder = RenpyBuilder(None, "./temp_font_check")
        fonts = builder.get_available_fonts(BASE_DIR)
        custom_fonts = [name for name in fonts.keys() if not name.startswith("[系统]") and not name.startswith("DejaVu")]
        system_fonts = [name for name in fonts.keys() if name.startswith("[系统]")]
        return ["自动检测"] + custom_fonts + system_fonts
    except Exception:
        return ["自动检测"]


def normalize_font(font_choice: str) -> str:
    if not font_choice or font_choice == "自动检测":
        return "auto"
    if font_choice.startswith("[系统]"):
        return font_choice
    return Path(font_choice).stem


IMAGE_MODEL_NAMES = list_image_models()
IMAGE_MODEL_DISPLAY_TO_NAME = {get_model_display_name(name): name for name in IMAGE_MODEL_NAMES}
IMAGE_MODEL_NAME_TO_DISPLAY = {name: get_model_display_name(name) for name in IMAGE_MODEL_NAMES}

PROVIDER_CHOICES = ["none", "local_sd"] + [get_model_display_name(name) for name in IMAGE_MODEL_NAMES]


def normalize_image_provider_selection(selection: str) -> tuple[str, str]:
    selection = (selection or "none").strip()

    if selection == "none":
        return "none", ""

    if selection == "local_sd":
        return "local_sd", get_default_image_model("local_sd") or r"sd1.5\anything-v5.safetensors [7f96a1a9ca]"

    if selection in IMAGE_MODEL_DISPLAY_TO_NAME:
        return "remote_api", IMAGE_MODEL_DISPLAY_TO_NAME[selection]

    lower_selection = selection.lower()
    if lower_selection == "gemini" or lower_selection == "remote_api":
        model_name = get_default_image_model("remote_api") or get_image_model_name()
        return "remote_api", model_name

    if selection in IMAGE_MODEL_NAME_TO_DISPLAY:
        return "remote_api", selection

    return "none", ""


def get_default_provider_selection() -> str:
    provider = get_default_image_provider()

    if provider == "local_sd":
        return "local_sd"

    if provider == "remote_api":
        model_name = get_default_image_model("remote_api") or get_image_model_name()
        return IMAGE_MODEL_NAME_TO_DISPLAY.get(model_name, get_model_display_name(model_name))

    return "none"


def build_generator() -> VNGenerator:
    return VNGenerator(
        script_llm_config=SCRIPT_CONFIG,
        code_llm_config=CODE_CONFIG
    )


def make_stage_html(title: str, percent: int, detail: str) -> str:
    return f"""
    <div class="stage-card">
        <div class="stage-head">
            <div class="stage-title">{title}</div>
            <div class="stage-percent">{percent}%</div>
        </div>
        <div class="stage-bar">
            <div class="stage-bar-fill" style="width:{percent}%;"></div>
        </div>
        <div class="stage-detail">{detail}</div>
    </div>
    """


def image_status_text(enabled: bool, provider: str, model_name: str, local_sd_url: str) -> str:
    if not enabled or provider == "none":
        return "图片生成：关闭"
    if provider == "local_sd":
        return f"图片生成：本地 SD / 模型 `{model_name or '未指定'}` / 地址 `{local_sd_url}`"
    return f"图片生成：{get_model_display_name(model_name) if model_name else '远程模型'} / 模型 `{model_name or get_image_model_name()}`"


def _run_generate(
    story_text: str,
    font_choice: str,
    image_enabled: bool,
    image_provider_selection: str,
    local_sd_base_url: str,
):
    if not story_text or not story_text.strip():
        yield (
            "请输入故事内容",
            make_stage_html("等待开始", 0, "请输入故事内容后再生成。"),
            None,
            ""
        )
        return

    start_time = time.time()

    provider, model_name = normalize_image_provider_selection(image_provider_selection)
    enabled = bool(image_enabled) and provider != "none"
    local_sd_base_url = (local_sd_base_url or get_default_local_sd_url()).strip()

    try:
        yield (
            "## 准备开始\n\n系统正在初始化任务环境。",
            make_stage_html("准备任务", 5, "初始化模型配置与任务参数"),
            None,
            ""
        )
        time.sleep(0.12)

        generator = build_generator()

        yield (
            "## 正在处理\n\n系统正在分析输入故事。",
            make_stage_html(
                "剧本分析中",
                18,
                f"使用 {get_model_display_name(get_script_model_name())} 提取人物、场景与主线"
            ),
            None,
            ""
        )
        time.sleep(0.12)

        yield (
            "## 正在处理\n\n系统正在组织剧情结构与分支路线。",
            make_stage_html("组织剧情", 35, "梳理剧情节奏、选择分支与结局结构"),
            None,
            ""
        )
        time.sleep(0.12)

        stage_detail = f"使用 {get_model_display_name(get_code_model_name())} 生成脚本、资源与工程文件"
        if enabled:
            stage_detail += "，并准备图片资源生成"

        yield (
            "## 正在处理\n\n开始构建 Ren'Py 工程。",
            make_stage_html(
                "代码构建中",
                55,
                stage_detail
            ),
            None,
            ""
        )

        result = generator.generate(
            user_input=story_text,
            output_base_path="./output",
            font_name=normalize_font(font_choice),
            image_enabled=enabled,
            image_provider_name=provider,
            image_model_name=model_name,
            local_sd_base_url=local_sd_base_url,
        )

        resource_detail = "写入字体、场景脚本、配置文件与占位资源"
        if enabled:
            resource_detail = "写入字体、场景脚本、配置文件，并生成背景图与角色立绘"

        yield (
            "## 正在处理\n\n系统正在整理资源并准备打包。",
            make_stage_html("资源整理中", 80, resource_detail),
            None,
            result.output_path or ""
        )

        output_dir = Path(result.output_path)
        zip_path = Path(f"{result.output_path}.zip")

        if zip_path.exists():
            zip_path.unlink()

        shutil.make_archive(str(output_dir), "zip", str(output_dir))

        elapsed = time.time() - start_time
        scene_count = len(result.script.scenes)
        char_count = len(result.script.characters)
        seq_count = sum(len(s.sequences) for s in result.script.scenes)

        summary = (
            "## 任务完成\n\n"
            f"**标题**：{result.script.title}\n\n"
            f"**本次剧本模型**：`{get_model_display_name(get_script_model_name())}`  \n"
            f"**本次代码模型**：`{get_model_display_name(get_code_model_name())}`  \n"
            f"**字体**：`{font_choice}`  \n"
            f"**{image_status_text(enabled, provider, model_name, local_sd_base_url)}**\n\n"
            f"**角色数**：{char_count}  \n"
            f"**场景数**：{scene_count}  \n"
            f"**总序列数**：{seq_count}\n\n"
            f"**输出目录**：`{result.output_path}`  \n"
            f"**ZIP 大小**：{zip_path.stat().st_size / 1024:.1f} KB  \n"
            f"**总耗时**：{elapsed:.1f} 秒"
        )

        yield (
            summary,
            make_stage_html("全部完成", 100, "剧本生成、代码构建、资源打包均已完成"),
            str(zip_path),
            str(output_dir)
        )

    except Exception as e:
        import traceback
        yield (
            f"## 生成失败\n\n```text\n{str(e)}\n\n{traceback.format_exc()}\n```",
            make_stage_html("任务失败", 100, "执行过程中出现异常，请查看详细报错信息"),
            None,
            ""
        )


def generate_from_text(
    story_text,
    font_choice,
    image_enabled,
    image_provider_selection,
    local_sd_base_url,
):
    yield from _run_generate(
        story_text=story_text,
        font_choice=font_choice,
        image_enabled=image_enabled,
        image_provider_selection=image_provider_selection,
        local_sd_base_url=local_sd_base_url,
    )


def generate_from_file(
    file_obj,
    font_choice,
    image_enabled,
    image_provider_selection,
    local_sd_base_url,
):
    if file_obj is None:
        yield (
            "请先上传文件",
            make_stage_html("等待开始", 0, "请先上传故事文件。"),
            None,
            ""
        )
        return

    try:
        file_path = Path(file_obj)
        suffix = file_path.suffix.lower()
        content = None

        yield (
            "## 正在读取文件\n\n系统正在读取上传的文件内容。",
            make_stage_html("文件读取中", 8, f"正在处理文件：{file_path.name}"),
            None,
            ""
        )

        if suffix == ".docx":
            try:
                from docx import Document
                content = "\n".join(
                    p.text for p in Document(file_path).paragraphs if p.text.strip()
                )
            except ImportError:
                yield (
                    "缺少依赖：pip install python-docx",
                    make_stage_html("任务失败", 100, "缺少 python-docx 依赖"),
                    None,
                    ""
                )
                return
            except Exception as e:
                yield (
                    f"Word 解析失败：{e}",
                    make_stage_html("任务失败", 100, "Word 文件解析失败"),
                    None,
                    ""
                )
                return

        elif suffix in [".txt", ".md"]:
            for enc in ["utf-8", "gbk", "gb2312", "utf-16", "latin-1"]:
                try:
                    content = file_path.read_text(encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
        else:
            yield (
                f"不支持的格式：{suffix}",
                make_stage_html("任务失败", 100, "当前文件格式不受支持"),
                None,
                ""
            )
            return

        if not content or not content.strip():
            yield (
                "文件内容为空",
                make_stage_html("任务失败", 100, "文件没有可用内容"),
                None,
                ""
            )
            return

        yield from _run_generate(
            content,
            font_choice,
            image_enabled,
            image_provider_selection,
            local_sd_base_url,
        )

    except Exception as e:
        import traceback
        yield (
            f"文件读取失败：{str(e)}\n\n{traceback.format_exc()}",
            make_stage_html("任务失败", 100, "文件读取阶段发生异常"),
            None,
            ""
        )


def on_provider_change(selection: str):
    provider, _ = normalize_image_provider_selection(selection)

    if provider == "local_sd":
        return gr.update(
            value=get_default_local_sd_url(),
            visible=True,
        )

    return gr.update(
        value=get_default_local_sd_url(),
        visible=False,
    )


font_choices = safe_get_font_choices()
default_image_provider = get_default_image_provider()
default_image_enabled = env_bool("IMAGE_ENABLED", False) and default_image_provider != "none"
default_provider_selection = get_default_provider_selection()

CSS = """
:root {
    --bg: #0b1020;
    --panel: #121b31;
    --panel-2: #172340;
    --line: rgba(255,255,255,0.08);
    --text: #edf2ff;
    --muted: #9aa8c7;
    --primary: #6b5cff;
    --primary-2: #3f87ff;
    --good: #3bd671;
    --shadow: 0 12px 30px rgba(0,0,0,0.28);
    --input-bg: #18233f;
    --input-bg-2: #1b2746;
}

html, body, .gradio-container {
    background:
        radial-gradient(circle at top left, rgba(107,92,255,0.16), transparent 28%),
        radial-gradient(circle at top right, rgba(63,135,255,0.13), transparent 24%),
        linear-gradient(180deg, #0a0f1d 0%, #0b1020 100%) !important;
    color: var(--text) !important;
    font-family: "Inter", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif !important;
}

.main-wrap {
    max-width: 1320px;
    margin: 0 auto;
    padding-bottom: 24px;
}

.hero {
    background: linear-gradient(135deg, rgba(107,92,255,0.18), rgba(63,135,255,0.10));
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 22px;
    padding: 24px 28px;
    box-shadow: var(--shadow);
    margin-bottom: 18px;
}

.hero-title {
    font-size: 34px;
    font-weight: 800;
    color: #fff;
    margin-bottom: 6px;
}

.hero-sub {
    color: var(--muted);
    font-size: 14px;
    line-height: 1.8;
}

.status-strip {
    display: flex;
    gap: 18px;
    flex-wrap: wrap;
    margin-top: 14px;
    color: #dbe6ff;
    font-size: 13px;
}

.status-item {
    display: flex;
    align-items: center;
    gap: 8px;
}

.status-dot {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    background: var(--good);
    box-shadow: 0 0 12px rgba(59,214,113,0.45);
}

.card {
    background: linear-gradient(180deg, rgba(19,28,50,0.98), rgba(15,22,40,0.98));
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 18px;
    padding: 18px;
    box-shadow: var(--shadow);
    height: 100%;
}

.card-title {
    font-size: 18px;
    font-weight: 800;
    color: #ffffff;
    margin-bottom: 14px;
}

.image-box {
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid rgba(255,255,255,0.08);
}

.image-subtitle {
    font-size: 15px;
    font-weight: 700;
    color: #ffffff;
    margin-bottom: 8px;
}

.image-helper {
    color: var(--muted);
    font-size: 12px;
    line-height: 1.7;
    margin-bottom: 10px;
}

footer { display: none !important; }

.gradio-container .block {
    border: none !important;
    background: transparent !important;
}

.gradio-container label,
.gradio-container .prose,
.gradio-container .prose p,
.gradio-container .prose li,
.gradio-container .prose strong,
.gradio-container .prose code {
    color: var(--text) !important;
}

textarea, input, select {
    background: var(--input-bg) !important;
    color: #edf2ff !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 14px !important;
    min-height: 52px !important;
}

textarea::placeholder, input::placeholder {
    color: #90a0c5 !important;
}

.gradio-container .gr-textbox textarea,
.gradio-container .gr-textbox input {
    background: var(--input-bg) !important;
}

.gradio-container .gr-dropdown,
.gradio-container .gr-dropdown > div,
.gradio-container .gr-dropdown input,
.gradio-container .gr-dropdown button {
    background: var(--input-bg-2) !important;
    color: #edf2ff !important;
}

button {
    border-radius: 14px !important;
    font-weight: 700 !important;
}

.big-btn button {
    height: 56px !important;
    font-size: 17px !important;
    background: linear-gradient(90deg, var(--primary), var(--primary-2)) !important;
    color: #fff !important;
    border: none !important;
    box-shadow: 0 10px 24px rgba(107,92,255,0.30) !important;
}

.big-btn button:hover {
    filter: brightness(1.08);
}

.result-box {
    min-height: 250px;
}

.compact-gap {
    gap: 16px !important;
}

.stage-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 16px;
    margin-bottom: 14px;
}

.stage-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
}

.stage-title {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
}

.stage-percent {
    font-size: 14px;
    color: #d5e0ff;
}

.stage-bar {
    width: 100%;
    height: 10px;
    border-radius: 999px;
    background: rgba(255,255,255,0.08);
    overflow: hidden;
    margin-bottom: 10px;
}

.stage-bar-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, #6b5cff, #3f87ff);
}

.stage-detail {
    color: var(--muted);
    font-size: 13px;
    line-height: 1.7;
}

.path-box textarea,
.path-box input {
    min-height: 40px !important;
    height: 40px !important;
}
"""

usage_text = (
    f"**当前配置**\n\n"
    f"- 剧本模型：`{get_model_display_name(get_script_model_name())}`\n"
    f"- 代码模型：`{get_model_display_name(get_code_model_name())}`\n"
    f"- 已注册剧本模型：`{', '.join(get_model_display_name(x) for x in list_script_models())}`\n"
    f"- 已注册代码模型：`{', '.join(get_model_display_name(x) for x in list_code_models())}`\n"
    f"- 已注册图片模型：`{', '.join(get_model_display_name(x) for x in list_image_models())}`\n"
    f"- 字体目录：`{FONT_DIR}`\n\n"
    f"**使用建议**\n\n"
    f"- 故事描述越详细，生成的场景与分支越丰富\n"
    f"- 可以主动写明人物关系、冲突目标、关键转折和多结局要求\n"
    f"- 如果需要好结局 / 坏结局 / 普通结局，建议在故事中直接说明\n"
    f"- 中文文字建议选择：思源黑体 / 微软雅黑 / Noto Sans CJK\n"
    f"- 若出现方块字，请检查字体是否支持完整中文字符集\n"
    f"- 上传文件时优先使用 UTF-8 编码的 txt 或 md 文件\n"
    f"- 如果启用本地 SD，请确认 7861 端口已开启 API\n"
)

with gr.Blocks(title="VN Generator", css=CSS, theme=gr.themes.Base()) as demo:
    with gr.Column(elem_classes=["main-wrap"]):
        gr.HTML(
            f"""
            <div class="hero">
                <div class="hero-title">VN Generator</div>
                <div class="hero-sub">将故事快速生成可运行的 Ren'Py 视觉小说工程。</div>
                <div class="status-strip">
                    <div class="status-item"><span class="status-dot"></span><span>剧本接口已通过启动检测</span></div>
                    <div class="status-item"><span class="status-dot"></span><span>代码接口已通过启动检测</span></div>
                    <div class="status-item"><span class="status-dot"></span><span>当前剧本模型：{get_model_display_name(get_script_model_name())}</span></div>
                    <div class="status-item"><span class="status-dot"></span><span>当前代码模型：{get_model_display_name(get_code_model_name())}</span></div>
                </div>
            </div>
            """
        )

        with gr.Row(equal_height=True, elem_classes=["compact-gap"]):
            with gr.Column(scale=12):
                with gr.Column(elem_classes=["card"]):
                    gr.HTML('<div class="card-title">使用说明</div>')
                    gr.Markdown(usage_text)

        with gr.Row(equal_height=True, elem_classes=["compact-gap"]):
            with gr.Column(scale=7):
                with gr.Tabs():
                    with gr.Tab("文本输入"):
                        with gr.Column(elem_classes=["card"]):
                            gr.HTML('<div class="card-title">故事输入</div>')
                            text_input = gr.Textbox(
                                label="故事内容",
                                lines=16,
                                placeholder=(
                                    "输入你的故事，越详细生成质量越高。\n\n"
                                    "示例：一个关于电信诈骗的悬疑故事，主角是退休老人林桂芳，"
                                    "被骗子冒充公安套取积蓄。故事有三条分支：识破骗局、半途觉醒、"
                                    "被骗到底，对应好、普通、坏三种结局。"
                                )
                            )

                            with gr.Row():
                                font_dropdown = gr.Dropdown(
                                    label="字体",
                                    choices=font_choices,
                                    value="自动检测",
                                    scale=1
                                )
                                text_gen_btn = gr.Button(
                                    "生成游戏",
                                    variant="primary",
                                    elem_classes=["big-btn"],
                                    scale=1
                                )

                            gr.HTML('<div class="image-box"><div class="image-subtitle">图片生成设置</div><div class="image-helper">勾选后启用图片生成。远程图片模型已直接合并到“图片提供方”里；本地模式使用默认本地 SD 模型。</div></div>')

                            with gr.Row():
                                text_image_enabled = gr.Checkbox(
                                    label="",
                                    value=default_image_enabled,
                                    scale=1
                                )
                                text_image_provider = gr.Dropdown(
                                    label="图片提供方",
                                    choices=PROVIDER_CHOICES,
                                    value=default_provider_selection,
                                    scale=4
                                )

                            text_local_sd_url = gr.Textbox(
                                label="Local SD Base URL",
                                value=get_default_local_sd_url(),
                                visible=(default_image_provider == "local_sd"),
                                placeholder="http://127.0.0.1:7861"
                            )

                    with gr.Tab("文件导入"):
                        with gr.Column(elem_classes=["card"]):
                            gr.HTML('<div class="card-title">文件导入</div>')
                            file_input = gr.File(
                                label="上传故事文件（TXT / MD / DOCX）",
                                file_types=[".txt", ".md", ".docx"],
                                type="filepath"
                            )

                            with gr.Row():
                                font_dropdown_file = gr.Dropdown(
                                    label="字体",
                                    choices=font_choices,
                                    value="自动检测",
                                    scale=1
                                )
                                file_gen_btn = gr.Button(
                                    "从文件生成",
                                    variant="primary",
                                    elem_classes=["big-btn"],
                                    scale=1
                                )

                            gr.HTML('<div class="image-box"><div class="image-subtitle">图片生成设置</div><div class="image-helper">文件模式与文本模式的图片配置分开保存。远程图片模型已直接合并到“图片提供方”里；本地模式使用默认本地 SD 模型。</div></div>')

                            with gr.Row():
                                file_image_enabled = gr.Checkbox(
                                    label="",
                                    value=default_image_enabled,
                                    scale=1
                                )
                                file_image_provider = gr.Dropdown(
                                    label="图片提供方",
                                    choices=PROVIDER_CHOICES,
                                    value=default_provider_selection,
                                    scale=4
                                )

                            file_local_sd_url = gr.Textbox(
                                label="Local SD Base URL",
                                value=get_default_local_sd_url(),
                                visible=(default_image_provider == "local_sd"),
                                placeholder="http://127.0.0.1:7861"
                            )

            with gr.Column(scale=5):
                with gr.Column(elem_classes=["card"]):
                    gr.HTML('<div class="card-title">任务结果</div>')

                    stage_html = gr.HTML(
                        value=make_stage_html("等待开始", 0, "提交故事后，系统将在这里显示当前阶段。")
                    )

                    result_md = gr.Markdown(
                        value=(
                            "等待生成。\n\n"
                            "- 标题、场景数、序列数会在这里显示\n"
                            "- 生成完成后可直接下载 ZIP"
                        ),
                        elem_classes=["result-box"]
                    )

                    with gr.Row():
                        download_file = gr.File(label="下载 ZIP", interactive=False)
                        path_text = gr.Textbox(
                            label="项目路径",
                            interactive=False,
                            elem_classes=["path-box"]
                        )

    text_image_provider.change(
        fn=on_provider_change,
        inputs=[text_image_provider],
        outputs=[text_local_sd_url]
    )

    file_image_provider.change(
        fn=on_provider_change,
        inputs=[file_image_provider],
        outputs=[file_local_sd_url]
    )

    text_gen_btn.click(
        fn=generate_from_text,
        inputs=[
            text_input,
            font_dropdown,
            text_image_enabled,
            text_image_provider,
            text_local_sd_url,
        ],
        outputs=[result_md, stage_html, download_file, path_text]
    )

    file_gen_btn.click(
        fn=generate_from_file,
        inputs=[
            file_input,
            font_dropdown_file,
            file_image_enabled,
            file_image_provider,
            file_local_sd_url,
        ],
        outputs=[result_md, stage_html, download_file, path_text]
    )


if __name__ == "__main__":
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))

    print("WEBUI_VERSION = IMAGE_PROVIDER_MERGED_WITH_REMOTE_MODELS", flush=True)
    print("VN Generator 启动", flush=True)
    print(f"  剧本模型: {get_model_display_name(get_script_model_name())}", flush=True)
    print(f"  代码模型: {get_model_display_name(get_code_model_name())}", flush=True)
    print(f"  默认图片提供方: {default_provider_selection}", flush=True)
    print(f"  默认图片模型: {get_default_image_model(default_image_provider)}", flush=True)
    print(f"  Local SD URL: {get_default_local_sd_url()}", flush=True)
    print(f"  字体数量: {len(font_choices) - 1}", flush=True)
    print(f"  WebUI 地址: http://127.0.0.1:{server_port}", flush=True)

    demo.launch(
        server_name="127.0.0.1",
        server_port=server_port,
        share=False,
        show_error=True
    )
