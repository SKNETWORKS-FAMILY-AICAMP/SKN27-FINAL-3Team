"""Master ETL orchestrator for fault_cases.

Coordinates the pipeline execution for review_case, fault_standard, and traffic_precedents.
Finishes by detailing the unified Qwen4 embedding process for successful pipelines.
"""

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DOMAINS = ["review_case", "fault_standard", "traffic_precedents"]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Master orchestrator for all fault_cases ETL pipelines.")
    parser.add_argument("--skip-crawl", action="store_true", help="Skip crawling stages.")
    parser.add_argument("--skip-classify", action="store_true", help="Skip heavy AI classification stages in traffic_precedents.")
    parser.add_argument("--exclude-domains", nargs="+", choices=DOMAINS, default=[], help="Domains to completely exclude from execution.")
    parser.add_argument("--ignore-errors", action="store_true", help="Continue to next domain even if one fails.")
    return parser.parse_args()

def run_domain_pipeline(domain: str, args: argparse.Namespace) -> bool:
    """Run a specific domain pipeline and return True if successful."""
    print(f"\n{'='*60}\n[MASTER] Starting domain pipeline: {domain}\n{'='*60}")
    
    script_path = BASE_DIR / domain / "run_pipeline.py"
    if not script_path.exists():
        print(f"[MASTER] Warning: {script_path} not found.", file=sys.stderr)
        return False
        
    stages = ["all"]
    
    if args.skip_crawl and domain in ("review_case", "traffic_precedents"):
        if domain == "review_case":
            stages = ["preprocess", "schema", "load"]
        elif domain == "traffic_precedents":
            stages = ["preprocess"]
            if not args.skip_classify:
                stages.extend(["classify1", "verify1", "classify2", "verify2"])
            stages.extend(["chunk", "load"])
    elif args.skip_classify and domain == "traffic_precedents":
        stages = ["crawl", "preprocess", "chunk", "load"]
        
    for stage in stages:
        cmd = [sys.executable, str(script_path), "--stage", stage]
        print(f"[MASTER] Executing: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(BASE_DIR))
        
        if result.returncode != 0:
            print(f"[MASTER] Error: {domain} pipeline failed at stage '{stage}'!", file=sys.stderr)
            if not args.ignore_errors:
                return False
            else:
                print(f"[MASTER] --ignore-errors is set. Ignoring {domain} failure and continuing.")
                return False

    print(f"[MASTER] Successfully completed domain: {domain}")
    return True

def main() -> None:
    args = parse_args()
    
    successful_domains = []
    
    for domain in DOMAINS:
        if domain in args.exclude_domains:
            print(f"\n[MASTER] Skipping domain: {domain} (--exclude-domains)")
            continue
            
        success = run_domain_pipeline(domain, args)
        if success:
            successful_domains.append(domain)
        else:
            if not args.ignore_errors:
                print(f"\n[MASTER] Aborting master pipeline due to failure in {domain}.")
                sys.exit(1)
                
    if not successful_domains:
        print("\n[MASTER] No domains were successfully processed. Skipping final output.")
        sys.exit(1)
        
    print(f"\n{'='*60}\n[MASTER] All local ETL pipelines finished.\n[MASTER] Successful domains: {', '.join(successful_domains)}\n{'='*60}")
    
    print("\n[MASTER] Local preprocessing and DB loading are complete.")
    print("[MASTER] To perform unified Qwen4 embedding on a GPU instance, generate the bundle next:")
    print("         python -m etl.fault_cases.src.shared_embedding.qwen4_operational.build_runpod_bundle --run-id <id> --source-root ...")
    print("\n[MASTER] Master pipeline execution finished successfully.")

if __name__ == "__main__":
    main()
