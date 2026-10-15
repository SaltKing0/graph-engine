"""CI-only pip-audit gate over a frozen environment, with alias deduplication.

Run in a separate environment containing pip-audit; the input must contain
all resolved transitive dependencies, as frozen requirements or a pip report.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import subprocess
import sys
from typing import Any


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(s, str) or not s for s in value):
        raise ValueError("Expected a list of nonempty strings in audit report")
    return value


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Group connected advisory IDs, retaining every affected package and fix."""
    dependencies = data.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("Audit report must contain resolved dependencies")
    graph: dict[str, set[str]] = {}
    records = []
    for dep in dependencies:
        if not isinstance(dep, dict) or "skip_reason" in dep:
            raise ValueError(f"Unaudited dependency: {dep!r}")
        name, version, vulns = dep.get("name"), dep.get("version"), dep.get("vulns")
        if not all(isinstance(v, str) and v for v in (name, version)) or not isinstance(vulns, list):
            raise ValueError(f"Incomplete dependency: {dep!r}")
        for vuln in vulns:
            if not isinstance(vuln, dict):
                raise ValueError("Invalid vulnerability record")
            identifier = vuln.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("Vulnerability is missing its ID")
            ids = {identifier, *_strings(vuln.get("aliases", []))}
            fixes = _strings(vuln.get("fix_versions", []))
            for alias in ids:
                graph.setdefault(alias, set()).update(ids)
            records.append((identifier, name, version, fixes))

    groups: dict[str, dict[str, Any]] = {}
    canonical: dict[str, str] = {}
    for identifier in sorted(graph):
        if identifier in canonical:
            continue
        connected: set[str] = set()
        pending = [identifier]
        while pending:
            alias = pending.pop()
            if alias not in connected:
                connected.add(alias)
                pending.extend(graph[alias] - connected)
        # Prefer a CVE, then GHSA, then database-specific identifiers.
        key = min(connected, key=lambda s: (0 if s.startswith("CVE-") else
                                          1 if s.startswith("GHSA-") else 2, s))
        canonical.update(dict.fromkeys(connected, key))
        groups[key] = {"id": key, "aliases": sorted(connected), "packages": {}}
    for identifier, name, version, fixes in records:
        packages = groups[canonical[identifier]]["packages"]
        packages.setdefault((name, version), set()).update(fixes)
    findings = []
    for key in sorted(groups):
        group = groups[key]
        group["packages"] = [
            {"name": name, "version": version, "fix_versions": sorted(fixes)}
            for (name, version), fixes in sorted(group["packages"].items())
        ]
        findings.append(group)
    return {"vulnerability_count": len(findings), "vulnerabilities": findings}


def freeze_report(data: dict[str, Any]) -> str:
    """Convert pip's dry-run resolution into exact requirements for the scanner."""
    installs = data.get("install")
    if data.get("version") != "1" or not isinstance(installs, list) or not installs:
        raise ValueError("Expected a nonempty pip installation report (version 1)")
    requirements = set()
    for item in installs:
        metadata = item["metadata"]
        name, version = metadata["name"], metadata["version"]
        # Exclude only our local source tree, not a published dependency.
        if (name == "graph-engine-memory" and
                "dir_info" in item.get("download_info", {})):
            continue
        # Keep generated requirements limited to package names and exact versions.
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
                or not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version)):
            raise ValueError("Invalid name/version in pip installation report")
        requirements.add(f"{name}=={version}")
    if not requirements:
        raise ValueError("No resolved dependencies to audit")
    return "\n".join(sorted(requirements)) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements", type=Path, help="Frozen requirements or pip installation report")
    parser.add_argument("--pip-report", action="store_true", help="Input is pip --dry-run --report JSON")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    raw = args.output.with_suffix(".raw.json")
    # A failed scanner must never reuse an earlier successful result.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.unlink(missing_ok=True)
    raw.unlink(missing_ok=True)
    try:
        requirements = args.requirements
        if args.pip_report:
            requirements = args.output.with_suffix(".requirements.txt")
            requirements.unlink(missing_ok=True)
            requirements.write_text(freeze_report(json.loads(args.requirements.read_text())))
        result = subprocess.run([
            sys.executable, "-m", "pip_audit", "-r", str(requirements),
            "--no-deps", "--disable-pip", "--strict", "--aliases", "on",
            "--progress-spinner", "off", "-f", "json", "-o", str(raw),
        ], check=False)
        if result.returncode not in (0, 1):
            raise ValueError(f"pip-audit failed with status {result.returncode}")
        report = normalize(json.loads(raw.read_text()))
        if result.returncode != bool(report["vulnerability_count"]):
            raise ValueError("Scanner status disagrees with report; audit is incomplete")
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        print(f"Advisory check failed: {exc}", file=sys.stderr)
        return 2
    print(f"Unique advisories: {report['vulnerability_count']}")
    for finding in report["vulnerabilities"]:
        affected = ", ".join(f"{p['name']}=={p['version']}" for p in finding["packages"])
        print(f"  {finding['id']}: {affected}")
    return int(bool(report["vulnerability_count"]))


if __name__ == "__main__":
    raise SystemExit(main())
