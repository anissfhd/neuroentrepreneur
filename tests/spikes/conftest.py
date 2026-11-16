"""Ferme les checkpointers ouverts par les tests techniques."""

from __future__ import annotations

import pytest

from spikes.spike_support import close_savers


@pytest.fixture(autouse=True)
def _close_spike_savers():
    yield
    close_savers()
