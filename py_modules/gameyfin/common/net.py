"""HTTP plumbing every plugin needs: the system CA bundle, a User-Agent, one error type."""

from __future__ import annotations

import functools
import os
import ssl
import urllib.request
from dataclasses import dataclass

# Sent with every request (Cloudflare 403s urllib's default). The plugin sets its own
# with set_user_agent() when its client module is imported.
USER_AGENT = "decky-common"

# Decky's bundled (PyInstaller) Python has no usable CA store, so HTTPS fails with
# CERTIFICATE_VERIFY_FAILED. Point it at the system bundle that SteamOS ships.
_CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ca-certificates/extracted/tls-ca-bundle.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
)


def set_user_agent(ua: str) -> None:
    global USER_AGENT
    USER_AGENT = ua


def user_agent() -> str:
    return USER_AGENT


@functools.lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    for path in _CA_BUNDLES:
        if os.path.isfile(path):
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


def urlopen(req, timeout: float):
    """urllib.request.urlopen with the system CA bundle. Use for every request."""
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


class PluginError(Exception):
    """API or transport failure, with a message fit to show the user.

    Plugins alias it (``GameyfinError = PluginError``) rather than subclass it, so an
    error raised here is caught by the plugin's own ``except``."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code

    def to_dict(self) -> dict:
        return {"message": str(self), "status": self.status, "code": self.code}


@dataclass
class Image:
    data: bytes
    content_type: str
