"""``pyvelm test`` — run pytest with project-friendly defaults."""

from __future__ import annotations

from pathlib import Path

from pyvelm.console import Command, _build_argparse
from pyvelm.scaffolder import find_project_root


def default_test_path() -> str:
    """Return a sensible pytest path for the current tree."""
    root = find_project_root()
    if root is not None:
        tests = root / "tests"
        if tests.is_dir():
            return str(tests)
    if Path("pyvelm/tests").is_dir():
        return "pyvelm/tests"
    return "."


class TestCommand(Command):
    name = "test"
    description = "Run pytest (pass extra args after --, e.g. pyvelm test -- -k foo)"
    signature = (
        "test "
        "{--coverage : Run with coverage report} "
        "{--integration : Include integration tests (requires PYVELM_DSN_TEST)} "
        "{--path= : Test path or node (default: tests/ or pyvelm/tests)}"
    )

    def run(self, ctx, argv: list[str]) -> int:
        """Parse known flags; forward remaining tokens to pytest."""
        self._ctx = ctx
        parser = _build_argparse(self)
        args, extra = parser.parse_known_args(argv)
        return self.handle(**vars(args), extra=extra)

    def handle(
        self,
        coverage: bool = False,
        integration: bool = False,
        path: str | None = None,
        extra: list[str] | None = None,
    ) -> int:
        from pyvelm.database import load_testing_env

        load_testing_env()

        try:
            import pytest
        except ImportError:
            self.error(
                "pytest is not installed. Run: pip install pyvelm[test]"
            )
            return 1

        target = (path or "").strip() or default_test_path()
        pytest_args: list[str] = []
        if coverage:
            pytest_args.extend(["--cov=pyvelm", "--cov-report=term-missing"])
        if not integration:
            pytest_args.extend(["-m", "not integration"])
        pytest_args.append(target)
        if extra:
            pytest_args.extend(extra)

        code = pytest.main(pytest_args)
        return 0 if code == 0 else 1
