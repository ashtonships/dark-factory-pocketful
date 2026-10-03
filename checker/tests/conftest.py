"""Shared fixtures for the Checker's Pocketful checks.

Every check is tagged with the work item that introduces the behaviour it checks
(`@pytest.mark.item("W-n")`); only items listed in PF_ITEMS run.
"""

from __future__ import annotations

import os

import pytest

from pf import Api, base_fixture

ITEMS = {i for i in os.environ.get("PF_ITEMS", "").split(",") if i}


def pytest_configure(config):
    config.addinivalue_line("markers", "item(id): work item that introduces the checked behaviour")


def pytest_collection_modifyitems(config, items):
    keep, drop = [], []
    for it in items:
        m = it.get_closest_marker("item")
        if m is None:
            raise pytest.UsageError(f"{it.nodeid} has no item marker")
        (keep if m.args[0] in ITEMS else drop).append(it)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


@pytest.fixture(scope="session")
def api() -> Api:
    a = Api(os.environ["PF_BASE_URL"])
    yield a
    a.close()


@pytest.fixture
def seeded(api):
    """Reset to the base fixture and return logged-in sessions by handle."""
    fx = base_fixture()
    api.reset(fx)
    return api.sessions(fx)
