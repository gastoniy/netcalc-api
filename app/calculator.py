"""Pure subnet-calculation logic, decoupled from the web framework.

Everything here is a plain input -> output transformation. Keeping it
framework-free means each function can be unit-tested directly, with no
HTTP client, no app fixture, no mocking. The FastAPI layer (main.py) is
just a thin adapter over these functions.
"""

from __future__ import annotations

import ipaddress
from typing import Any

# Guard against pathological splits. A /8 split into /32s is 16.7M
# subnets and would happily eat all available memory. Validating input
# bounds is cheap insurance and a habit worth showing.
MAX_SUBNETS = 1024


def _usable_host_count(net: ipaddress._BaseNetwork) -> int:
    """Count usable hosts WITHOUT enumerating them.

    Materialising hosts (list(net.hosts())) is fine for a /24 but fatal for
    an IPv6 /64 (2**64 addresses -> OOM). We mirror the rules ipaddress uses:
      * /32 (or /128): exactly 1 host
      * /31 (or /127): exactly 2 hosts (RFC 3021 point-to-point)
      * otherwise IPv4 reserves network + broadcast (-2),
        IPv6 reserves only the Subnet-Router anycast (-1).
    """
    max_prefix = net.max_prefixlen
    if net.prefixlen >= max_prefix:
        return 1
    if net.prefixlen == max_prefix - 1:
        return 2
    return net.num_addresses - (2 if net.version == 4 else 1)


def _usable_bounds(net: ipaddress._BaseNetwork) -> tuple[str | None, str | None]:
    """First and last usable host via O(1) indexing, never a full scan."""
    if _usable_host_count(net) == 0:
        return None, None

    first = next(iter(net.hosts()))  # hosts() is a list for /32, iterator otherwise

    if net.prefixlen >= net.max_prefixlen:  # /32 or /128: single host
        last = net[0]
    elif net.version == 4 and net.prefixlen < 31:
        last = net[-2]  # exclude the IPv4 broadcast address
    else:
        last = net[-1]

    return str(first), str(last)


def describe_network(cidr: str) -> dict[str, Any]:
    """Return a structured description of a network given its CIDR.

    `strict=False` lets us accept host bits being set (e.g. 192.168.1.10/24)
    and normalise to the network address, which is the friendlier behaviour
    for a calculator.
    """
    net = ipaddress.ip_network(cidr, strict=False)
    first_host, last_host = _usable_bounds(net)

    return {
        "cidr": str(net),
        "version": net.version,
        "network_address": str(net.network_address),
        # IPv6 has no broadcast concept, so we report it only for IPv4.
        "broadcast_address": (
            str(net.broadcast_address) if net.version == 4 else None
        ),
        "netmask": str(net.netmask),
        "prefix_length": net.prefixlen,
        "num_addresses": net.num_addresses,
        "num_usable_hosts": _usable_host_count(net),
        "first_usable_host": first_host,
        "last_usable_host": last_host,
        "is_private": net.is_private,
    }


def network_contains(cidr: str, ip: str) -> dict[str, Any]:
    """Check whether a given IP address falls within a network."""
    net = ipaddress.ip_network(cidr, strict=False)
    addr = ipaddress.ip_address(ip)

    if addr.version != net.version:
        raise ValueError(
            f"IP version mismatch: {addr} is IPv{addr.version}, "
            f"network is IPv{net.version}"
        )

    return {
        "cidr": str(net),
        "ip": str(addr),
        "contained": addr in net,
    }


def split_network(cidr: str, new_prefix: int) -> dict[str, Any]:
    """Split a network into equal-sized subnets of `new_prefix` length."""
    net = ipaddress.ip_network(cidr, strict=False)

    max_prefix = 32 if net.version == 4 else 128
    if not (0 <= new_prefix <= max_prefix):
        raise ValueError(
            f"new prefix /{new_prefix} out of range for IPv{net.version} "
            f"(0..{max_prefix})"
        )
    if new_prefix < net.prefixlen:
        raise ValueError(
            f"new prefix /{new_prefix} must be >= current prefix "
            f"/{net.prefixlen} (a smaller prefix would widen, not split)"
        )

    count = 2 ** (new_prefix - net.prefixlen)
    if count > MAX_SUBNETS:
        raise ValueError(
            f"split would produce {count} subnets; limit is {MAX_SUBNETS}"
        )

    subnets = [str(s) for s in net.subnets(new_prefix=new_prefix)]
    return {
        "cidr": str(net),
        "new_prefix": new_prefix,
        "subnet_count": len(subnets),
        "subnets": subnets,
    }
