"""AST + Call Graph Analysis (CGA) based type mismatch detector."""

from src.analysis.checker import CheckResult, check_directory

__all__ = ["check_directory", "CheckResult"]
