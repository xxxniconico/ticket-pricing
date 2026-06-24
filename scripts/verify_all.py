#!/usr/bin/env python3
"""一键运行全部阶段验证脚本。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [
    ("phase1", "verify_phase1.py"),
    ("phase4", "verify_phase4.py"),
    ("mae", "verify_mae_regression.py"),
    ("backtest", "backtest_summary.py"),
]


def main():
    failed = []
    for name, script in SCRIPTS:
        path = ROOT / "scripts" / script
        print(f"\n--- {name}: {script} ---")
        r = subprocess.run([sys.executable, str(path)], cwd=str(ROOT))
        if r.returncode != 0:
            failed.append(name)
    if failed:
        print(f"\nVERIFY_ALL_FAIL: {', '.join(failed)}")
        return 1
    print("\nVERIFY_ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
