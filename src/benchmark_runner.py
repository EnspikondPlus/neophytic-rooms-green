import asyncio
import json
from typing import Dict, List, Any
from datetime import datetime
from pydantic import HttpUrl

from .benchmark_config import BenchmarkDatabase, BenchmarkConfig, BenchmarkCase
from .messenger import Messenger


class BenchmarkRunner:
    """Runs benchmark suite against a purple agent."""
    
    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.database = BenchmarkDatabase()
        self.messenger = Messenger()
    
    async def run_benchmark_suite(
        self,
        purple_agent_url: str,
        output_path: str = None
    ) -> Dict[str, Any]:
        """Run full benchmark suite against a purple agent.
        
        Args:
            purple_agent_url: URL of the purple agent to test
            output_path: Optional path to save results JSON
        
        Returns:
            Dictionary with benchmark results
        """
        print(f"\n{'='*60}")
        print(f"🟢 Running Rooms Benchmark Suite")
        print(f"{'='*60}")
        print(f"Purple Agent: {purple_agent_url}")
        print(f"Categories: {', '.join(self.config.categories)}")
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
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            print(f"  {status} - Reward: {result['total_reward']:.2f}, Steps: {result['steps_taken']}\n")
        
        # Compile summary
        summary = self._compile_summary(results, cases)
        
        # Save results if path provided
        if output_path:
            self._save_results(summary, output_path)
        
        self._print_summary(summary)
        
        return summary
    
    async def _run_single_case(
        self,
        case: BenchmarkCase,
        purple_agent_url: str
    ) -> Dict[str, Any]:
        """Run a single benchmark case."""
        
        # Prepare request for green agent (itself)
        request = {
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
        
        # This would normally be called through the agent's run method
        # For now, we'll simulate the result structure
        # In practice, this would integrate with your Agent.run() method
        
        try:
            # TODO: Integrate with actual agent execution
            # For now, return a placeholder
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
                "error": "Not yet implemented"
            }
        except Exception as e:
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
        passed = sum(1 for r in results if r["success"])
        
        # Group by category
        by_category = {}
        for result in results:
            cat = result["category"]
            if cat not in by_category:
                by_category[cat] = {"passed": 0, "total": 0, "avg_reward": 0.0}
            
            by_category[cat]["total"] += 1
            if result["success"]:
                by_category[cat]["passed"] += 1
            by_category[cat]["avg_reward"] += result["total_reward"]
        
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
        """Save results to JSON file."""
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)
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