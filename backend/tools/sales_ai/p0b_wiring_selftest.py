"""P0-B wiring regression: verifies that approved pure helpers are called.

Unlike unit tests that exercise only the helper modules, this verifies the
production entrypoints. Reads only checked-in Python source; no DB or LLM calls.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]  # backend/
MODULES = ROOT / "app" / "modules" / "sales_agent"


def function_body(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    if len(funcs) != 1:
        raise AssertionError(f"Expected exactly one {name} in {path.name}")
    return funcs[0]


def from_imported(node, module, symbol, alias=None):
    return any(
        isinstance(child, ast.ImportFrom)
        and child.module == module
        and any(
            a.name == symbol and a.asname == alias
            for a in child.names
        )
        for child in ast.walk(node)
    )


def called(node, name):
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == name
        for child in ast.walk(node)
    )


class TestP0BWiring(unittest.TestCase):
    def test_booking_intent_is_imported_inside_compiler(self):
        node = function_body(MODULES / "interpretation_input.py", "compile_input")
        self.assertTrue(
            from_imported(node, "booking_intent", "canonicalize_new_visit"),
            "P0-B helper exists but is not imported in compile_input",
        )

    def test_booking_intent_is_invoked_inside_compiler(self):
        node = function_body(MODULES / "interpretation_input.py", "compile_input")
        self.assertTrue(
            called(node, "canonicalize_new_visit"),
            "P0-B normalizer exists but is not called before references compile",
        )

    def test_booking_fastpath_is_imported_in_runtime(self):
        node = function_body(MODULES / "active_service.py", "interpret_phase")
        self.assertTrue(
            from_imported(node, "booking_fastpath", "try_preview",
                          "booking_confirmation_preview"),
            "P0-B booking acceptance helper is not connected to active_service",
        )

    def test_booking_fastpath_is_invoked_before_llm_fallback(self):
        node = function_body(MODULES / "active_service.py", "interpret_phase")
        self.assertTrue(
            called(node, "booking_confirmation_preview"),
            "P0-B booking acceptance helper is not called in production",
        )
        self.assertTrue(called(node, "preview"), "No model fallback found")


if __name__ == "__main__":
    unittest.main(verbosity=2)
