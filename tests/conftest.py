"""Keeps the test run from flipping the real desktop's do-not-disturb."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def no_real_do_not_disturb() -> Iterator[None]:
    with patch("omarchy_focus.notifications._ask", return_value=None):
        yield
