"""Importing this package registers all built-in check types.

Order is not important. Add a new module here when you add a family of checks.
"""

from . import gcp, jupyter, python_env, system  # noqa: F401
