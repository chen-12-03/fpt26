"""Architecture dependency direction tests.

Enforce that:
- candidate/ does not import from workflow
- integrations/ does not import from pipeline
- agents do not import workflow gate functions
- CandidateValidator is the single import for gate logic
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

AGENT_ROOT = Path(__file__).resolve().parent.parent / "agent"

# Modules that must NOT import from workflow
_FORBIDDEN_WORKFLOW_IMPORTERS = [
    "agent/candidate/",
    "agent/integrations/",
    "agent/security/",
    "agent/pipeline/",
    "agent/reporting/",
]

# Specific workflow symbols agents must NOT import
_FORBIDDEN_WORKFLOW_SYMBOLS = {
    "validate_candidate",
    "record_synth_gates",
    "record_cosim_gate",
    "mark_fully_verified",
    "_candidate_validator",
}


def _imports_from(module_path: Path, target_module: str) -> list[str]:
    """Return list of symbol names imported from *target_module*."""
    if not module_path.is_file():
        return []
    try:
        tree = ast.parse(module_path.read_text())
    except SyntaxError:
        return []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and target_module in node.module:
                for alias in node.names:
                    imports.append(alias.name)
    return imports


class TestDependencyDirection:
    """Forbidden imports: candidate/integrations/security/pipeline must not import workflow."""

    @pytest.mark.parametrize("forbidden_dir", _FORBIDDEN_WORKFLOW_IMPORTERS)
    def test_no_workflow_import(self, forbidden_dir: str):
        d = AGENT_ROOT / forbidden_dir.replace("agent/", "", 1) if "/" in forbidden_dir else AGENT_ROOT / forbidden_dir
        if not d.is_dir():
            pytest.skip(f"{d} does not exist")
        violations = []
        for py_file in sorted(d.rglob("*.py")):
            imports = _imports_from(py_file, "agent.workflow")
            if imports:
                violations.append(f"{py_file.relative_to(AGENT_ROOT)} imports {imports}")
        assert not violations, (
            f"Modules under {forbidden_dir} must not import from agent.workflow:\n"
            + "\n".join(violations)
        )


class TestAgentsDoNotImportWorkflowGates:
    """Repair, structural, and optimize agents must not import workflow gate functions directly."""

    @pytest.mark.parametrize("agent_file", [
        "agent/agents/repair.py",
        "agent/agents/structural.py",
        "agent/agents/optimize.py",
    ])
    def test_agent_no_workflow_gate_import(self, agent_file: str):
        fp = AGENT_ROOT / agent_file.replace("agent/", "", 1)
        if not fp.is_file():
            pytest.skip(f"{fp} not found")
        symbols = _imports_from(fp, "agent.workflow")
        violations = [s for s in symbols if s in _FORBIDDEN_WORKFLOW_SYMBOLS]
        assert not violations, (
            f"{agent_file} imports forbidden workflow gate symbols: {violations}. "
            f"Use agent.candidate.validator instead."
        )


class TestExtractCodeCentralised:
    """extract_code must only be defined in candidate/validator.py.
    Other modules must import it from there."""

    @pytest.mark.parametrize("agent_file", [
        "agent/agents/repair.py",
        "agent/agents/structural.py",
    ])
    def test_agent_imports_extract_code_from_candidate(self, agent_file: str):
        fp = AGENT_ROOT / agent_file.replace("agent/", "", 1)
        if not fp.is_file():
            pytest.skip(f"{fp} not found")
        imports = _imports_from(fp, "agent.candidate.validator")
        assert "extract_code" in imports, (
            f"{agent_file} must import extract_code from agent.candidate.validator"
        )

    def test_optimize_controller_imports_extract_code(self):
        """optimization/controller.py must import extract_code from candidate/validator."""
        fp = AGENT_ROOT / "agents/optimization/controller.py"
        if not fp.is_file():
            pytest.skip(f"{fp} not found")
        imports = _imports_from(fp, "agent.candidate.validator")
        assert "extract_code" in imports, (
            "controller.py must import extract_code from agent.candidate.validator"
        )

    @pytest.mark.parametrize("agent_file", [
        "agent/agents/repair.py",
        "agent/agents/structural.py",
        "agent/agents/optimize.py",
    ])
    def test_agent_has_no_local_extract_code(self, agent_file: str):
        fp = AGENT_ROOT / agent_file.replace("agent/", "", 1)
        if not fp.is_file():
            pytest.skip(f"{fp} not found")
        try:
            tree = ast.parse(fp.read_text())
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "extract_code":
                pytest.fail(f"{agent_file} defines its own extract_code; import from agent.candidate.validator instead")


class TestWorkflowCompat:
    """Workflow.py still exports gate functions as compatibility forwarders."""

    def test_workflow_exports_gate_functions(self):
        fp = AGENT_ROOT / "workflow.py"
        text = fp.read_text()
        for name in ["validate_candidate", "record_synth_gates", "record_cosim_gate",
                      "mark_fully_verified"]:
            assert f"def {name}" in text, (
                f"workflow.py must still define {name} for backward compatibility"
            )
        # extract_code is re-exported via import, not a local definition
        assert "extract_code" in text, (
            "workflow.py must still re-export extract_code"
        )

    def test_workflow_delegates_to_candidate(self):
        fp = AGENT_ROOT / "workflow.py"
        text = fp.read_text()
        assert "agent.candidate.validator" in text, (
            "workflow.py must delegate to agent.candidate.validator"
        )


class TestLlmsHarnessBoundary:
    """Production code must not import llm4hls directly (only integrations may)."""

    _FORBIDDEN_DIRECT_LLM4HLS = [
        "agent/main.py",
        "agent/pipeline/submission.py",
        "agent/pipeline/evaluator.py",
        "agent/agents/repair.py",
        "agent/agents/structural.py",
        "agent/agents/optimize.py",
        "agent/candidate/validator.py",
        "agent/candidate/selector.py",
        "agent/candidate/checkpoint.py",
    ]

    @pytest.mark.parametrize("rel_path", _FORBIDDEN_DIRECT_LLM4HLS)
    def test_no_direct_llm4hls_import(self, rel_path: str):
        fp = AGENT_ROOT / rel_path.replace("agent/", "", 1) if rel_path.startswith("agent/") else AGENT_ROOT / rel_path
        if not fp.is_file():
            pytest.skip(f"{fp} not found")
        imports = _imports_from(fp, "llm4hls")
        assert not imports, (
            f"{rel_path} must not import from llm4hls directly. "
            f"Use agent.integrations.harness or agent.integrations.llm instead."
        )


class TestTaskRepositoryInProduction:
    """main.py must use TaskRepository for task loading."""

    def test_main_uses_task_repository(self):
        fp = AGENT_ROOT / "main.py"
        text = fp.read_text()
        assert "PublicTaskRepository" in text, (
            "main.py must use PublicTaskRepository for submission task loading"
        )


class TestLLMExecutorInProduction:
    """backends.py must return LLMExecutor."""

    def test_backends_returns_llm_executor(self):
        fp = AGENT_ROOT / "backends.py"
        text = fp.read_text()
        assert "LLMExecutor" in text, (
            "backends.py must return LLMExecutor"
        )
