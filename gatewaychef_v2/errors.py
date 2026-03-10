class GatewayChefV2Error(Exception):
    def __init__(
        self,
        message,
        *,
        code="v2_error",
        status_code=400,
        details=None,
        stage=None,
        retryable=False,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        self.stage = stage
        self.retryable = retryable


class StateTransitionError(GatewayChefV2Error):
    def __init__(self, message, **kwargs):
        super().__init__(message, code="invalid_state_transition", status_code=409, **kwargs)


class ExternalServiceError(GatewayChefV2Error):
    def __init__(self, service, message, **kwargs):
        details = dict(kwargs.pop("details", {}) or {})
        details["service"] = service
        super().__init__(
            message,
            code=kwargs.pop("code", "external_service_error"),
            status_code=kwargs.pop("status_code", 502),
            details=details,
            stage=kwargs.pop("stage", None),
            retryable=kwargs.pop("retryable", True),
        )
