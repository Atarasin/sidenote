"""模型调用错误归一化（计划 T1.1.1）：任何服务商的失败都归到这几类。"""

from __future__ import annotations


class ModelError(Exception):
    """归一化基类。kind ∈ timeout / auth / rate_limit / network / bad_request / provider / mock."""

    def __init__(self, kind: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code

    @property
    def retryable(self) -> bool:
        return self.kind in ("timeout", "rate_limit", "network", "provider_5xx")


class ModelTimeoutError(ModelError):
    def __init__(self, message: str = "模型调用超时") -> None:
        super().__init__("timeout", message)


class ModelAuthError(ModelError):
    def __init__(self, message: str = "模型服务鉴权失败") -> None:
        super().__init__("auth", message, status_code=401)


class ModelRateLimitError(ModelError):
    def __init__(self, message: str = "模型服务限流") -> None:
        super().__init__("rate_limit", message, status_code=429)


class ModelNetworkError(ModelError):
    def __init__(self, message: str = "模型服务网络不可达") -> None:
        super().__init__("network", message)


class ModelBadRequestError(ModelError):
    def __init__(self, message: str) -> None:
        super().__init__("bad_request", message, status_code=400)


def from_http_status(status: int, body: str) -> ModelError:
    """按 HTTP 状态归一化服务商错误。"""
    snippet = body[:200] if body else ""
    if status == 401 or status == 403:
        return ModelAuthError(f"鉴权失败（{status}）：{snippet}")
    if status == 429:
        return ModelRateLimitError(f"限流（429）：{snippet}")
    if status >= 500:
        return ModelError("provider_5xx", f"服务商错误（{status}）：{snippet}", status_code=status)
    return ModelBadRequestError(f"请求被拒（{status}）：{snippet}")
