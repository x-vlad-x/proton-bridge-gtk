"""Authenticated, certificate-pinned local RPC transport.

Only the bundled core is started. Account credentials never go through a shell,
and all I/O runs outside GTK's main loop.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time

import grpc
from google.protobuf import empty_pb2, wrappers_pb2
from . import bridge_pb2 as pb

# Read by this distribution's core patch (patches/0001-*.patch); unset means upstream behaviour.
SYNC_OLDEST_FIRST_ENV = "BRIDGE_GTK_SYNC_OLDEST_FIRST"


def core_environment(sync_oldest_first, base=None):
    # The GTK preference is authoritative; an inherited value is never passed through.
    env = dict(os.environ if base is None else base)
    env.pop(SYNC_OLDEST_FIRST_ENV, None)
    if sync_oldest_first:
        env[SYNC_OLDEST_FIRST_ENV] = "1"
    return env


def login_request(username, password, **kwargs):
    # Bridge's bytes field contains base64 text, not raw password bytes.
    return pb.LoginRequest(username=username,
                           password=base64.b64encode(password.encode("utf-8")), **kwargs)


class Backend:
    def __init__(self, root, dispatch, on_event, on_disconnect, sync_oldest_first=False):
        self.root = Path(root)
        self.sync_oldest_first = sync_oldest_first
        self.dispatch = dispatch
        self.on_event = on_event
        self.on_disconnect = on_disconnect
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bridge-rpc")
        self.channel = None
        self.process = None
        self.metadata = ()
        self.stopping = False
        self.stream = None
        self.methods = {}
        self.config_path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "protonmail/bridge-v3/grpcServerConfig.json"

    def submit(self, work, callback=None, error=None):
        def run():
            try:
                result = work()
            except Exception as exc:
                # Do not log RPC request contents or remote errors containing credentials.
                if not self.stopping and error:
                    self.dispatch(error, self.safe_error(exc))
            else:
                if not self.stopping and callback:
                    self.dispatch(callback, result)
        self.pool.submit(run)

    @staticmethod
    def safe_error(exc):
        if isinstance(exc, grpc.RpcError):
            return f"Bridge RPC: {exc.code().name}"
        if isinstance(exc, (OSError, TimeoutError, ValueError, RuntimeError)):
            return str(exc)
        return type(exc).__name__

    def start(self, ready, error):
        self.submit(self._start, ready, error)

    def _start(self):
        binary = self.root / "bin/bridge"
        if not binary.is_file():
            raise FileNotFoundError("Bridge core is missing. Run update-proton-bridge-gtk.sh --build-only.")
        previous = None
        try:
            previous = json.loads(self.config_path.read_text()).get("token")
        except (OSError, ValueError):
            pass
        logs = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "proton-bridge-gtk"
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (logs / "core.log").open("ab") as log:
            self.process = subprocess.Popen(
                [str(binary), "--grpc", "--no-window", "--parent-pid", str(os.getpid()),
                 "--launcher", str(self.root / "proton-bridge-gtk"), "--log-level", "warn"],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, umask=0o077,
                env=core_environment(self.sync_oldest_first))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not self.stopping:
            if self.process.poll() is not None:
                raise RuntimeError("Bridge core exited. See ~/.local/state/proton-bridge-gtk/core.log; check the keyring and that another Bridge is not running.")
            try:
                config = json.loads(self.config_path.read_text())
                if config.get("token") and config["token"] != previous:
                    self._connect(config)
                    break
            except (OSError, ValueError, grpc.FutureTimeoutError, grpc.RpcError):
                if self.channel:
                    self.channel.close()
            time.sleep(0.2)
        else:
            raise TimeoutError("Bridge did not start within 45 seconds. Check the keyring and core.log.")
        # Establish event subscription before letting the core load accounts.
        self.stream = self.channel.unary_stream(
            "/grpc.Bridge/RunEventStream", request_serializer=pb.EventStreamRequest.SerializeToString,
            response_deserializer=pb.StreamEvent.FromString)(
                pb.EventStreamRequest(ClientPlatform="linux"), metadata=self.metadata)
        threading.Thread(target=self._events, daemon=True, name="bridge-events").start()
        # Official signed Qt updates are incompatible with this distribution.
        self.call("SetIsAutomaticUpdateOn", wrappers_pb2.BoolValue(value=False))
        self.call("GuiReady")
        return self.snapshot()

    def _connect(self, config):
        if self.config_path.stat().st_uid != os.getuid():
            raise ValueError("Bridge configuration must be owned by the current user.")
        socket = config.get("fileSocketPath")
        if socket:
            if not Path(socket).is_absolute():
                raise ValueError("Bridge socket path must be absolute.")
            target = f"unix:{socket}"
        else:
            port = int(config["port"])
            if not 1 <= port <= 65535:
                raise ValueError("Invalid Bridge RPC port.")
            target = f"127.0.0.1:{port}"
        self.channel = grpc.secure_channel(
            target, grpc.ssl_channel_credentials(config["cert"].encode()),
            options=(("grpc.ssl_target_name_override", "127.0.0.1"),))
        self.methods.clear()
        grpc.channel_ready_future(self.channel).result(timeout=2)
        self.metadata = (("server-token", config["token"]),)
        # Verify the server can read our private challenge, as the Qt frontend does.
        token = secrets.token_hex(32)
        with tempfile.NamedTemporaryFile(mode="w", prefix="bridge-gtk-", dir=self.config_path.parent) as challenge:
            json.dump({"token": token}, challenge)
            challenge.flush()
            answer = self.call("CheckTokens", wrappers_pb2.StringValue(value=challenge.name)).value
            if not secrets.compare_digest(answer, token):
                raise ValueError("Bridge token verification failed.")

    def call(self, name, request=None):
        method = pb.DESCRIPTOR.services_by_name["Bridge"].methods_by_name[name]
        if name not in self.methods:
            self.methods[name] = self.channel.unary_unary(
                f"/grpc.Bridge/{name}", request_serializer=lambda msg: msg.SerializeToString(),
                response_deserializer=method.output_type._concrete_class.FromString)
        return self.methods[name](request if request is not None else empty_pb2.Empty(),
                                  metadata=self.metadata, timeout=15)

    def snapshot(self):
        result = {"users": list(self.call("GetUserList").users),
                  "servers": self.call("MailServerSettings"),
                  "version": self.call("Version").value,
                  "hostname": self.call("Hostname").value}
        for method in ("IsAutostartOn", "IsAllMailVisible", "IsTelemetryDisabled", "IsDoHEnabled"):
            result[method] = self.call(method).value
        result["CurrentKeychain"] = self.call("CurrentKeychain").value
        return result

    def _events(self):
        try:
            for event in self.stream:
                if not self.stopping:
                    self.dispatch(self.on_event, event)
        except grpc.RpcError as exc:
            if not self.stopping:
                self.dispatch(self.on_disconnect, self.safe_error(exc))
        else:
            if not self.stopping:
                self.dispatch(self.on_disconnect, "Bridge event stream ended.")

    def close(self):
        self.stopping = True
        # Gracefully stop the stream before closing its channel: cancelling it alone
        # tells upstream to quit. The owned core gets SIGTERM to flush its vault.
        if self.channel:
            try:
                self.call("StopEventStream")
            except Exception:
                pass
            self.channel.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.pool.shutdown(wait=False, cancel_futures=True)
