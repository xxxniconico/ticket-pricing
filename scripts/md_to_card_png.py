#!/usr/bin/env python3
"""把精简版决策卡 Markdown 渲染成单张长图（PNG）。

用法：python scripts/md_to_card_png.py <input.md> <output.png> [标题]
流程：markdown → 内嵌 CSS 的 HTML → Chrome headless 截图 → PIL 裁掉底部空白
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import markdown
from PIL import Image

CHROME = "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"

CSS = """
@page { size: 1240px 20000px; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  width: 1240px; padding: 40px 48px 30px;
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  color: #1b2430; background: #fff; line-height: 1.55; font-size: 15px;
}
h1 { font-size: 30px; color: #0b3d91; border-left: 8px solid #0b3d91;
     padding-left: 16px; margin-bottom: 10px; letter-spacing: .3px; }
h2 { font-size: 19px; color: #fff; background: #0b3d91; padding: 7px 14px;
     border-radius: 5px; margin: 26px 0 12px; display: inline-block; }
h3 { font-size: 16px; color: #12365f; margin: 18px 0 8px;
     border-bottom: 2px solid #e3ebf6; padding-bottom: 4px; }
blockquote { background: #f4f7fc; border-left: 4px solid #6c8fc4; padding: 10px 14px;
             margin: 12px 0; color: #33475f; font-size: 14px; border-radius: 4px; }
blockquote p { margin: 4px 0; }
p { margin: 9px 0; }
ul, ol { margin: 9px 0 9px 26px; }
li { margin: 5px 0; }
table { width: 100%; border-collapse: collapse; font-size: 14px; margin: 12px 0; }
th { background: #eaf0f9; color: #12365f; padding: 8px 6px; font-weight: 700;
     border-bottom: 2px solid #0b3d91; text-align: center; }
td { padding: 6px; text-align: center; border-bottom: 1px solid #e6ecf4; }
td:first-child, th:first-child { text-align: left; padding-left: 12px; }
tr:last-child td { background: #f7f9fc; font-weight: 600; }
strong { color: #0b3d91; }
code { background: #f0f3f8; padding: 1px 5px; border-radius: 3px;
       font-family: Consolas, monospace; font-size: 13px; color: #b03060; }
hr { border: none; border-top: 1px solid #e6ecf4; margin: 20px 0; }
em { color: #6b7c93; font-size: 13.5px; }
"""


def build_html(md_text: str) -> str:
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>{CSS}</style></head><body>{body}</body></html>"""


def to_win(p: str | Path) -> str:
    """WSL 路径 → Windows 路径（Chrome 是 Windows 程序，只认后者）。"""
    s = str(p)
    if s.startswith("/mnt/") and len(s) > 6:
        parts = s.split("/")
        return parts[2].upper() + ":\\" + "\\".join(parts[3:])
    return s


def shot(html_path: Path, png_path: Path, height: int = 9000) -> None:
    url = "file:///" + to_win(html_path).replace("\\", "/")
    r = subprocess.run([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", f"--screenshot={to_win(png_path)}",
        f"--window-size=1240,{height}", url,
    ], capture_output=True, timeout=180)
    if not Path(png_path).exists():
        print("CHROME stderr:", r.stderr.decode(errors="ignore")[:800])
        raise SystemExit("截图失败")


def trim(png_path: Path) -> tuple[int, int]:
    im = Image.open(png_path).convert("RGB")
    w, h = im.size
    px = im.load()
    last = 0
    for y in range(h - 1, -1, -1):
        row_nonwhite = any(sum(px[x, y]) < 740 for x in range(0, w, 7))
        if row_nonwhite:
            last = y
            break
    out_h = min(h, last + 34)
    im.crop((0, 0, w, out_h)).save(png_path, optimize=True)
    return w, out_h


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: md_to_card_png.py <in.md> <out.png>")
        return 1
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    md_text = src.read_text(encoding="utf-8")
    # 去掉纯 Markdown 版本的页脚分隔（保留内容）
    tmp_dir = Path("/mnt/c/Users/xxxsu/AppData/Local/Temp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    html_path = tmp_dir / "_card_render.html"
    html_path.write_text(build_html(md_text), encoding="utf-8")
    shot(html_path, dst)
    w, h = trim(dst)
    print(f"✅ {dst.name}  {w}x{h}  {dst.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
