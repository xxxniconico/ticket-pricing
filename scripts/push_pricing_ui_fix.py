#!/usr/bin/env python3
"""Push pending dashboard fix to GitHub (non-interactive)."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
env = {**os.environ, "GIT_EDITOR": "true", "GIT_TERMINAL_PROMPT": "0"}

subprocess.run(["git", "add", "dashboard/components/pricing_ui.py"], check=True, env=env)

r = subprocess.run(["git", "diff", "--cached", "--quiet"], env=env)
if r.returncode == 0:
    print("Nothing to commit")
    sys.exit(0)

subprocess.run(
    ["git", "commit", "-m", "Fix PENALTY_FLOOR NameError in render_cumulative_bar (function-local import)."],
    check=True,
    env=env,
)
subprocess.run(["git", "push", "origin", "master"], check=True, env=env)
subprocess.run(["git", "log", "-1", "--oneline"], check=True, env=env)
print("PUSH_OK")
