"""Explicit offline preview for screenshots; never contacts Proton."""
from google.protobuf import empty_pb2
from . import bridge_pb2 as pb


class DemoBackend:
    def __init__(self, dispatch, on_event, empty=False):
        self.dispatch = dispatch
        self.on_event = on_event
        self.users = [] if empty else [pb.User(
            id="demo", username="Alex Morgan", avatarText="AM", state=pb.CONNECTED,
            usedBytes=2_400_000_000, totalBytes=15_000_000_000,
            password=b"demo-password-not-a-real-credential",
            addresses=["alex@proton.me", "alex.morgan@pm.me"])]
        self.servers = pb.ImapSmtpSettings(imapPort=1143, smtpPort=1025)
        self.values = {"IsAutostartOn": False, "IsAllMailVisible": True,
                       "IsTelemetryDisabled": True, "IsDoHEnabled": True}

    def start(self, ready, error):
        self.dispatch(ready, self.snapshot())

    def snapshot(self):
        return {"users": self.users, "servers": self.servers, "version": "3.27.1 · Demo",
                "hostname": "127.0.0.1", "CurrentKeychain": "secret-service", **self.values}

    def submit(self, work, callback=None, error=None):
        try:
            result = work()
            if callback:
                self.dispatch(callback, result)
        except Exception as exc:
            if error:
                self.dispatch(error, str(exc))

    def call(self, method, request=None):
        if method == "GetUserList":
            return pb.UserListResponse(users=self.users)
        if method == "SetMailServerSettings":
            self.servers = request
            self.dispatch(self.on_event, pb.StreamEvent(mailServerSettings=pb.MailServerSettingsEvent(
                changeMailServerSettingsFinished=pb.ChangeMailServerSettingsFinishedEvent())))
        elif method == "SetUserSplitMode":
            self.users[0].splitMode = request.active
            self.dispatch(self.on_event, pb.StreamEvent(user=pb.UserEvent(
                toggleSplitModeFinished=pb.ToggleSplitModeFinishedEvent(userID="demo"))))
        elif method.startswith("SetIs"):
            key = "Is" + method[5:]
            self.values[key] = request.value
        elif method in ("Login", "Login2FA", "Login2Passwords", "LoginFido"):
            self.dispatch(self.on_event, pb.StreamEvent(login=pb.LoginEvent(
                error=pb.LoginErrorEvent(type=pb.USERNAME_PASSWORD_ERROR))))
        return empty_pb2.Empty()

    def close(self):
        pass
