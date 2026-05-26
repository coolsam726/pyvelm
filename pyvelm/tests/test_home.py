"""Tests for site entry URL configuration."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from pyvelm.home import (
    DEFAULT_HOME_URL,
    home_url,
    landing_enabled,
    login_destination,
    login_url,
)


class HomeUrlTests(unittest.TestCase):
    def test_default_home(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYVELM_HOME_URL", None)
            self.assertEqual(home_url(), DEFAULT_HOME_URL)

    def test_root_home(self):
        with patch.dict(os.environ, {"PYVELM_HOME_URL": "/"}):
            self.assertEqual(home_url(), "/")

    def test_view_home(self):
        with patch.dict(
            os.environ,
            {"PYVELM_HOME_URL": "/web/views/feedback_signals/home"},
        ):
            self.assertEqual(
                home_url(), "/web/views/feedback_signals/home"
            )

    def test_login_destination_honors_next(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYVELM_HOME_URL", None)
            self.assertEqual(
                login_destination("/web/views/crm/lead.list"),
                "/web/views/crm/lead.list",
            )

    def test_login_url_includes_next(self):
        with patch.dict(os.environ, {"PYVELM_HOME_URL": "/"}):
            self.assertEqual(login_url(), "/login?next=%2F")

    def test_landing_flag(self):
        with patch.dict(os.environ, {"PYVELM_LANDING": "0"}):
            self.assertFalse(landing_enabled())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYVELM_LANDING", None)
            self.assertTrue(landing_enabled())
