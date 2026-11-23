"""AWS signatures and bounded MQTT 3.1.1 framing, independent of HA."""

from __future__ import annotations

import hashlib
import hmac
import struct
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _mac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode(), hashlib.sha256).digest()


def _key(secret: str, date: str, region: str, service: str) -> bytes:
    key = _mac(("AWS4" + secret).encode(), date)
    for part in (region, service, "aws4_request"):
        key = _mac(key, part)
    return key


def signed_headers(url: str, credentials: dict, region: str, now=None) -> dict:
    """Sign GET requests to the fixed ecoNET API using temporary IAM keys."""
    parsed = urlsplit(url)
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    scope = f"{day}/{region}/execute-api/aws4_request"
    headers = {
        "appid": "0",
        "content-type": "application/json",
        "host": parsed.netloc,
        "x-amz-date": stamp,
        "x-amz-security-token": credentials["SessionToken"],
    }
    names = ";".join(sorted(headers))
    canonical_headers = "".join(f"{key}:{headers[key]}\n" for key in sorted(headers))
    canonical = "\n".join((
        "GET", quote(parsed.path or "/", safe="/~"), parsed.query,
        canonical_headers, names, _hash(""),
    ))
    to_sign = "\n".join(("AWS4-HMAC-SHA256", stamp, scope, _hash(canonical)))
    signature = _mac(_key(credentials["SecretKey"], day, region, "execute-api"), to_sign).hex()
    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={credentials['AccessKeyId']}/{scope}, "
        f"SignedHeaders={names}, Signature={signature}"
    )
    return headers


def websocket_url(endpoint: str, credentials: dict, region: str, now=None) -> str:
    """Match Amplify's IoT signing: the session token is appended unsigned."""
    parsed = urlsplit(endpoint)
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    scope = f"{day}/{region}/iotdevicegateway/aws4_request"
    query = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{credentials['AccessKeyId']}/{scope}",
        "X-Amz-Date": stamp,
        "X-Amz-SignedHeaders": "host",
    }
    canonical_query = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query.items()))
    canonical = "\n".join((
        "GET", parsed.path, canonical_query, f"host:{parsed.netloc}\n", "host", _hash(""),
    ))
    to_sign = "\n".join(("AWS4-HMAC-SHA256", stamp, scope, _hash(canonical)))
    signature = _mac(_key(credentials["SecretKey"], day, region, "iotdevicegateway"), to_sign).hex()
    token = quote(credentials["SessionToken"], safe="-_.~")
    return f"{endpoint}?{canonical_query}&X-Amz-Signature={signature}&X-Amz-Security-Token={token}"


def mqtt_string(value: str) -> bytes:
    encoded = value.encode()
    if len(encoded) > 65535:
        raise ValueError("MQTT string too large")
    return struct.pack("!H", len(encoded)) + encoded


def mqtt_packet(first: int, payload: bytes = b"") -> bytes:
    if len(payload) > 1048576:
        raise ValueError("MQTT packet too large")
    length = len(payload)
    remaining = bytearray()
    while True:
        byte = length % 128
        length //= 128
        remaining.append(byte | (128 if length else 0))
        if not length:
            break
    return bytes([first]) + remaining + payload


def mqtt_packets(buffer: bytearray) -> list[tuple[int, int, bytes]]:
    """Extract complete packets, preserving any fragmented trailing packet."""
    result = []
    while len(buffer) >= 2:
        length = 0
        multiplier = 1
        end = None
        for offset in range(1, min(len(buffer), 5)):
            byte = buffer[offset]
            length += (byte & 127) * multiplier
            if length > 1048576:
                raise ValueError("MQTT packet too large")
            if not byte & 128:
                end = offset + 1
                break
            multiplier *= 128
        if end is None:
            if len(buffer) >= 5:
                raise ValueError("Malformed MQTT remaining length")
            break
        if len(buffer) < end + length:
            break
        first = buffer[0]
        result.append((first >> 4, first & 15, bytes(buffer[end:end + length])))
        del buffer[:end + length]
    return result
