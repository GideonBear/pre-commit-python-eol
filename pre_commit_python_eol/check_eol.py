from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import typing as t
from collections import abc
from dataclasses import dataclass
from enum import StrEnum
from operator import attrgetter
from pathlib import Path

import tomlkit
from packaging import specifiers, version

CACHED_RELEASE_CYCLE = Path(__file__).parent / "cached_release_cycle.json"


class EOLPythonError(Exception): ...  # noqa: D101


class RequiresPythonNotFoundError(Exception): ...  # noqa: D101


class UnsupportedFixError(Exception):  # noqa: D101
    def __init__(self):
        super().__init__(
            "Fixing EOL Python versions is only supported for simple '>=3.x' specifiers."
        )


class ReleasePhase(StrEnum):
    """
    Python release phase mapping, as described by PEP602.

    See: https://devguide.python.org/versions/#status-key
    """

    FEATURE = "feature"
    PRERELEASE = "prerelease"
    BUGFIX = "bugfix"
    SECURITY = "security"
    EOL = "end-of-life"


def _parse_eol_date(date_str: str) -> dt.date:
    """
    Parse a `dt.date` instance from one of two specification formats.

    Two date formats are supported:
        * `YYYY-MM-DD` - Parsed as-is, assuming ISO 8601 format
        * `YYYY-MM` - Parsed as a `dt.date` instance for the 1st of the specified year & month
    """
    parts = date_str.split("-")
    match len(parts):
        case 3:
            eol_date = dt.date.fromisoformat(date_str)
        case 2:
            year, month = (int(c) for c in parts)
            eol_date = dt.date(year=year, month=month, day=1)
        case _:
            raise ValueError(f"Unknown date format: '{date_str}'")

    return eol_date


@dataclass(frozen=True)
class PythonRelease:  # noqa: D101
    python_ver: version.Version
    status: ReleasePhase
    end_of_life: dt.date

    def __str__(self) -> str:  # pragma: no cover
        return f"Python {self.python_ver} - Status: {self.status}, EOL: {self.end_of_life}"

    @classmethod
    def from_json(cls, ver: str, metadata: dict[str, t.Any]) -> PythonRelease:
        """
        Create a `PythonRelease` instance from the provided JSON components.

        JSON components are assumed to be of the format provided by the Python PEPs API:
        https://peps.python.org/api/release-cycle.json
        """
        return cls(
            python_ver=version.Version(ver),
            status=ReleasePhase(metadata["status"]),
            end_of_life=_parse_eol_date(metadata["end_of_life"]),
        )

    def is_eol(self, use_system_date: bool) -> bool:
        """
        Check if this version is end-of-life.

        If `use_system_date` is `True`, an additional date-based check is performed for versions
        that are not explicitly EOL.
        """
        if self.status == ReleasePhase.EOL:
            return True

        if use_system_date:
            utc_today = dt.datetime.now(dt.timezone.utc).date()
            if self.end_of_life <= utc_today:
                return True

        return False


def _get_cached_release_cycle(cache_json: Path) -> list[PythonRelease]:
    """
    Parse the locally cached Python release cycle into `PythonRelease` instance(s).

    Results are sorted by Python version in descending order.
    """
    with cache_json.open("r", encoding="utf-8") as f:
        contents = json.load(f)

    # The sorting is probably unnecessary since the JSON should already be sorted, but going to
    # retain since it's expected downstream
    return sorted(
        (PythonRelease.from_json(v, m) for v, m in contents.items()),
        key=attrgetter("python_ver"),
        reverse=True,
    )


def get_fixed_spec(specs: specifiers.SpecifierSet, eol_supported: list[PythonRelease]) -> str:
    """Fix a specifier to exclude EOL versions."""
    # Only supports a single specifier
    if not len(specs) == 1:
        raise UnsupportedFixError()
    spec = list(specs)[0]
    # Only supports >= operator
    if not spec.operator == ">=":
        raise UnsupportedFixError()

    cutoff = eol_supported[-1].python_ver
    # Only supports >=x.y
    new_minimum = f"{cutoff.major}.{cutoff.minor + 1}"
    return f">={new_minimum}"


def check_python_support(
    toml_file: Path,
    cache_json: Path = CACHED_RELEASE_CYCLE,
    use_system_date: bool = True,
    fix: bool = False,
) -> None:
    """
    Check the input TOML's `requires-python` for overlap with EOL Python version(s).

    If overlap(s) are present, an exception is raised whose message enumerates all EOL Python
    versions supported by the TOML file.

    If `use_system_date` is `True`, an additional date-based check is performed for versions that
    are not explicitly EOL.
    """
    with toml_file.open("rb") as f:
        contents = tomlkit.load(f)

    requires_python = contents.get("project", {}).get("requires-python", None)
    if not requires_python:
        raise RequiresPythonNotFoundError

    package_spec = specifiers.SpecifierSet(requires_python)
    release_cycle = _get_cached_release_cycle(cache_json)

    eol_supported = [
        r for r in release_cycle if ((r.python_ver in package_spec) and r.is_eol(use_system_date))
    ]

    if not eol_supported:
        return

    eol_supported.sort(key=attrgetter("python_ver"))  # Sort ascending for error msg generation

    if fix:
        new_spec = get_fixed_spec(package_spec, eol_supported)
        contents["project"]["requires-python"] = new_spec
        with toml_file.open("w") as f:
            tomlkit.dump(contents, f)

    joined_vers = ", ".join(str(r.python_ver) for r in eol_supported)
    raise EOLPythonError(f"EOL Python support found: {joined_vers}")


def main(argv: abc.Sequence[str] | None = None) -> int:  # noqa: D103
    parser = argparse.ArgumentParser()
    parser.add_argument("filenames", nargs="*", type=Path)
    parser.add_argument("--cache_only", action="store_true")
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args(argv)

    ec = 0
    for file in args.filenames:
        try:
            check_python_support(file, use_system_date=(not args.cache_only), fix=args.fix)
        except EOLPythonError as e:
            print(f"{file}: {e}")
            ec = 1
        except RequiresPythonNotFoundError:
            print(f"{file} 'requires-python' could not be located, or it is empty.")
            ec = 1

    return ec


if __name__ == "__main__":
    sys.exit(main())
