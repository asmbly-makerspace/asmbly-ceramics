"""The app's package is installed and importable, so the coverage floor measures src/.

Replace this with the first real test when the app's code lands.
"""

import importlib


def test_the_package_imports_from_src() -> None:
    package = importlib.import_module("asmbly_ceramics")
    assert package.__file__ is not None
    assert package.__file__.replace("\\", "/").endswith("src/asmbly_ceramics/__init__.py")
