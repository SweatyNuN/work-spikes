"""Execution context passed to every checker."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .config import Config
from .interpolate import MissingValue


@dataclass
class CommandResult:
    argv: Sequence[str] | str
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timed_out: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.error

    def detail(self, max_chars: int = 4000) -> str:
        if isinstance(self.argv, str):
            command = self.argv
        else:
            command = " ".join(shlex.quote(str(part)) for part in self.argv)

        lines = [f"$ {command}"]
        if self.error:
            lines.append(self.error)
        status = f"exit code: {self.returncode}"
        if self.timed_out:
            status += " (timed out)"
        lines.append(status)

        if self.stdout.strip():
            lines.extend(["stdout:", _clip(self.stdout, max_chars)])
        if self.stderr.strip():
            lines.extend(["stderr:", _clip(self.stderr, max_chars)])
        return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated)"


class Context:
    """Everything a checker needs, and nothing more."""

    def __init__(
        self,
        config: Config,
        root: Path | None = None,
        verbose: bool = False,
        default_timeout: float | None = None,
    ):
        self.config = config
        self.root = Path(root) if root else config.root
        self.verbose = verbose
        self.default_timeout = float(
            default_timeout if default_timeout is not None else config.default_timeout
        )

    @property
    def values(self):
        return self.config.values

    def get(self, key: str, default=None):
        try:
            return self.values.get(key)
        except MissingValue:
            return default

    def resolve_path(self, value: str | Path) -> Path:
        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else (self.root / path)

    @property
    def gcloud_available(self) -> bool:
        return shutil.which("gcloud") is not None

    def run(
        self,
        command: Sequence[str] | str,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        shell: bool | None = None,
    ) -> CommandResult:
        """Run a command, never raising for a non-zero exit or a timeout."""

        if isinstance(command, (list, tuple)):
            parts = [str(part) for part in command]
            use_shell = bool(shell) if shell is not None else False
            # Passing a list to subprocess with shell=True has surprising
            # semantics (only the first element is the command), so join it.
            argv: Sequence[str] | str = shlex.join(parts) if use_shell else parts
        else:
            argv = str(command)
            use_shell = True if shell is None else bool(shell)

        timeout = float(timeout if timeout is not None else self.default_timeout)
        workdir = str(cwd if cwd is not None else self.root)
        if not Path(workdir).exists():
            return CommandResult(
                argv=argv,
                returncode=127,
                error=f"working directory not found: {workdir}",
            )

        environment = dict(os.environ)
        if env:
            environment.update({str(key): str(value) for key, value in env.items()})

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                argv,
                shell=use_shell,
                cwd=workdir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                argv=argv,
                returncode=124,
                stdout=_as_text(exc.stdout),
                stderr=_as_text(exc.stderr),
                duration=time.perf_counter() - started,
                timed_out=True,
            )
        except FileNotFoundError as exc:
            return CommandResult(
                argv=argv,
                returncode=127,
                duration=time.perf_counter() - started,
                error=f"executable not found: {exc.filename or argv}",
            )
        except OSError as exc:
            return CommandResult(
                argv=argv,
                returncode=126,
                duration=time.perf_counter() - started,
                error=f"could not run command: {exc}",
            )

        return CommandResult(
            argv=argv,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration=time.perf_counter() - started,
        )

    def gcloud(
        self,
        args: Sequence[str],
        project: str | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        argv = ["gcloud", *[str(part) for part in args]]
        if project:
            argv.append(f"--project={project}")
        return self.run(argv, timeout=timeout)


def _as_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value
