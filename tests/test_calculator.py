"""Unit tests for the pure calculator logic (no HTTP involved)."""

import ipaddress

import pytest

from app import calculator


class TestDescribeNetwork:
    def test_standard_24(self):
        info = calculator.describe_network("192.168.1.0/24")
        assert info["network_address"] == "192.168.1.0"
        assert info["broadcast_address"] == "192.168.1.255"
        assert info["netmask"] == "255.255.255.0"
        assert info["num_addresses"] == 256
        assert info["num_usable_hosts"] == 254
        assert info["first_usable_host"] == "192.168.1.1"
        assert info["last_usable_host"] == "192.168.1.254"
        assert info["is_private"] is True

    def test_host_bits_are_normalised(self):
        # strict=False: a host address is accepted and snapped to its network.
        info = calculator.describe_network("192.168.1.42/24")
        assert info["cidr"] == "192.168.1.0/24"

    def test_public_address_flagged_not_private(self):
        info = calculator.describe_network("8.8.8.0/24")
        assert info["is_private"] is False

    def test_slash_31_is_point_to_point(self):
        # RFC 3021: a /31 has two usable hosts, no network/broadcast reserve.
        info = calculator.describe_network("10.0.0.0/31")
        assert info["num_usable_hosts"] == 2
        assert info["first_usable_host"] == "10.0.0.0"
        assert info["last_usable_host"] == "10.0.0.1"

    def test_slash_32_single_host(self):
        info = calculator.describe_network("10.0.0.5/32")
        assert info["num_addresses"] == 1
        assert info["num_usable_hosts"] == 1
        assert info["first_usable_host"] == "10.0.0.5"
        assert info["last_usable_host"] == "10.0.0.5"

    def test_ipv6_has_no_broadcast(self):
        info = calculator.describe_network("2001:db8::/64")
        assert info["version"] == 6
        assert info["broadcast_address"] is None

    def test_ipv6_64_does_not_enumerate(self):
        # Regression guard: a /64 must be summarised arithmetically, never by
        # materialising 2**64 hosts. If this hangs or OOMs, the bug is back.
        info = calculator.describe_network("2001:db8::/64")
        assert info["num_addresses"] == 2**64
        assert info["num_usable_hosts"] == 2**64 - 1
        assert info["first_usable_host"] == "2001:db8::1"

    @pytest.mark.parametrize(
        "bad", ["not-a-cidr", "192.168.1.0/33", "999.0.0.0/24", ""]
    )
    def test_invalid_input_raises(self, bad):
        with pytest.raises(ValueError):
            calculator.describe_network(bad)


class TestNetworkContains:
    def test_ip_inside(self):
        result = calculator.network_contains("10.0.0.0/8", "10.1.2.3")
        assert result["contained"] is True

    def test_ip_outside(self):
        result = calculator.network_contains("10.0.0.0/8", "192.168.1.1")
        assert result["contained"] is False

    def test_version_mismatch_raises(self):
        with pytest.raises(ValueError):
            calculator.network_contains("10.0.0.0/8", "2001:db8::1")

    def test_invalid_ip_raises(self):
        with pytest.raises(ValueError):
            calculator.network_contains("10.0.0.0/8", "nope")


class TestSplitNetwork:
    def test_split_24_into_26(self):
        result = calculator.split_network("192.168.0.0/24", 26)
        assert result["subnet_count"] == 4
        assert result["subnets"] == [
            "192.168.0.0/26",
            "192.168.0.64/26",
            "192.168.0.128/26",
            "192.168.0.192/26",
        ]

    def test_split_into_same_prefix_is_identity(self):
        result = calculator.split_network("192.168.0.0/24", 24)
        assert result["subnet_count"] == 1
        assert result["subnets"] == ["192.168.0.0/24"]

    def test_smaller_prefix_raises(self):
        # /23 is wider than /24, not a split.
        with pytest.raises(ValueError):
            calculator.split_network("192.168.0.0/24", 23)

    def test_oversized_split_is_rejected(self):
        # /8 -> /32 would be 16.7M subnets; must be refused, not attempted.
        with pytest.raises(ValueError):
            calculator.split_network("10.0.0.0/8", 32)

    def test_prefix_out_of_range_raises(self):
        with pytest.raises(ValueError):
            calculator.split_network("192.168.0.0/24", 40)

    def test_split_count_matches_math(self):
        result = calculator.split_network("192.168.0.0/24", 28)
        net = ipaddress.ip_network("192.168.0.0/24")
        assert result["subnet_count"] == 2 ** (28 - net.prefixlen)
