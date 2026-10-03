"""W-1: delivery and runtime facts measured by run_checks.py when it built and started the image."""

from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.item("W-1")


@pytest.fixture(scope="module")
def facts():
    path = os.environ.get("PF_RUNTIME")
    if not path:
        pytest.skip("service not started by run_checks.py (--base-url mode)")
    return json.loads(open(path).read())


def test_delivery_files_and_run_md(facts):
    # ledger: 15, 18, 25 (one documented docker build + docker run; no compose)
    assert facts["dockerfile"] and facts["run_md_build_and_run"], facts


def test_image_builds_and_runs_alone(facts):
    # ledger: 22, 24, 34 (one container, -e PORT and a port mapping, nothing else)
    assert facts["build_ok"] and facts["port_env_healthy_seconds"] is not None, facts


def test_healthy_within_60s_under_limits(facts):
    # ledger: 27, 28, 29, 37, 38 (non-200 tolerated until healthy)
    assert facts["limits"] == {"cpus": 2, "memory": "2g", "env": "PORT=9137"}
    assert facts["port_env_healthy_seconds"] < 60, facts


def test_default_port_8080(facts):
    # ledger: 36
    assert facts["default_port_healthy"] is True, facts
