"""Opt-in strict skip handling for CI suites with required dependencies."""

import pytest


@pytest.fixture(params=[
    "{broken json", "{}", "[]", "null", '"text"',
    '{"id": "bad"}', '{"vec": [1, 0]}',
    '{"id": [], "vec": [1, 0]}', '{"id": "bad", "vec": null}',
    '{"id": "bad", "vec": "12"}', '{"id": "bad", "vec": [true, 0]}',
    '{"id": "bad", "vec": ["1", 0]}',
    '{"id": "bad", "vec": [NaN, 0]}',
    '{"id": "bad", "vec": [Infinity, 0]}',
    '{"id": "bad", "vec": [-1e999, 0]}',
    '{"id": "bad", "vec": [' + "9" * 400 + ', 0]}',
    '{"id": "short", "vec": [1]}\n{"id": "empty", "vec": []}',
    # Count final records, not overwritten lines, when selecting a dimension.
    '{"id": "short", "vec": [1]}\n' * 4,
], ids=[
    "malformed", "empty-object", "array", "null", "string", "missing-vec",
    "missing-id", "invalid-id", "null-vec", "string-vec", "boolean-value",
    "string-value", "nan", "infinity", "float-overflow", "integer-overflow",
    "mixed-dimensions", "repeated-dimension",
])
def damaged_vector_cache(request):
    """Disposable damage alongside a valid pair with cosine 0.8."""
    return ('{"id": "a", "vec": [1, 0]}\n' + request.param + '\n'
            '{"id": "b", "vec": [0.8, 0.6]}\n')


def pytest_addoption(parser):
    parser.addoption("--fail-on-skip", action="store_true",
                     help="Fail if any selected test or module is skipped")


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    if (session.config.getoption("--fail-on-skip") and reporter is not None
            and reporter.stats.get("skipped") and exitstatus == 0):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        reporter.write_sep("=", "Skipped tests are forbidden by --fail-on-skip", red=True)
