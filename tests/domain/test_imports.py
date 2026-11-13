"""The domain, the ports and the in-memory fakes import only the standard library and
each other.

CLAUDE.md's planned shape: the domain is plain Python with no AWS library and no web
framework, so its rules are tested without AWS. The imports are read with `ast`, so a
module is checked without being imported.
"""

import ast
import sys
from pathlib import Path

import asmbly_ceramics

PACKAGE = Path(asmbly_ceramics.__file__).parent
DOMAIN = "asmbly_ceramics.domain"
PORTS = "asmbly_ceramics.ports"
# The fakes are what phases 2 and 3 test against without AWS, so they import no AWS
# library or web framework either.
ALLOWED = {"domain": (DOMAIN,), "ports": (DOMAIN, PORTS), "adapters/memory": (DOMAIN, PORTS)}


def imported_modules(source: str) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Relative imports are banned by ruff; record one as itself so it is refused.
            modules.append("." * node.level + (node.module or ""))
    return modules


def forbidden_imports(source: str, allowed: tuple[str, ...]) -> list[str]:
    def is_allowed(module: str) -> bool:
        if module.split(".")[0] in sys.stdlib_module_names:
            return True
        return any(module == package or module.startswith(package + ".") for package in allowed)

    return [module for module in imported_modules(source) if not is_allowed(module)]


def test_the_domain_imports_only_the_standard_library() -> None:
    modules = [
        (path, allowed)
        for folder, allowed in ALLOWED.items()
        for path in sorted((PACKAGE / folder).rglob("*.py"))
    ]
    for folder in ALLOWED:
        assert any(path.parent == PACKAGE / folder for path, _ in modules), f"no {folder} module"
    problems = {
        path.relative_to(PACKAGE).as_posix(): bad
        for path, allowed in modules
        if (bad := forbidden_imports(path.read_text(), allowed))
    }
    assert not problems


def test_the_import_check_catches_a_forbidden_import() -> None:
    source = "import json\nimport boto3\nfrom starlette.requests import Request\nfrom . import ids\n"
    assert forbidden_imports(source, (DOMAIN,)) == ["boto3", "starlette.requests", "."]
    assert forbidden_imports("from asmbly_ceramics.ports import records\n", (DOMAIN,)) == [
        "asmbly_ceramics.ports"
    ]
    assert forbidden_imports("from asmbly_ceramics.domain.ids import DropOffId\n", (DOMAIN,)) == []
