# -*- coding: utf-8 -*-

import os
import logging
import pytest
import subprocess

from typing import List
from unittest.mock import patch

from gordo_components.server.server import run_cmd
from gordo_components import serializer
from gordo_components.server import server

import tests.utils as tu


logger = logging.getLogger(__name__)


def test_healthcheck_endpoint(base_route, gordo_ml_server_client):
    """
    Test expected behavior of /<gordo-name>/healthcheck
    """
    # Should also be at the very lowest level as well.
    resp = gordo_ml_server_client.get(f"/healthcheck")
    assert resp.status_code == 200

    resp = gordo_ml_server_client.get(f"{base_route}/healthcheck")
    assert resp.status_code == 200

    data = resp.get_json()
    logger.debug(f"Got resulting JSON response: {data}")
    assert "gordo-server-version" in data


def test_response_header_timing(base_route, gordo_ml_server_client):
    """
    Test that the response contains a `Server-Timing` header
    """
    resp = gordo_ml_server_client.get(f"{base_route}/healthcheck")
    assert resp.status_code == 200
    assert "Server-Timing" in resp.headers
    assert "request_walltime_s" in resp.headers["Server-Timing"]


def test_metadata_endpoint(base_route, gordo_ml_server_client):
    """
    Test the expected behavior of /metadata
    """
    resp = gordo_ml_server_client.get(f"{base_route}/metadata")
    assert resp.status_code == 200

    data = resp.get_json()
    assert "metadata" in data
    assert data["metadata"]["name"] == tu.GORDO_SINGLE_TARGET


def test_download_model(base_route, gordo_ml_server_client):
    """
    Test we can download a model, loadable via serializer.loads()
    """
    resp = gordo_ml_server_client.get(f"{base_route}/download-model")

    serialized_model = resp.get_data()
    model = serializer.loads(serialized_model)

    # All models have a fit method
    assert hasattr(model, "fit")

    # Models MUST have either predict or transform
    assert hasattr(model, "predict") or hasattr(model, "transform")


def test_run_cmd(monkeypatch):
    """
    Test that execution error catchings work as expected
    """

    # Call command that raises FileNotFoundError, a subclass of OSError
    cmd = ["gumikorn", "gordo_components.server.server:app"]
    with pytest.raises(OSError):
        run_cmd(cmd)

    # Call command that raises a CalledProcessError
    cmd = ["ping", "--bad-option"]
    with pytest.raises(subprocess.CalledProcessError):
        run_cmd(cmd)


@pytest.mark.parametrize("revisions", [("1234", "2345", "3456"), ("1234",)])
def test_list_revisions(tmpdir, revisions: List[str]):
    """
    Verify the server is capable of returning the project revisions
    it's capable of serving.
    """

    # Server gets the 'latest' directory to serve models from, but knows other
    # revisions should be available a step up from this directory.
    model_dir = os.path.join(tmpdir, revisions[0])

    # Make revision directories under the tmpdir
    [os.mkdir(os.path.join(tmpdir, rev)) for rev in revisions]  # type: ignore

    # Request from the server what revisions it can serve, should match
    with tu.temp_env_vars(MODEL_COLLECTION_DIR=model_dir):
        app = server.build_app()
        app.testing = True
        client = app.test_client()
        resp = client.get("/gordo/v0/test-project/revisions")

    assert set(resp.json.keys()) == {"latest", "available-revisions"}
    assert resp.json["latest"] == model_dir
    assert isinstance(resp.json["available-revisions"], list)
    assert set(resp.json["available-revisions"]) == set(revisions)


def test_list_revisions_listdir_fail(caplog):
    """
    Verify the server will not fail if listing directories above the current
    model collection directory it has, fails.
    """

    def listdir_fail(*args, **kwargs):
        raise FileNotFoundError()

    expected_revision = "some-project-revision-123"

    with patch.object(os, "listdir", side_effect=listdir_fail) as mocked_listdir:
        with caplog.at_level(logging.CRITICAL):
            with tu.temp_env_vars(MODEL_COLLECTION_DIR=expected_revision):
                app = server.build_app()
                app.testing = True
                client = app.test_client()
                resp = client.get("/gordo/v0/test-project/revisions")

    assert mocked_listdir.called_once()
    assert set(resp.json.keys()) == {"latest", "available-revisions"}
    assert resp.json["latest"] == expected_revision
    assert isinstance(resp.json["available-revisions"], list)
    assert resp.json["available-revisions"] == [expected_revision]
