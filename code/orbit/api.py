"""
Orbit — API entrypoint shim.

Lets you run the server as documented:

    python -m orbit.api

The implementation lives in ``orbit.services.api``.
"""
from .services.api import main, serve  # re-export

__all__ = ["main", "serve"]

if __name__ == "__main__":
    main()
