"""一次性重生成 SVG（避免模块路径问题）。"""
import importlib.util
from pathlib import Path

gen_path = Path(__file__).parent / "generate_stadium_svg.py"
spec = importlib.util.spec_from_file_location("gen_stadium", gen_path)
gen = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(gen)
out = gen.OUT
out.write_text(gen.build_svg(), encoding="utf-8")
print(f"OK {out} ring100_rot={gen.RING_100_ROTATION:.1f}")
