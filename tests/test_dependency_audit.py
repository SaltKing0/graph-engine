"""Offline regressions for the advisory gate; never contact an advisory service."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
CVE = "CVE-2025-71176"
GHSA = "GHSA-6w46-j5rx-g56g"


def dependency(name="pytest", version="8.4.0", vulns=None):
    return {"name": name, "version": version, "vulns": vulns or []}


def vuln(identifier=CVE, aliases=None, fixes=None):
    return {"id": identifier, "aliases": aliases or [], "fix_versions": fixes or []}


def test_pytest_pins_are_patched_and_consistent():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["optional-dependencies"]["dev"] == ["pytest==9.0.3"]
    assert "pytest==9.0.3" in (ROOT / "requirements.txt").read_text().splitlines()
    for requirements in [project["dependencies"], *project["optional-dependencies"].values()]:
        assert not any("pip-audit" in requirement for requirement in requirements)


def test_aliases_and_duplicate_rows_count_once_with_all_affected_packages():
    from tools.dependency_audit import normalize

    report = normalize({"dependencies": [
        dependency(vulns=[vuln(CVE, fixes=["9.0.3"]), vuln(CVE)]),
        dependency(vulns=[vuln(GHSA)]),
        # A later row bridges two previously separate groups.
        dependency(vulns=[vuln("PYSEC-2026-1", [CVE, GHSA])]),
        dependency("other", "1.0", [vuln(GHSA, [CVE], ["2.0"])]),
    ]})
    assert report["vulnerability_count"] == 1
    finding, = report["vulnerabilities"]
    assert finding["id"] == CVE
    assert finding["aliases"] == sorted([CVE, GHSA, "PYSEC-2026-1"])
    assert finding["packages"] == [
        {"name": "other", "version": "1.0", "fix_versions": ["2.0"]},
        {"name": "pytest", "version": "8.4.0", "fix_versions": ["9.0.3"]},
    ]


def test_distinct_advisories_are_not_collapsed_by_package_or_version():
    from tools.dependency_audit import normalize

    report = normalize({"dependencies": [dependency(vulns=[vuln(), vuln("CVE-2026-1")])]})
    assert report["vulnerability_count"] == 2


@pytest.mark.parametrize("data", [
    {}, {"dependencies": []}, {"dependencies": [{"name": "x", "skip_reason": "unknown"}]},
    {"dependencies": [{"name": "x", "version": "1"}]},
    {"dependencies": [dependency(vulns=[{"id": ""}])]},
    {"dependencies": [dependency(vulns=[vuln(aliases=[123])])]},
])
def test_incomplete_or_skipped_reports_fail_closed(data):
    from tools.dependency_audit import normalize

    with pytest.raises(ValueError):
        normalize(data)


@pytest.mark.parametrize("returncode, findings, expected", [(0, False, 0), (1, True, 1),
                                                            (2, False, 2), (1, False, 2), (0, True, 2)])
def test_cli_preserves_failures_and_writes_reviewable_reports(tmp_path, monkeypatch,
                                                            returncode, findings, expected):
    from tools.dependency_audit import main

    requirements = tmp_path / "resolved.txt"
    requirements.write_text("pytest==9.0.3\n")
    output = tmp_path / "audit.json"

    def scanner(command, **kwargs):
        assert command[1:3] == ["-m", "pip_audit"]
        assert all(flag in command for flag in ["--strict", "--no-deps", "--disable-pip"])
        assert command[command.index("--aliases") + 1] == "on"
        assert command[command.index("-r") + 1] == str(requirements)
        raw = Path(command[command.index("-o") + 1])
        raw.write_text(json.dumps({"dependencies": [dependency(vulns=[vuln()] if findings else [])]}))
        return subprocess.CompletedProcess(command, returncode)

    monkeypatch.setattr(subprocess, "run", scanner)
    assert main([str(requirements), "--output", str(output)]) == expected
    if expected != 2:
        assert json.loads(output.read_text())["vulnerability_count"] == int(findings)
        assert output.with_suffix(".raw.json").exists()


def test_scanner_network_failure_cannot_reuse_stale_report(tmp_path, monkeypatch):
    from tools.dependency_audit import main

    output = tmp_path / "audit.json"
    output.write_text('{"vulnerability_count": 0}')
    output.with_suffix(".raw.json").write_text('{"dependencies": []}')
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1))
    assert main([str(tmp_path / "resolved.txt"), "--output", str(output)]) == 2
    assert not output.exists()


def test_pip_resolution_includes_transitive_packages_but_excludes_local_project():
    from tools.dependency_audit import freeze_report

    data = {"version": "1", "install": [
        {"metadata": {"name": "graph-engine-memory", "version": "0.7.0"},
         "download_info": {"dir_info": {}}},
        {"metadata": {"name": "pytest", "version": "9.0.3"}, "requested": True},
        {"metadata": {"name": "pluggy", "version": "1.7.0"}, "requested": False},
    ]}
    assert freeze_report(data) == "pluggy==1.7.0\npytest==9.0.3\n"


@pytest.mark.parametrize("data", [{}, {"version": "1", "install": []},
    {"version": "2", "install": []},
    {"version": "1", "install": [{"metadata": {"name": "x\n-r evil", "version": "1"}}]},
])
def test_incomplete_or_invalid_pip_resolution_fails(data):
    from tools.dependency_audit import freeze_report

    with pytest.raises(ValueError):
        freeze_report(data)


@pytest.mark.parametrize("payload", [{"dependencies": [dependency(), {"name": "x", "skip_reason": "missing"}]},
                                     {"dependencies": []}, None])
def test_cli_rejects_skipped_or_broken_scans(tmp_path, monkeypatch, payload):
    from tools.dependency_audit import main

    output = tmp_path / "audit.json"

    def scanner(command, **kwargs):
        Path(command[command.index("-o") + 1]).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", scanner)
    assert main(["requirements.txt", "--output", str(output)]) == 2
    assert not output.exists()
