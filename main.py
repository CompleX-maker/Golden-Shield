import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path if env_path.exists() else None)

from vn_generator.generator import VNGenerator
from vn_generator.renpy_builder import RenpyBuilder
from vn_generator.model_registry import (
    build_script_config,
    build_code_config,
    get_script_model_name,
    get_code_model_name,
)


def list_available_fonts():
    builder = RenpyBuilder(None, "./temp_check")
    fonts = builder.get_available_fonts(Path(__file__).parent)

    print("\n可用字体列表：")
    print("-" * 40)

    custom_fonts = {k: v for k, v in fonts.items() if not k.startswith("DejaVu")}
    system_fonts = {k: v for k, v in fonts.items() if k.startswith("[系统]")}
    custom_only = {k: v for k, v in custom_fonts.items() if not k.startswith("[系统]")}

    if custom_only:
        print("自定义字体 (font/ 目录):")
        for i, (name, path) in enumerate(custom_only.items(), 1):
            print(f"  {i}. {name}  ({path})")

    if system_fonts:
        offset = len(custom_only) + 1
        print("\n系统字体:")
        for i, (name, path) in enumerate(system_fonts.items(), offset):
            print(f"  {i}. {name}  ({path})")

    if not custom_only and not system_fonts:
        print("  未检测到任何字体，将使用 DejaVuSans（可能显示方块）")
        print("  提示：将 .ttf/.otf/.ttc 字体文件放入 font/ 目录")

    print("-" * 40)
    return list(fonts.keys())


def main():
    script_config = build_script_config()
    code_config = build_code_config()

    generator = VNGenerator(
        script_llm_config=script_config,
        code_llm_config=code_config
    )

    print("=" * 60)
    print("视觉小说生成器")
    print("-" * 60)
    print(f"剧本模型: {get_script_model_name()}")
    print(f"代码模型: {get_code_model_name()}")
    print("=" * 60)

    available_fonts = list_available_fonts()

    print("\n请选择字体（直接回车使用自动检测）：")
    font_choice = input("> ").strip()

    selected_font = "auto"
    if font_choice:
        try:
            idx = int(font_choice) - 1
            if 0 <= idx < len(available_fonts):
                selected_font = available_fonts[idx]
                print(f"已选择: {selected_font}")
            else:
                print("无效序号，使用自动检测")
        except ValueError:
            if font_choice in available_fonts:
                selected_font = font_choice
                print(f"已选择: {selected_font}")
            else:
                print(f"未找到字体 '{font_choice}'，使用自动检测")

    print("\n输入故事内容，空行结束：")
    lines = []
    while True:
        try:
            line = input()
            if line.strip() == "" and lines:
                break
            lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print("\n已中断")
            sys.exit(0)

    story = "\n".join(lines).strip()
    if not story:
        print("未输入内容，退出")
        return

    print(f"\n收到故事 ({len(story)} 字符)")
    print(f"使用字体: {selected_font}")
    print("开始生成...")

    try:
        result = generator.generate(
            user_input=story,
            output_base_path="./output",
            font_name=selected_font
        )

        print("\n" + "=" * 60)
        print("生成完成")
        print(f"标题:  {result.script.title}")
        print(f"角色:  {len(result.script.characters)} 个")
        print(f"场景:  {len(result.script.scenes)} 个")
        print(f"字体:  {selected_font}")
        print(f"路径:  {result.output_path}")
        print("=" * 60)

    except Exception as e:
        print(f"\n生成失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
