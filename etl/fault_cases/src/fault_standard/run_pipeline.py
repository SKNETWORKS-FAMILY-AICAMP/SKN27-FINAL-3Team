"""Fault standard pipeline controller."""

import argparse
import subprocess
import sys
from pathlib import Path

STAGES = ("preprocess", "staging", "core", "search", "all")
BASE_DIR = Path(__file__).resolve().parent

def parse_stage_args() -> tuple[str, list[str]]:
    parser = argparse.ArgumentParser(description="Run the fault_standard pipeline.")
    parser.add_argument("--stage", choices=STAGES, default="all")
    args, remaining = parser.parse_known_args()
    return args.stage, remaining

def run_script(script_path: Path, args: list[str]) -> None:
    if not script_path.exists():
        print(f"[{script_path.name}] Not found: {script_path}", file=sys.stderr)
        sys.exit(1)
        
    cmd = [sys.executable, str(script_path), *args]
    print(f"\n[{script_path.name}] Running...")
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        print(f"[{script_path.name}] Failed with exit code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

def main() -> None:
    stage, remaining = parse_stage_args()
    
    stages_to_run = []
    if stage == "all":
        stages_to_run = list(STAGES[:-1])
    else:
        stages_to_run = [stage]

    for s in stages_to_run:
        if s == "preprocess":
            run_script(BASE_DIR / "preprocessing" / "run_all.py", remaining if stage == "preprocess" else [])
        elif s == "staging":
            run_script(BASE_DIR / "loading" / "run_staging_pipeline.py", remaining if stage == "staging" else [])
        elif s == "core":
            run_script(BASE_DIR / "loading" / "core" / "run_core_load.py", remaining if stage == "core" else [])
        elif s == "search":
            run_script(BASE_DIR / "loading" / "search" / "run_search_build.py", remaining if stage == "search" else [])

if __name__ == "__main__":
    main()
