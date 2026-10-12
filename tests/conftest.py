"""Opt-in strict skip handling for CI suites with required dependencies."""

import pytest


def pytest_addoption(parser):
    parser.addoption("--fail-on-skip", action="store_true",
                     help="Fail if any selected test or module is skipped")


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    if (session.config.getoption("--fail-on-skip") and reporter is not None
            and reporter.stats.get("skipped") and exitstatus == 0):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        reporter.write_sep("=", "Skipped tests are forbidden by --fail-on-skip", red=True)
