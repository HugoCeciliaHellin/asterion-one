"""
Asterion One — Digital Twin Smoke Test
========================================
Verifies that Twin segment imports are functional.
Real tests added in Phase 4.
"""


def test_twin_package_importable():
    """Verify the twin package initializes correctly."""
    import twin
    assert twin is not None


def test_numpy_available():
    """Verify NumPy is installed and functional."""
    import numpy as np
    # Basic sanity: RC model will use these operations
    arr = np.array([1.0, 2.0, 3.0])
    assert arr.mean() == 2.0
    assert len(arr) == 3
