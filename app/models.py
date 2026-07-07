"""Pydantic response models.

Declaring response shapes explicitly gives us validated, self-documenting
output and a clean OpenAPI schema at /docs for free.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NetworkInfo(BaseModel):
    cidr: str = Field(examples=["192.168.1.0/24"])
    version: int
    network_address: str
    broadcast_address: str | None
    netmask: str
    prefix_length: int
    num_addresses: int
    num_usable_hosts: int
    first_usable_host: str | None
    last_usable_host: str | None
    is_private: bool


class ContainsResult(BaseModel):
    cidr: str
    ip: str
    contained: bool


class SplitResult(BaseModel):
    cidr: str
    new_prefix: int
    subnet_count: int
    subnets: list[str]


class Health(BaseModel):
    status: str = Field(examples=["ok"])


class ServiceInfo(BaseModel):
    service: str
    version: str
