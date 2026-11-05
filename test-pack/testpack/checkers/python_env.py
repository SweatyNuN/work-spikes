"""Checks about the running Python interpreter and installed distributions."""

from __future__ import annotations

import importlib
import importlib.metadata
import platform
import sys

from ..models import Outcome
from ..registry import check
from ..versions import satisfies


def _version_spec(params: dict) -> str | None:
    spec = params.get("version")
    if spec:
        return str(spec)

    clauses: list[str] = []
    if params.get("min_version") is not None:
        clauses.append(f">={params['min_version']}")
    if params.get("max_version") is not None:
        clauses.append(f"<={params['max_version']}")
    if params.get("exact_version") is not None:
        clauses.append(f"=={params['exact_version']}")
    return ",".join(clauses) or None


@check("python_version", "Assert the running Python version")
def python_version(ctx, params):
    actual = platform.python_version()
    implementation = platform.python_implementation()

    expected_implementation = params.get("implementation")
    if (
        expected_implementation
        and implementation.casefold() != str(expected_implementation).casefold()
    ):
        return Outcome.fail(
            f"{implementation} is running, expected {expected_implementation}",
            detail=f"Python {actual}\ninterpreter: {sys.executable}",
        )

    spec = _version_spec(params)
    if spec and not satisfies(actual, spec):
        return Outcome.fail(
            f"Python {actual} does not satisfy {spec}",
            detail=f"interpreter: {sys.executable}",
            hint="Use a supported Vertex AI Workbench image or rebuild the kernel.",
        )

    message = f"Python {actual} ({implementation})"
    if spec:
        message += f" satisfies {spec}"
    return Outcome.ok(message, detail=f"interpreter: {sys.executable}")


@check("package", "Assert a Python distribution is installed and importable")
def package(ctx, params):
    name = params.get("name")
    if not name:
        return Outcome.fail("check is missing the 'name' param")

    name = str(name)
    import_name = params.get("import_name")
    if import_name is None:
        import_name = name.replace("-", "_")
    import_name = str(import_name) if import_name else ""

    version_spec = _version_spec(params)

    try:
        installed = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return Outcome.fail(
            f"{name} is not installed",
            hint=f"pip install {name}",
        )
    except Exception as exc:  # malformed metadata, unusual environment
        return Outcome.fail(
            f"could not read the installed version of {name}",
            detail=f"{type(exc).__name__}: {exc}",
        )

    if version_spec and not satisfies(installed, version_spec):
        return Outcome.fail(
            f"{name} {installed} does not satisfy {version_spec}",
            hint=f"pip install --upgrade '{name}{version_spec}'",
        )

    # Importing proves the package is usable, not merely present in metadata.
    # Set import_check: false for packages whose import is very expensive.
    if import_name and params.get("import_check", True):
        try:
            importlib.import_module(import_name)
        except Exception as exc:
            return Outcome.fail(
                f"{name} {installed} is installed but cannot be imported",
                detail=f"import {import_name} failed: {type(exc).__name__}: {exc}",
                hint="The base image is inconsistent; rebuild it or reinstall the package.",
            )

    detail = f"distribution: {name} {installed}"
    if import_name:
        detail += f"\nimport: {import_name}"
    return Outcome.ok(f"{name} {installed}", detail=detail)


@check("python_import", "Import a module (and optionally an attribute)")
def python_import(ctx, params):
    module_name = params.get("module")
    if not module_name:
        return Outcome.fail("check is missing the 'module' param")

    module_name = str(module_name)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return Outcome.fail(
            f"could not import {module_name}",
            detail=f"{type(exc).__name__}: {exc}",
            hint=f"Check that {module_name} is installed and its dependencies are intact.",
        )

    attribute = params.get("attribute")
    if attribute:
        try:
            getattr(module, str(attribute))
        except AttributeError:
            return Outcome.fail(
                f"{module_name} has no attribute '{attribute}'",
                detail=f"module loaded from {getattr(module, '__file__', '(built-in)')}",
            )

    display = str(params.get("name") or module_name)
    detail = f"module: {getattr(module, '__file__', '(built-in)')}"
    if attribute:
        detail += f"\nattribute: {attribute}"
    return Outcome.ok(f"{display} importable", detail=detail)
