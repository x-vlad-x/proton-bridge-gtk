import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import grpc
from google.protobuf import wrappers_pb2
from proton_bridge_gtk import bridge_pb2 as pb
from proton_bridge_gtk import backend as backend_module
from proton_bridge_gtk.backend import SYNC_OLDEST_FIRST_ENV, Backend, core_environment, login_request


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(self.folder / "key.pem"), "-out", str(self.folder / "cert.pem"),
                        "-days", "1", "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.server = grpc.server(ThreadPoolExecutor(max_workers=2))
        def challenge(request, context):
            if dict(context.invocation_metadata()).get("server-token") != "test-token":
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "wrong token")
            return wrappers_pb2.StringValue(value=json.loads(Path(request.value).read_text())["token"])
        self.server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler("grpc.Bridge", {
            "CheckTokens": grpc.unary_unary_rpc_method_handler(challenge,
                request_deserializer=wrappers_pb2.StringValue.FromString,
                response_serializer=wrappers_pb2.StringValue.SerializeToString),
        }),))
        self.cert = (self.folder / "cert.pem").read_text()
        port = self.server.add_secure_port("127.0.0.1:0", grpc.ssl_server_credentials([
            ((self.folder / "key.pem").read_bytes(), self.cert.encode())]))
        self.server.start()
        self.config = {"cert": self.cert, "token": "test-token", "port": port}
        self.backend = Backend(self.folder, lambda fn, *args: fn(*args), lambda e: None, lambda m: None)
        self.backend.config_path = self.folder / "grpcServerConfig.json"
        self.backend.config_path.write_text(json.dumps(self.config))

    def tearDown(self):
        self.backend.close()
        self.server.stop(0).wait()
        self.tmp.cleanup()

    def test_pinned_tls_and_token_challenge(self):
        self.backend._connect(self.config)
        self.assertEqual(self.backend.metadata, (("server-token", "test-token"),))
        self.assertFalse(list(self.folder.glob("bridge-gtk-*")), "challenge file must be removed")

    def test_wrong_token_rejected(self):
        with self.assertRaises(grpc.RpcError) as raised:
            self.backend._connect({**self.config, "token": "wrong"})
        self.assertEqual(raised.exception.code(), grpc.StatusCode.UNAUTHENTICATED)

    def test_different_certificate_rejected(self):
        # Trusting no copy of the generated server certificate must fail.
        self.backend.channel = grpc.secure_channel(f'127.0.0.1:{self.config["port"]}', grpc.ssl_channel_credentials())
        with self.assertRaises(grpc.FutureTimeoutError):
            grpc.channel_ready_future(self.backend.channel).result(timeout=0.5)

    def test_unicode_password_encoding(self):
        password = "\u043f\u0430\u0440\u043e\u043b\u044c '$() & \U0001f4e8"
        request = login_request("alex@proton.me", password, useHvDetails=True)
        self.assertEqual(base64.b64decode(request.password).decode(), password)
        self.assertTrue(request.useHvDetails)
        self.assertTrue(request.HasField("useHvDetails"))

    def test_errors_do_not_expose_remote_details(self):
        class Error(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.INVALID_ARGUMENT
            def details(self):
                return "secret-password"
        self.assertNotIn("secret-password", self.backend.safe_error(Error()))


class CoreEnvironmentTests(unittest.TestCase):
    def test_oldest_first_is_explicit_and_never_inherited(self):
        base = {"PATH": "/usr/bin", SYNC_OLDEST_FIRST_ENV: "1"}
        self.assertEqual(core_environment(False, base), {"PATH": "/usr/bin"})
        self.assertEqual(core_environment(True, {"PATH": "/usr/bin"}), {"PATH": "/usr/bin", SYNC_OLDEST_FIRST_ENV: "1"})
        self.assertEqual(base[SYNC_OLDEST_FIRST_ENV], "1", "the caller's environment must not be modified")

    def test_core_is_started_with_the_selected_order(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "bin").mkdir()
                (root / "bin/bridge").write_text("")
                started = []

                class ExitedCore:
                    def __init__(self, args, **kwargs):
                        started.append((args, kwargs))

                    def poll(self):
                        return 1

                backend = Backend(root, lambda fn, *args: fn(*args), lambda e: None, lambda m: None, sync_oldest_first=enabled)
                backend.config_path = root / "grpcServerConfig.json"
                with patch.object(backend_module.subprocess, "Popen", ExitedCore), \
                        patch.dict(os.environ, {"XDG_STATE_HOME": str(root / "state"), SYNC_OLDEST_FIRST_ENV: "1"}):
                    with self.assertRaises(RuntimeError):
                        backend._start()
                backend.close()
                args, kwargs = started[0]
                self.assertEqual(args[0], str(root / "bin/bridge"))
                self.assertEqual(kwargs["env"].get(SYNC_OLDEST_FIRST_ENV), "1" if enabled else None)
                self.assertEqual(kwargs["env"]["XDG_STATE_HOME"], str(root / "state"))


if __name__ == "__main__":
    unittest.main()
