from __future__ import annotations

from chitalka.updater import _version


def test_version_comparison_values():
    assert _version("v1.2.3") == (1, 2, 3)
    assert _version("1.10") > _version("1.9")
    assert _version("") == (0,)
