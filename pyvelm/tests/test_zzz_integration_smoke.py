"""Optional full-stack smoke via ``examples/basic.py``.

The maintained HTTP path is ``test_http_smoke.py``. Enable this only when
explicitly debugging the large demo script::

    PYVELM_RUN_FULL_BASIC=1 pytest pyvelm/tests/test_zzz_integration_smoke.py -v
"""
from __future__ import annotations

import os

import pytest

from pyvelm.tests.conftest import reset_public_schema


@pytest.mark.integration
def test_examples_basic_smoke(pyvelm_dsn: str):
    if not os.environ.get("PYVELM_RUN_FULL_BASIC"):
        pytest.skip("set PYVELM_RUN_FULL_BASIC=1 to run examples/basic.py")
    reset_public_schema(pyvelm_dsn)
    from examples import basic

    basic.main()
