"""PyInstaller entry shim — the frozen sidecar's __main__.

Mirrors the `tempest-server` console script exactly (see tempest-server.spec); everything
runtime-relevant lives in `tempest_api.server.main`, never here.
"""

from tempest_api.server import main

if __name__ == "__main__":
    main()
