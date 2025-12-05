import json
import platform

from pre_commit_python_eol import __url__, __version__
from pre_commit_python_eol.check_eol import CACHED_EOL_VERSIONS as LOCAL_CACHE_EOL_VERSIONS
from pre_commit_python_eol.check_eol import CACHED_RELEASE_CYCLE as LOCAL_CACHE_CYCLE
from pre_commit_python_eol.check_eol import (
    get_eol_versions,
)

try:
    import httpx
except ImportError:
    raise RuntimeError(
        "httpx was not installed, please install the 'gha' dependency group"
    ) from None

USER_AGENT = (
    f"pre-commit-check-eol/{__version__} ({__url__}) "
    f"httpx/{httpx.__version__} "
    f"{platform.python_implementation()}/{platform.python_version()}"
)

CACHE_SOURCE = "https://peps.python.org/api/release-cycle.json"


def bump_cached_release_cycle() -> None:
    """Update the cached release cycle JSON from the source repository."""
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        r = client.get(CACHE_SOURCE)
        r.raise_for_status()

        rj = r.json()

    with LOCAL_CACHE_CYCLE.open("w", encoding="utf8") as f:
        json.dump(rj, f, indent=2, ensure_ascii=False)
        f.write("\n")  # Add in trailing newline


def bump_cached_eol_versions() -> None:
    """Update the cached EOL versions JSON from the source repository."""
    eol_versions = dict(version.to_json() for version in get_eol_versions())

    with LOCAL_CACHE_EOL_VERSIONS.open("w", encoding="utf8") as f:
        json.dump(eol_versions, f, indent=2, ensure_ascii=False)
        f.write("\n")  # Add in trailing newline


if __name__ == "__main__":
    bump_cached_release_cycle()
    bump_cached_eol_versions()
