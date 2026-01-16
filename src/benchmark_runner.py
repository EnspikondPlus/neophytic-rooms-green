import asyncio
import json
import re
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from pydantic import HttpUrl

# Adjust relative imports based on your structure
from .benchmark_config import BenchmarkDatabase, BenchmarkConfig, BenchmarkCase
from .messenger import Messenger
from .agent import Agent
from a2a.types import Message, Part, TextPart, Role
from uuid import uuid4
from .local_runtime import LocalTaskUpdater


class BenchmarkRunner:
    """Runs benchmark suite against a purple agent."""
    
    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.database = BenchmarkDatabase()
        self.messenger = Messenger()
    
    async def run_benchmark_suite(
        self,
        purple_agent_url: str,
        output_path: str = None  # This is now treated as a "base name" or ignored if auto-generating
    ) -> Dict[str, Any]:
        """Run full benchmark suite against a purple agent."""
        print(f"\n{'='*60}")
        print(f"🟢 Running Rooms Benchmark Suite")
        print(f"{'='*60}")
        print(f"Purple Agent: {purple_agent_url}")
        print(f"Categories: {', '.join(self.config.categories)}")
        print(f"Max Steps: {self.config.max_steps}")
        print(f"{'='*60}\n")
        
        # Get test cases
        cases = self.database.get_cases(self.config.categories)
        print(f"📋 Loaded {len(cases)} test cases\n")
        
        # Run each test case
        results = []
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] Running: {case.id} ({case.difficulty})")
            print(f"  Description: {case.description}")
            
            result = await self._run_single_case(case, purple_agent_url)
            results.append(result)
            
            # Print result
            status = "✅ PASS" if result.get("success") else "❌ FAIL"
            steps = result.get("steps_taken", 0)
            reward = result.get("total_reward", 0.0)
            print(f"  {status} - Reward: {reward:.2f}, Steps: {steps}\n")
        
        # Compile summary
        summary = self._compile_summary(results, cases)
        
        # --- NEW LOGGING LOGIC ---
        # 1. Determine log directory
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # 2. Generate timestamped filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        if output_path:
            # If user provided a specific path (e.g. "my_run.json"), 
            # insert timestamp before extension: "my_run_2023-10-27_10-00-00.json"
            p = Path(output_path)
            stem = p.stem
            suffix = p.suffix
            filename = f"{stem}_{timestamp}{suffix}"
            final_path = log_dir / filename
        else:
            # Default name
            final_path = log_dir / f"benchmark_results_{timestamp}.json"
        
        self._save_results(summary, str(final_path))
        
        self._print_summary(summary)
        
        return summary
    
    async def _run_single_case(
        self,
        case: BenchmarkCase,
        purple_agent_url: str
    ) -> Dict[str, Any]:
        """Run a single benchmark case."""
        
        request_payload = {
            "participants": {
                "solver": purple_agent_url
            },
            "config": {
                "encoding": case.encoding,
                "max_steps": self.config.max_steps,
                "steps_remaining": self.config.steps_remaining,
                "obs_inspect_weight": self.config.obs_inspect_weight,
                "failure_show": self.config.failure_show,
                "failure_consequence": self.config.failure_consequence,
                "commit_reset": self.config.commit_reset,
            }
        }

        message = Message(
            kind="message",
            role=Role.user,
            parts=[Part(root=TextPart(kind="text", text=json.dumps(request_payload)))],
            message_id=uuid4().hex,
        )

        agent = Agent()
        updater = LocalTaskUpdater()

        try:
            await agent.run(message, updater)
            
            data = updater.get_result_data()
            
            if data:
                data["case_id"] = case.id
                data["difficulty"] = case.difficulty
                data["category"] = case.category
                data["optimal_steps"] = case.optimal_steps
                
                if data["success"] and data["steps_taken"] > 0:
                    data["efficiency"] = case.optimal_steps / data["steps_taken"]
                else:
                    data["efficiency"] = 0.0
                    
                return data
            else:
                return {
                    "case_id": case.id,
                    "error": "Agent finished but returned no data artifact",
                    "success": False,
                    "total_reward": 0.0,
                    "steps_taken": 0,
                    "category": case.category
                }

        except Exception as e:
            print(f"DEBUG: Exception caught in runner: {e}")
            import traceback
            traceback.print_exc()
            return {
                "case_id": case.id,
                "encoding": case.encoding,
                "category": case.category,
                "difficulty": case.difficulty,
                "success": False,
                "total_reward": 0.0,
                "steps_taken": 0,
                "optimal_steps": case.optimal_steps,
                "efficiency": 0.0,
                "error": str(e)
            }
    
    def _compile_summary(
        self,
        results: List[Dict[str, Any]],
        cases: List[BenchmarkCase]
    ) -> Dict[str, Any]:
        """Compile summary statistics from results."""
        total = len(results)
        passed = sum(1 for r in results if r.get("success"))
        
        # Group by category
        by_category = {}
        for result in results:
            cat = result.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = {"passed": 0, "total": 0, "avg_reward": 0.0}
            
            by_category[cat]["total"] += 1
            if result.get("success"):
                by_category[cat]["passed"] += 1
            by_category[cat]["avg_reward"] += result.get("total_reward", 0.0)
        
        # Calculate averages
        for cat in by_category:
            if by_category[cat]["total"] > 0:
                by_category[cat]["avg_reward"] /= by_category[cat]["total"]
        
        return {
            "timestamp": datetime.now().isoformat(),
            "config": self.config.model_dump(),
            "total_cases": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 0,
            "by_category": by_category,
            "results": results
        }
    
    def _save_results(self, summary: Dict[str, Any], output_path: str):
        """Save results to JSON file with compacted arrays."""
        
        # 1. Generate standard pretty JSON string
        json_str = json.dumps(summary, indent=2)
        
        # 2. Define a regex to find simple arrays (no nested objects/arrays)
        # Matches: [ ... ] where ... contains NO { or [ characters
        # This safely targets lists of numbers/strings while skipping complex nested structures
        array_pattern = re.compile(r'\[[^\{\[]*?\]')

        def compact_match(match):
            # Remove all whitespace/newlines inside the match, then add single spaces back
            text = match.group(0)
            # Collapse whitespace to single space
            compact = re.sub(r'\s+', ' ', text)
            # Clean up spacing around brackets: [ 1, 2 ] -> [1, 2]
            return compact.replace('[ ', '[').replace(' ]', ']')

        # 3. Apply the regex substitution
        json_str = array_pattern.sub(compact_match, json_str)
        
        # Ensure directory exists (just in case)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            f.write(json_str)
            
        print(f"\n💾 Results saved to: {output_path}")
    
    def _print_summary(self, summary: Dict[str, Any]):
        """Print summary to console."""
        print(f"\n{'='*60}")
        print(f"📊 Benchmark Summary")
        print(f"{'='*60}")
        print(f"Total Cases: {summary['total_cases']}")
        print(f"Passed: {summary['passed']} ({summary['pass_rate']*100:.1f}%)")
        print(f"Failed: {summary['failed']}")
        print(f"\nBy Category:")
        for cat, stats in summary['by_category'].items():
            pass_rate = stats['passed'] / stats['total'] * 100 if stats['total'] > 0 else 0
            print(f"  {cat}: {stats['passed']}/{stats['total']} ({pass_rate:.1f}%) - Avg Reward: {stats['avg_reward']:.2f}")
        print(f"{'='*60}\n")