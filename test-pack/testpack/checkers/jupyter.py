"""Checks for Jupyter kernels and JupyterLab extensions."""

from __future__ import annotations

import json
import shutil

from ..models import Outcome
from ..registry import check


@check("jupyter_kernel", "Assert a Jupyter kernel is installed")
def jupyter_kernel(ctx, params):
    name = str(params.get("name", "python3"))
    if shutil.which("jupyter") is None:
        return Outcome.fail(
            "jupyter command not found",
            hint="Run this inside a Vertex AI Workbench, or install Jupyter.",
        )

    result = ctx.run(
        ["jupyter", "kernelspec", "list", "--json"],
        timeout=params.get("timeout") or 30,
    )
    if not result.ok:
        return Outcome.fail("could not list Jupyter kernels", detail=result.detail())

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return Outcome.fail(
            "could not parse Jupyter kernel list",
            detail=f"{exc}\n{result.stdout[:2000]}",
        )

    kernels = data.get("kernelspecs", {}) if isinstance(data, dict) else {}
    if name not in kernels:
        installed = ", ".join(sorted(kernels)) or "none"
        return Outcome.fail(
            f"kernel '{name}' is not installed",
            detail=f"Installed kernels: {installed}",
            hint=(
                "Install ipykernel and register the kernel, or use the workbench's default kernel."
            ),
        )

    spec = kernels[name].get("spec", {}) if isinstance(kernels[name], dict) else {}
    display = spec.get("display_name") or name
    language = spec.get("language")
    detail = f"display name: {display}"
    if language:
        detail += f"\nlanguage: {language}"
    return Outcome.ok(f"kernel '{name}' available ({display})", detail=detail)


@check("jupyter_extension", "Assert a JupyterLab extension is installed/enabled")
def jupyter_extension(ctx, params):
    name = params.get("name")
    if not name:
        return Outcome.fail("check is missing the 'name' param")
    name = str(name)
    must_be_enabled = bool(params.get("must_be_enabled", True))

    if shutil.which("jupyter") is None:
        return Outcome.fail(
            "jupyter command not found",
            hint="Run this inside a Vertex AI Workbench, or install Jupyter.",
        )

    result = ctx.run(
        ["jupyter", "labextension", "list"],
        timeout=params.get("timeout") or 60,
    )
    if not result.ok:
        return Outcome.fail("could not list JupyterLab extensions", detail=result.detail())

    matches = [
        line.strip() for line in result.stdout.splitlines() if name.casefold() in line.casefold()
    ]
    if not matches:
        return Outcome.fail(
            f"JupyterLab extension '{name}' was not found",
            detail=result.stdout[-3000:],
            hint=f"Install it in the workbench image (for example: pip install {name}).",
        )

    line = next((item for item in matches if "enabled" in item.casefold()), matches[0])
    disabled = "disabled" in line.casefold()

    if must_be_enabled and disabled:
        return Outcome.fail(
            f"extension '{name}' is installed but disabled",
            detail=line,
            hint=f"Enable it with: jupyter labextension enable {name}",
        )
    if not must_be_enabled and not disabled:
        return Outcome.fail(f"extension '{name}' is enabled but should be disabled", detail=line)

    state = "disabled" if disabled else "enabled"
    return Outcome.ok(f"extension '{name}' {state}", detail=line)
