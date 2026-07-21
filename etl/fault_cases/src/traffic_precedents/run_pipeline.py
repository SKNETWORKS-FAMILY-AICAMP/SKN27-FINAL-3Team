"""Traffic precedents pipeline controller."""

import argparse
import subprocess
import sys
from pathlib import Path

STAGES = ("crawl", "preprocess", "classify1", "verify1", "classify2", "verify2", "chunk", "load", "all")
BASE_DIR = Path(__file__).resolve().parent

def parse_stage_args() -> tuple[str, list[str]]:
    parser = argparse.ArgumentParser(description="Run the traffic_precedents pipeline.")
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
        if s == "crawl":
            run_script(BASE_DIR / "traffic_precedents_crawling" / "traffic_prec_api_collector_all_raw_commented.py", remaining if stage == "crawl" else [])
        elif s == "preprocess":
            run_script(BASE_DIR / "traffic_precedents_preprocessing" / "preprocess_run.py", remaining if stage == "preprocess" else [])
        elif s == "classify1":
            run_script(BASE_DIR / "traffic_precedents_1st_classification-traffic accident" / "traffic_relevance_reclassifier_stage1.py", remaining if stage == "classify1" else [])
        elif s == "verify1":
            run_script(BASE_DIR / "traffic_precedents_1st_classification-verification" / "traffic_relevance_recheck.py", remaining if stage == "verify1" else [])
        elif s == "classify2":
            run_script(BASE_DIR / "traffic_precedents_2nd_classification-fault_ratio" / "traffic_fault_ratio_stage2.py", remaining if stage == "classify2" else [])
        elif s == "verify2":
            run_script(BASE_DIR / "traffic_precedents_2nd_classification-verification" / "traffic_fault_ratio_recheck.py", remaining if stage == "verify2" else [])
        elif s == "chunk":
            run_script(BASE_DIR / "precedent_chunking" / "build_fault_ratio_precedent_chunks.py", remaining if stage == "chunk" else [])
        elif s == "load":
            run_script(BASE_DIR / "precedent_db_loading" / "schema_loader.py", [])
            run_script(BASE_DIR / "precedent_db_loading" / "load_traffic_precedents.py", [])
            run_script(BASE_DIR / "precedent_db_loading" / "load_fault_ratio_precedents.py", remaining if stage == "load" else [])

if __name__ == "__main__":
    main()
