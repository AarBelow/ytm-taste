import time
from dataclasses import dataclass


@dataclass
class FlowState:
    device_code: str
    verification_url_complete: str
    interval: int
    expires_at: float


@dataclass
class FlowResult:
    status: str
    token: dict | None = None
    message: str | None = None


def start_flow(credentials) -> FlowState:
    code = credentials.get_code()
    verification_url_complete = f"{code['verification_url']}?user_code={code['user_code']}"
    return FlowState(
        device_code=code["device_code"],
        verification_url_complete=verification_url_complete,
        interval=code["interval"],
        expires_at=time.monotonic() + code["expires_in"],
    )


def check_flow(credentials, device_code: str) -> FlowResult:
    result = credentials.token_from_code(device_code)
    if "access_token" in result:
        return FlowResult(status="done", token=result)

    error = result.get("error")
    if error in ("authorization_pending", "slow_down"):
        return FlowResult(status="pending")
    if error == "expired_token":
        return FlowResult(status="expired", message="The login code expired. Please try again.")
    if error == "access_denied":
        return FlowResult(status="denied", message="Login was denied.")
    return FlowResult(status="error", message=f"Unexpected response from Google: {result}")
