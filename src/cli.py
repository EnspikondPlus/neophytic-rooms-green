# src/cli.py
import asyncio
import argparse
import sys
from pathlib import Path

from .benchmark_config import BenchmarkConfig
from .benchmark_runner import BenchmarkRunner

def parse_range(range_str: str) -> slice:
    """Parse string like '1-100' or '5' into a slice."""
    try:
        if '-' in range_str:
            start, end = map(int, range_str.split('-'))
            return slice(start - 1, end)
        else:
            idx = int(range_str)
            return slice(idx - 1, idx)
    except ValueError:
        print(f"Error: Invalid range format '{range_str}'. Use format '1-100' or '5'.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="AgentBeats Green Agent - CLI Benchmark Runner")
    
    # Connection args
    parser.add_argument("--purple-url", required=True, help="URL of the Purple (Solver) Agent (e.g. http://localhost:8000)")
    parser.add_argument("--output", default="benchmark_results.json", help="Path to save results JSON")
    
    # Task Selection
    parser.add_argument("--categories", nargs="+", default=["all"], help="Categories to run (tutorial, basic, advanced) or 'all'")
    parser.add_argument("--task-range", help="Range of tasks to run (e.g., '1-50' or '10'). Applies after category filtering.")
    
    # Hyperparameters
    parser.add_argument("--max-steps", type=int, default=50, help="Max steps per episode")
    parser.add_argument("--steps-remaining", type=int, default=30, help="Initial step budget")
    parser.add_argument("--obs-inspect-weight", type=float, default=3.0, help="Cost of INSPECT action")
    parser.add_argument("--no-failure-show", action="store_true", help="Disable showing failure signals")
    parser.add_argument("--consequence", action="store_true", help="Enable failure consequences (penalties)")
    parser.add_argument("--reset-on-commit", action="store_true", help="Reset environment on commit")
    
    args = parser.parse_args()

    # Build Configuration
    config = BenchmarkConfig(
        categories=args.categories,
        max_steps=args.max_steps,
        steps_remaining=args.steps_remaining,
        obs_inspect_weight=args.obs_inspect_weight,
        failure_show=not args.no_failure_show,
        failure_consequence=args.consequence,
        commit_reset=args.reset_on_commit
    )

    runner = BenchmarkRunner(config)
    
    if args.task_range:
        original_get_cases = runner.database.get_cases
        
        def sliced_get_cases(categories=None):
            cases = original_get_cases(categories)
            sl = parse_range(args.task_range)
            return cases[sl]
            
        runner.database.get_cases = sliced_get_cases

    # Run Benchmark
    try:
        asyncio.run(runner.run_benchmark_suite(
            purple_agent_url=args.purple_url,
            output_path=args.output
        ))
    except KeyboardInterrupt:
        print("\n\n⚠️ Benchmark interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()