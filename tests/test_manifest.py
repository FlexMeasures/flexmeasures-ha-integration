"""Guard against test/production dependency skew.

The v0.3.7 release shipped code requiring flexmeasures-client >= 0.8 while the
manifest still pinned 0.7.0. CI never noticed, because tests installed the
client unpinned. These tests fail whenever the environment the tests run in
does not match the requirements that Home Assistant would install from the
manifest.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path

from packaging.requirements import Requirement
import pytest

MANIFEST_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "flexmeasures_hacs"
    / "manifest.json"
)
MANIFEST = json.loads(MANIFEST_PATH.read_text())


@pytest.mark.parametrize(
    "requirement_string", MANIFEST["requirements"], ids=lambda r: Requirement(r).name
)
def test_installed_version_matches_manifest(requirement_string: str) -> None:
    """Each manifest requirement must be installed at a satisfying version."""
    requirement = Requirement(requirement_string)
    try:
        installed = version(requirement.name)
    except PackageNotFoundError:
        pytest.fail(
            f"{requirement.name} is not installed, but the manifest requires "
            f"'{requirement_string}'. Install the manifest requirements before "
            "running the tests (see .github/workflows/validate.yml)."
        )
    assert requirement.specifier.contains(installed, prereleases=True), (
        f"Installed {requirement.name}=={installed} does not satisfy the manifest "
        f"pin '{requirement_string}'. Tests must run against the exact versions "
        "Home Assistant would install, or CI results are meaningless for users."
    )


def test_manifest_requirements_are_exact_pins() -> None:
    """Ranged pins reintroduce the drift that broke v0.3.7 — require '=='."""
    for requirement_string in MANIFEST["requirements"]:
        requirement = Requirement(requirement_string)
        operators = {spec.operator for spec in requirement.specifier}
        assert operators == {"=="}, (
            f"Manifest requirement '{requirement_string}' is not an exact pin. "
            "Home Assistant installs custom integration requirements without a "
            "lockfile, so only '==' pins give reproducible installs."
        )
