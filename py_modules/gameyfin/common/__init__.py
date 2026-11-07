"""Code shared by PlayingKarrde's Decky plugins (gameyfin-decky, romm-decky).

This package is copied into each plugin as ``py_modules/<plugin>/common/`` by
``sync.sh``; don't edit those copies. Modules here know nothing about Gameyfin or
RomM: anything source-specific stays in the plugin. Stdlib only, and imports within
the package are relative so the copy works under any parent package.
"""
