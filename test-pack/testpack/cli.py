"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__
from . import report as reporting


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="test-pack",
        description="Declarative readiness checks for a Vertex AI Workbench deployment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run.py\n"
            "  python run.py --only gcp --verbose\n"
            "  python run.py --skip workbench --json reports/result.json\n"
            "  python run.py --project-id my-uat-123 --region europe-west2\n"
            "  python run.py --set kms_key=my-key --set bucket=my-bucket\n"
            "  python run.py --list\n"
            "  python run.py --init\n"
        ),
    )

    parser.add_argument("--config", metavar="PATH", help="config file (default: config.yml)")
    parser.add_argument("--checks-dir", metavar="PATH", help="override the checks directory")
    parser.add_argument("--plugins-dir", metavar="PATH", help="override the plugins directory")

    overrides = parser.add_argument_group("environment overrides")
    overrides.add_argument("--project-id", metavar="ID", help="GCP project ID")
    overrides.add_argument("--project-number", metavar="NUMBER", help="GCP project number")
    overrides.add_argument("--region", metavar="REGION", help="GCP region")
    overrides.add_argument("--zone", metavar="ZONE", help="GCP zone")
    overrides.add_argument(
        "--set",
        metavar="KEY=VALUE",
        action="append",
        default=[],
        help="override any config value (repeatable)",
    )

    selection = parser.add_argument_group("selection")
    selection.add_argument(
        "--only",
        metavar="SELECTOR",
        action="append",
        default=[],
        help="only run checks matching an id, id substring, tag, type or category",
    )
    selection.add_argument(
        "--skip",
        metavar="SELECTOR",
        action="append",
        default=[],
        help="skip checks matching an id, id substring, tag, type or category",
    )
    selection.add_argument("--list", action="store_true", help="list checks without running them")
    selection.add_argument("--fail-fast", action="store_true", help="stop at the first failure")

    output = parser.add_argument_group("output")
    output.add_argument("--json", metavar="PATH", help="write machine-readable results")
    output.add_argument("--junit", metavar="PATH", help="write JUnit XML for CI")
    output.add_argument(
        "--verbose", action="store_true", help="show details, including passing check output"
    )
    output.add_argument(
        "--quiet", action="store_true", help="only show failures, warnings and the summary"
    )
    output.add_argument("--strict", action="store_true", help="exit non-zero for warnings too")
    output.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    output.add_argument("--ascii", action="store_true", help="use ASCII symbols (PASS/FAIL/SKIP)")

    parser.add_argument(
        "--init", action="store_true", help="create config.yml from config.example.yml"
    )
    parser.add_argument("--version", action="version", version=f"test-pack {__version__}")
    return parser


def _has_pyyaml() -> bool:
    try:
        import yaml  # noqa: F401
    except ImportError:
        return False
    return True


def _init_config(root: Path, config_arg: str | None) -> int:
    example = root / "config.example.yml"
    target = Path(config_arg).expanduser() if config_arg else (root / "config.yml")
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()

    if target.exists():
        print(f"{target} already exists; leaving it untouched.")
        return 0
    if not example.exists():
        print(f"error: {example} is missing", file=sys.stderr)
        return 2

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Created {target}")
    print("Edit the values, then run: python run.py")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not _has_pyyaml():
        print(
            "error: PyYAML is required. Install it with:\n"
            "  python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 2

    # Imports are delayed so the friendly PyYAML message above can run first.
    from . import checkers  # noqa: F401  (registers built-in check types)
    from .config import TOOL_ROOT, ConfigError, load_config, parse_overrides
    from .context import Context
    from .loader import LoadError, load_checks, load_plugins
    from .runner import run_checks, select_specs

    root = TOOL_ROOT

    if args.init:
        try:
            return _init_config(root, args.config)
        except OSError as exc:
            print(f"error: could not create config: {exc}", file=sys.stderr)
            return 2

    try:
        overrides = parse_overrides(
            project_id=args.project_id,
            project_number=args.project_number,
            region=args.region,
            zone=args.zone,
            assignments=args.set,
        )
        config = load_config(args.config, overrides=overrides, root=root)

        if args.checks_dir:
            config.settings["checks_dir"] = args.checks_dir
        if args.plugins_dir:
            config.settings["plugins_dir"] = args.plugins_dir

        plugins = load_plugins(config.plugins_dir)
        specs = load_checks(config.checks_dir, default_timeout=config.default_timeout)

        selected = select_specs(specs, only=args.only, skip=args.skip)
        if not selected:
            print("error: no checks matched the --only/--skip filters", file=sys.stderr)
            return 2

        if args.list:
            from .models import Outcome, Result

            reporting.print_check_list(
                [Result(spec, Outcome.skip("not run")) for spec in selected],
                config,
                plugins=plugins,
                ascii_only=args.ascii,
                color=False if args.no_color else None,
            )
            return 0

        context = Context(
            config=config,
            root=root,
            verbose=args.verbose,
            default_timeout=config.default_timeout,
        )

        started = time.perf_counter()
        results = run_checks(
            specs,
            context,
            only=args.only,
            skip=args.skip,
            fail_fast=args.fail_fast,
        )
        elapsed = time.perf_counter() - started

        summary = reporting.print_report(
            results,
            config,
            plugins=plugins,
            elapsed=elapsed,
            quiet=args.quiet,
            ascii_only=args.ascii,
            color=False if args.no_color else None,
            verbose=args.verbose,
        )

        if args.json:
            try:
                reporting.write_json(results, config, args.json, elapsed=elapsed)
            except OSError as exc:
                print(f"error: could not write JSON to {args.json}: {exc}", file=sys.stderr)
                return 2
            print(f"\nJSON written to {args.json}")
        if args.junit:
            try:
                reporting.write_junit(results, args.junit, elapsed=elapsed)
            except OSError as exc:
                print(f"error: could not write JUnit XML to {args.junit}: {exc}", file=sys.stderr)
                return 2
            print(f"JUnit XML written to {args.junit}")

    except (ConfigError, LoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not summary.ready:
        return 1
    if args.strict and (summary.has_warnings or summary.critical_skipped):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
