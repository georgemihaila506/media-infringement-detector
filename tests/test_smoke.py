import importlib

import pytest

MODULES = [
    "infringement.common.settings",
    "infringement.matcher.video",
    "infringement.matcher.photo",
    "infringement.matcher.audio",
    "infringement.engine.transport",
    "infringement.activities.handler",
]


@pytest.mark.parametrize("name", MODULES)
def test_imports(name):
    importlib.import_module(name)


def test_hamming():
    from infringement.matcher.phash import hamming

    assert hamming(0b1011, 0b0001) == 2
