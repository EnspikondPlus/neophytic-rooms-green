import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pydantic import BaseModel, Field


@dataclass
class BenchmarkCase:
    """Single benchmark test case."""
    id: str
    encoding: str
    difficulty: str
    optimal_steps: int
    description: str
    category: str


class BenchmarkConfig(BaseModel):
    """Configuration for running benchmarks."""
    categories: List[str] = Field(
        default=["tutorial"],
        description="Categories to run (tutorial, basic, advanced, or 'all')"
    )
    max_steps: int = Field(default=50, description="Maximum steps per episode")
    steps_remaining: int = Field(default=30, description="Step budget for agent")
    obs_inspect_weight: float = Field(default=3.0, description="Cost of inspect action")
    failure_show: bool = Field(default=True, description="Show failure signals")
    failure_consequence: bool = Field(default=False, description="Penalize failures")
    commit_reset: bool = Field(default=False, description="Reset on commit")
    timeout_per_test: int = Field(default=300, description="Timeout per test in seconds")
    

class BenchmarkDatabase:
    """Manages benchmark encodings and test cases."""
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "benchmarks" / "encodings.json"
        self.db_path = db_path
        self.data = self._load_database()
    
    def _load_database(self) -> Dict[str, Any]:
        """Load benchmark database from JSON file."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Benchmark database not found at {self.db_path}")
        
        with open(self.db_path, 'r') as f:
            return json.load(f)
    
    def get_categories(self) -> List[str]:
        """Get list of available categories."""
        return list(self.data.get("encodings", {}).keys())
    
    def get_cases(self, categories: Optional[List[str]] = None) -> List[BenchmarkCase]:
        """Get benchmark cases for specified categories.
        
        Args:
            categories: List of category names, or None for all categories
        
        Returns:
            List of BenchmarkCase objects
        """
        if categories is None or "all" in categories:
            categories = self.get_categories()
        
        cases = []
        encodings = self.data.get("encodings", {})
        
        for category in categories:
            if category not in encodings:
                print(f"Warning: Category '{category}' not found in database")
                continue
            
            category_data = encodings[category]
            for case_data in category_data.get("cases", []):
                cases.append(BenchmarkCase(
                    id=case_data["id"],
                    encoding=case_data["encoding"],
                    difficulty=case_data["difficulty"],
                    optimal_steps=case_data["optimal_steps"],
                    description=case_data["description"],
                    category=category
                ))
        
        return cases
    
    def get_case_by_id(self, case_id: str) -> Optional[BenchmarkCase]:
        """Get a specific benchmark case by ID."""
        for category in self.get_categories():
            for case in self.get_cases([category]):
                if case.id == case_id:
                    return case
        return None