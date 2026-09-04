"""Test package bootstrap.

Ensures the ``code/`` directory (which contains the ``orbit`` package) is on
sys.path so tests can run from anywhere with:

    python -m unittest discover -s tests -v

from the ``code/`` directory, or simply ``python -m unittest`` .
"""
import os
import sys

# Add the parent of this tests/ dir (the code/ root) to sys.path.
_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)
