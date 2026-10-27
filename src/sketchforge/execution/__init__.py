"""Execution package: isolated subprocess environment for generated application builds."""
from sketchforge.execution.sandbox import open_sandbox, SandboxSession, RunResult
from sketchforge.execution.command_policy import is_permitted, assert_permitted, CommandNotPermitted
from sketchforge.execution.process_runner import npm_workflow, pytest_workflow, ProcessReport

__all__ = [
    "open_sandbox", "SandboxSession", "RunResult",
    "is_permitted", "assert_permitted", "CommandNotPermitted",
    "npm_workflow", "pytest_workflow", "ProcessReport",
]
