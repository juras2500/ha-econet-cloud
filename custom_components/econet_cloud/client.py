"""ecoNET Cloud client with profile-checked controls and confirmed writes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import struct
import time
from urllib.parse import quote

from .const import API_BASE, CLIENT_ID, IDENTITY_POOL_ID, IOT_ENDPOINT, REGION, USER_POOL_ID, STALE_SECONDS
from .model import parameter_updates, parameter_bounds, profile_readings
from .controls import (ControlProfile, ControlError, READ_KEYS, TEMPERATURE_KEYS, speed_command,
                       mode_command, stop_boost_command, temperature_command, validate_write, command_matches)
from .protocol import mqtt_packet, mqtt_packets, mqtt_string, signed_headers, websocket_url

LOGGER = logging.getLogger(__name__)
CLIENT_METADATA = {"appId": "0"}


class CloudError(Exception):
    """Connection/protocol error without credential-bearing details."""


class AuthError(CloudError):
    """Expired or rejected ecoNET credentials."""

    def __init__(self, message, stage="login"):
        super().__init__(message)
        self.stage = stage


def _cognito(username, refresh_token=None):
    # All SDK imports, key discovery and synchronous HTTPS run in the executor.
    from botocore import UNSIGNED
    from botocore.config import Config
    from pycognito import Cognito

    return Cognito(
        USER_POOL_ID, CLIENT_ID, username=username, refresh_token=refresh_token,
        user_pool_region=REGION,
        botocore_config=Config(signature_version=UNSIGNED, connect_timeout=10, read_timeout=20,
                              retries={"max_attempts": 1}),
    )


def _safe_auth_error(error, stage="login"):
    code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
    # Only an allowlisted code and the stage are logged, never the SDK message.
    safe_code = code if code in {"NotAuthorizedException", "UserNotFoundException", "PasswordResetRequiredException",
                                "UserNotConfirmedException", "InvalidParameterException", "ForbiddenException",
                                "RefreshTokenReuseException", "TooManyRequestsException"} else type(error).__name__
    LOGGER.warning("ecoNET authentication failed: stage=%s, code=%s", stage, safe_code)
    if code in ("NotAuthorizedException", "UserNotFoundException", "PasswordResetRequiredException", "UserNotConfirmedException"):
        return AuthError("Account authentication required", stage)
    return CloudError(f"ecoNET authentication failed at {stage}")


def _srp(user, username, password):
    from pycognito.aws_srp import AWSSRP
    return AWSSRP(username=username, password=password, pool_id=USER_POOL_ID,
                  client_id=CLIENT_ID, client=user.client)


def _authenticate_srp(user, srp):
    auth_params = srp.get_auth_params()
    challenge = user.client.initiate_auth(
        AuthFlow="USER_SRP_AUTH", ClientId=CLIENT_ID,
        AuthParameters=auth_params, ClientMetadata=CLIENT_METADATA)
    if challenge.get("ChallengeName") != "PASSWORD_VERIFIER":
        raise AuthError("Additional authentication challenge required", "challenge")
    params = {"ClientId": CLIENT_ID, "ChallengeName": "PASSWORD_VERIFIER",
              "ChallengeResponses": srp.process_challenge(challenge["ChallengeParameters"], auth_params),
              "ClientMetadata": CLIENT_METADATA}
    if challenge.get("Session"):
        params["Session"] = challenge["Session"]
    response = user.client.respond_to_auth_challenge(**params)
    if "AuthenticationResult" not in response:
        raise AuthError("Additional authentication challenge required", "challenge")
    return response


def login_sync(username, password):
    stage = "login"
    try:
        user = _cognito(username)
        srp = _srp(user, username, password)
        response = _authenticate_srp(user, srp)
        auth = response.get("AuthenticationResult") or {}
        if not auth.get("RefreshToken"):
            raise AuthError("No refresh token returned")
        user.verify_token(auth["AccessToken"], "access_token", "access")
        user.verify_token(auth["IdToken"], "id_token", "id")
        device_key = None
        if metadata := auth.get("NewDeviceMetadata"):
            # Confirm this HA session, following the same device flow as Amplify.
            # It is not explicitly marked as a remembered/MFA-exempt device.
            from pycognito.aws_srp import generate_hash_device
            stage = "device_confirmation"
            device_key = metadata["DeviceKey"]
            _, verifier = generate_hash_device(metadata["DeviceGroupKey"], device_key)
            user.client.confirm_device(AccessToken=auth["AccessToken"], DeviceKey=device_key,
                                       DeviceName="Home Assistant ecoNET Cloud",
                                       DeviceSecretVerifierConfig=verifier)
        return {"refresh_token": auth["RefreshToken"], "id_token": auth["IdToken"],
                "device_key": device_key, "expires_at": time.time() + min(auth.get("ExpiresIn", 3600), 3600)}
    except CloudError:
        raise
    except Exception as error:
        raise _safe_auth_error(error, stage) from None


def identity_sync(username, refresh_token, device_key=None, initial_id_token=None):
    stage = "refresh"
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config

        user = _cognito(username, refresh_token)
        if initial_id_token:
            id_token = initial_id_token
        else:
            params = {"ClientId": CLIENT_ID, "RefreshToken": refresh_token,
                      "ClientMetadata": CLIENT_METADATA}
            if device_key:
                params["DeviceKey"] = device_key
            # This operation also supports Cognito refresh-token rotation.
            refreshed = user.client.get_tokens_from_refresh_token(**params)["AuthenticationResult"]
            user.verify_token(refreshed["AccessToken"], "access_token", "access")
            user.verify_token(refreshed["IdToken"], "id_token", "id")
            id_token = refreshed["IdToken"]
            refresh_token = refreshed.get("RefreshToken", refresh_token)
        stage = "identity"
        identity = boto3.client("cognito-identity", region_name=REGION,
                                config=Config(signature_version=UNSIGNED, connect_timeout=10,
                                              read_timeout=20, retries={"max_attempts": 1}))
        logins = {f"cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}": id_token}
        identity_id = identity.get_id(IdentityPoolId=IDENTITY_POOL_ID, Logins=logins)["IdentityId"]
        response = identity.get_credentials_for_identity(IdentityId=identity_id, Logins=logins)
        return identity_id, response["Credentials"], refresh_token
    except CloudError:
        raise
    except Exception as error:
        raise _safe_auth_error(error, stage) from None


class CloudClient:
    def __init__(self, session, executor, username, refresh_token, installation_id=None,
                 device_key=None, auth_session=None):
        self.session = session
        self.executor = executor
        self.username = username
        self.refresh_token = refresh_token
        self.device_key = device_key or (auth_session or {}).get("device_key")
        self._initial_id_token = (auth_session or {}).get("id_token")
        self.installation_id = installation_id
        self._credentials = None
        self._identity_id = None
        self._ws = None
        self._stopping = False
        self._ready = asyncio.Event()
        self.first_values = asyncio.Event()
        self.connected = False
        self.values = {}
        self.seen = {}
        self.specs = []
        self.details = {}
        self.device = {}
        self._tx = 0
        self._on_update = None
        self._write_lock = asyncio.Lock()
        self.last_error = None
        self.message_counts = {"responses": 0, "notifications": 0, "other": 0}
        self.response_statuses = []
        self.control_profile = None
        self.bounds = {}
        self._pending = {}
        self._values_changed = asyncio.Event()
        self._command_lock = asyncio.Lock()
        self.confirmed_commands = 0
        self.last_command_error = None

    @property
    def live(self):
        return self.connected and bool(self.seen) and time.monotonic() - max(self.seen.values()) < STALE_SECONDS

    async def credentials(self, force=False):
        expiry = self._credentials.get("Expiration") if self._credentials else None
        if force or not expiry or expiry.timestamp() < time.time() + 300:
            identity, credentials, refresh = await self.executor(identity_sync, self.username, self.refresh_token,
                                                                 self.device_key, self._initial_id_token)
            self._identity_id, self._credentials, self.refresh_token = identity, credentials, refresh
            self._initial_id_token = None
        return self._credentials

    async def get(self, path):
        url = API_BASE + path
        credentials = await self.credentials()
        try:
            async with asyncio.timeout(30):
                async with self.session.get(url, headers=signed_headers(url, credentials, REGION)) as response:
                    if response.status == 401:
                        raise AuthError("Cloud API authentication rejected")
                    if response.status != 200:
                        raise CloudError(f"Cloud API returned HTTP {response.status}")
                    return await response.json()
        except CloudError:
            raise
        except Exception:
            raise CloudError("Cloud API connection failed") from None

    async def installations(self):
        response = await self.get("/v1/get-installation-list")
        if not isinstance(response, list):
            raise CloudError("Unexpected installation list")
        return response

    async def prepare(self):
        details = await self.get(f"/v1/installation/{quote(self.installation_id, safe='')}/get-details")
        self.details = details
        components = details.get("components") or []
        info = details.get("installationInfo") or {}
        specs = []
        for row in components + [info]:
            component = row.get("componentFn") or row.get("factoryNumber")
            name = row.get("componentType") or row.get("name")
            pc = row.get("producerCode")
            hw, sw = row.get("hardwareVersion"), row.get("softVersion")
            if not component or pc is None or not all((name, hw, sw)):
                continue
            if row is info:
                pc = int(pc) & 65535
            path = "/v1/profiles/" + "/".join(quote(str(part), safe="") for part in (pc, name, hw, sw)) + "/web/"
            try:
                profile = await self.get(path + "profile.json")
                try:
                    translations = await self.get(path + "trans_pl.json")
                except CloudError:
                    translations = await self.get(path + "trans_en.json")
            except AuthError:
                raise
            except CloudError:
                continue
            specs.extend(profile_readings(profile, translations, str(component), "Panel · " if row is info else ""))
            if row is not info and name == "ecoVENT MINI OEM" and self.control_profile is None:
                self.control_profile = ControlProfile.discover(profile, component)
            if row is not info and not self.device:
                self.device = {"manufacturer": row.get("producerName", "PLUM"), "model": name,
                               "sw_version": sw, "hw_version": hw}
        self.specs = list({spec.key: spec for spec in specs}.values())
        if not self.specs:
            raise CloudError("No supported measurement profile found")

    async def _send(self, packet):
        if self._ws is None or self._ws.closed:
            raise CloudError("MQTT disconnected")
        async with self._write_lock:
            await self._ws.send_bytes(packet)

    async def operation(self, name, targets=None, wait=False):
        if name == "PARAMS_MODIFICATION":
            if (self.control_profile is None or not isinstance(targets, list) or len(targets) != 1
                    or targets[0].get("component") != self.control_profile.component):
                raise ControlError("Nieobsługiwany sterownik.")
            validate_write(targets[0].get("parameters", {}), self.bounds)
        elif name not in ("GET_VALUES", "CLIENT_PING"):
            raise ValueError("Unsupported operation")
        operation = {"name": name}
        if targets is not None:
            operation["targets"] = targets
        self._tx += 1
        transaction = str(self._tx)
        body = {"transactionId": transaction, "operations": [operation]}
        topic = f"{self.installation_id}/{self._client_id}/installationRequest"
        future = asyncio.get_running_loop().create_future() if wait else None
        if future is not None:
            self._pending[transaction] = (name, future)
        try:
            await self._send(mqtt_packet(0x30, mqtt_string(topic) + json.dumps(body, separators=(",", ":")).encode()))
            if future is not None:
                try:
                    return await asyncio.wait_for(future, timeout=20)
                except TimeoutError:
                    raise CloudError("Brak odpowiedzi na polecenie. Sprawdź stan centrali przed ponowieniem.") from None
        finally:
            self._pending.pop(transaction, None)

    async def request_values(self):
        if not self.connected:
            return
        requests = {}
        for spec in self.specs:
            requests.setdefault(spec.component, []).append(spec.request_key)
        if self.control_profile:
            requests.setdefault(self.control_profile.component, []).extend(READ_KEYS)
        for component, keys in requests.items():
            keys = sorted(set(keys))
            for start in range(0, len(keys), 50):
                await self.operation("GET_VALUES", [{"component": component, "parameters": keys[start:start + 50]}])

    def control_state(self):
        if not self.control_profile:
            return {}
        component = self.control_profile.component
        return {key: self.values.get((component, key)) for key in READ_KEYS}

    def control_ready(self, keys=READ_KEYS):
        return bool(self.control_profile and self.connected and all(
            self.values.get((self.control_profile.component, key)) is not None and
            time.monotonic() - self.seen.get((self.control_profile.component, key), 0) < STALE_SECONDS
            for key in keys))

    async def set_speed(self, option):
        async with self._command_lock:
            if not self.control_ready(("u81", "u6639", "u6630", "u7074")):
                raise CloudError("Brak aktualnego połączenia z centralą.")
            await self._modify(speed_command(option, self.control_state()))

    async def set_mode(self, option):
        async with self._command_lock:
            if not self.control_ready(("u6630",)):
                raise CloudError("Brak aktualnego połączenia z centralą.")
            await self._modify(mode_command(option, self.control_state()))

    async def set_temperature(self, key, value):
        async with self._command_lock:
            if not self.control_ready((key,)):
                raise CloudError("Brak aktualnego połączenia z centralą.")
            await self._modify(temperature_command(key, value, self.bounds))

    async def stop_boost(self):
        async with self._command_lock:
            if not self.control_ready(("u6639",)):
                raise CloudError("Brak aktualnego połączenia z centralą.")
            await self._modify(stop_boost_command(self.control_state()))

    async def _modify(self, parameters):
        if not parameters:
            return
        component = self.control_profile.component
        started = time.monotonic()
        self.last_command_error = None
        try:
            response = await self.operation("PARAMS_MODIFICATION", [{"component": component,
                                             "parameters": parameters}], wait=True)
            accepted = next((target.get("parameters", {}) for target in response.get("targets", [])
                             if str(target.get("component")) == component), {})
            if str(response.get("statusCode")) != "0" or any(str(accepted.get(key)) not in ("0", "16") for key in parameters):
                raise CloudError("Sterownik odrzucił zmianę ustawienia.")
            await self.operation("GET_VALUES", [{"component": component, "parameters": list(parameters)}])
            deadline = time.monotonic() + 20
            while not (all(self.seen.get((component, key), 0) >= started for key in parameters)
                       and command_matches(parameters, self.control_state())):
                self._values_changed.clear()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                await asyncio.wait_for(self._values_changed.wait(), timeout=remaining)
            self.confirmed_commands += 1
        except TimeoutError:
            self.last_command_error = "Polecenie przyjęte, ale brak potwierdzenia nowej nastawy ze sterownika."
            raise CloudError(self.last_command_error) from None
        except CloudError as error:
            self.last_command_error = str(error)
            raise

    def _notify(self):
        if self._on_update:
            self._on_update()

    async def _published(self, flags, payload):
        if len(payload) < 2:
            raise CloudError("Invalid MQTT publish")
        length = struct.unpack("!H", payload[:2])[0]
        offset = 2 + length
        if offset > len(payload):
            raise CloudError("Invalid MQTT topic")
        qos = (flags >> 1) & 3
        if qos == 1:
            if offset + 2 > len(payload):
                raise CloudError("Invalid MQTT packet id")
            await self._send(mqtt_packet(0x40, payload[offset:offset + 2]))
            offset += 2
        elif qos != 0:
            raise CloudError("Unsupported MQTT QoS")
        try:
            parsed = json.loads(payload[offset:])
        except (ValueError, UnicodeError):
            return
        topic = payload[2:2 + length].decode("utf-8", errors="replace")
        category = ("responses" if topic.endswith("/installationResponse") else
                    "notifications" if topic.endswith("/installationNotifications") else "other")
        self.message_counts[category] += 1
        if category == "responses":
            pending = self._pending.get(str(parsed.get("transactionId"))) if isinstance(parsed, dict) else None
            if pending:
                expected_name, future = pending
                operation = next((item for item in parsed.get("operations", [])
                                  if isinstance(item, dict) and item.get("name") == expected_name), None)
                if operation is not None and not future.done():
                    future.set_result(operation)
            summaries = [
                {"operation": item.get("name") if item.get("name") in ("GET_VALUES", "CLIENT_PING", "PARAMS_MODIFICATION") else "other",
                 "status": item.get("statusCode") if isinstance(item.get("statusCode"), (int, float)) else None,
                 "targets": len(item.get("targets", [])) if isinstance(item.get("targets"), list) else 0,
                 "target_details": [{"known_component": str(target.get("component")) in {spec.component for spec in self.specs},
                                     "status": target.get("statusCode") if isinstance(target.get("statusCode"), (int, float)) else None,
                                     "parameter_count": len(target.get("parameters") or {})}
                                    for target in (item.get("targets") or []) if isinstance(target, dict)][:3]}
                for item in ((parsed.get("operations") or []) if isinstance(parsed, dict) else [])
                if isinstance(item, dict)
            ][:10]
            self.response_statuses = (self.response_statuses + summaries)[-10:]
        allowed = {spec.key for spec in self.specs}
        if self.control_profile:
            allowed.update((self.control_profile.component, key) for key in READ_KEYS)
            for (component, key), bounds in parameter_bounds(parsed).items():
                if component == self.control_profile.component and key in TEMPERATURE_KEYS:
                    self.bounds[key] = bounds
        updates = {key: value for key, value in parameter_updates(parsed).items() if key in allowed}
        if updates:
            self.values.update(updates)
            now = time.monotonic()
            self.seen.update({key: now for key in updates})
            self._values_changed.set()
            self.first_values.set()
            self._notify()

    async def _connection(self):
        credentials = await self.credentials()
        self._client_id = f"{self._identity_id}-{time.time_ns() // 1000000}"
        url = websocket_url(IOT_ENDPOINT, credentials, REGION)
        try:
            async with asyncio.timeout(20):
                self._ws = await self.session.ws_connect(url, protocols=("mqtt",), max_msg_size=1048576,
                                                        headers={"Origin": "https://econetcloud.eu"})
        except Exception:
            raise CloudError("Unable to open cloud data stream") from None
        await self._send(mqtt_packet(0x10, mqtt_string("MQTT") + bytes((4, 2, 0, 60)) + mqtt_string(self._client_id)))
        buffer = bytearray()
        subscribed = False
        last_request = last_ping = started = time.monotonic()
        while not self._stopping and time.monotonic() - started < 2400:
            try:
                message = await self._ws.receive(timeout=15)
            except asyncio.TimeoutError:
                message = None
            if message is not None:
                if isinstance(message.data, (bytes, bytearray)):
                    buffer.extend(message.data)
                    for kind, flags, payload in mqtt_packets(buffer):
                        if kind == 2:
                            if payload != b"\x00\x00":
                                raise CloudError("MQTT connection rejected")
                            topics = (f"{self.installation_id}/installationNotifications",
                                      f"{self.installation_id}/{self._client_id}/installationResponse")
                            await self._send(mqtt_packet(0x82, b"\x00\x01" + b"".join(mqtt_string(t) + b"\x01" for t in topics)))
                        elif kind == 9:
                            if len(payload) < 4 or payload[:2] != b"\x00\x01" or any(code >= 128 for code in payload[2:]):
                                raise CloudError("MQTT subscription rejected")
                            if not subscribed:
                                subscribed = self.connected = True
                                self.last_error = None
                                self._ready.set()
                                await self.operation("CLIENT_PING")
                                await self.request_values()
                                last_request = time.monotonic()
                                self._notify()
                        elif kind == 3:
                            await self._published(flags, payload)
                        elif kind == 14:
                            raise CloudError("Cloud disconnected the stream")
                elif message.type in (8, 256, 257, 258):
                    raise CloudError("Cloud data stream closed")
            now = time.monotonic()
            if not subscribed and now - started > 20:
                raise CloudError("MQTT handshake timed out")
            if subscribed and now - last_ping >= 25:
                await self._send(b"\xc0\x00")
                await self.operation("CLIENT_PING")
                last_ping = now
                self._notify()
            if subscribed and now - last_request >= 60:
                await self.request_values()
                last_request = now

    async def run(self, on_update):
        self._on_update = on_update
        backoff = 2
        while not self._stopping:
            try:
                await self._connection()
                backoff = 2
            except AuthError:
                raise
            except asyncio.CancelledError:
                raise
            except CloudError as error:
                self.last_error = str(error)
            except Exception as error:
                # Never log exceptions containing signed URLs or tokens.
                self.last_error = type(error).__name__
            finally:
                self.connected = False
                for _, future in self._pending.values():
                    if not future.done():
                        future.set_exception(CloudError("Połączenie przerwane. Sprawdź stan centrali przed ponowieniem."))
                self._pending.clear()
                self._ready.clear()
                if self._ws is not None:
                    await self._ws.close()
                    self._ws = None
                self._notify()
            if not self._stopping:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def close(self):
        self._stopping = True
        if self._ws is not None:
            await self._ws.close()
