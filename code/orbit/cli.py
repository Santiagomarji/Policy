"""
Orbit — CLI entrypoint shim.

Lets you run the CLI as documented:

    python -m orbit.cli ...

The implementation lives in ``orbit.services.cli``.
"""
from .services.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
