"""Try IPv4 before IPv6 when opening connections.

urllib connects to each resolved address in turn and waits out the full timeout
on every one that does not answer. Yahoo resolves to four IPv6 addresses ahead
of its IPv4 ones, so on a network whose IPv6 route is broken each request sat
through four timeouts - about a minute per symbol - before reaching an address
that answers in milliseconds. Browsers and curl race both families and never
notice; urllib does not race.

Reordering keeps IPv6 available as a fallback for IPv6-only networks while
making the common case fast. Installing it once at package import covers every
module that downloads, including any added later.
"""

from __future__ import annotations

import socket

_original_getaddrinfo = socket.getaddrinfo


def _ipv4_first(*args, **kwargs):
    results = _original_getaddrinfo(*args, **kwargs)
    # Stable sort: within each family the resolver's own order is preserved.
    return sorted(results, key=lambda item: 0 if item[0] == socket.AF_INET else 1)


def prefer_ipv4() -> None:
    if socket.getaddrinfo is not _ipv4_first:
        socket.getaddrinfo = _ipv4_first
