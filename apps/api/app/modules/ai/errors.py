"""Provider-level failures, mapped to user-facing error codes by the generation service.

Providers raise these (and only these) so the rest of the code never sees vendor exceptions.
Messages are safe to show to users; technical detail goes to `detail` and the server log.
"""


class AIProviderError(Exception):
    code = "AI_UNAVAILABLE"
    user_message = "AI generation is temporarily unavailable. Please try again in a moment."

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class AIUnavailableError(AIProviderError):
    """Connection failure, 5xx, rate limit or authentication/configuration problem."""


class AITimeoutError(AIProviderError):
    code = "AI_TIMEOUT"
    user_message = "The AI service did not answer in time. Please try again."


class AIConfigurationError(AIProviderError):
    """The configured provider cannot be used (missing key/model, SDK not installed)."""

    code = "AI_NOT_CONFIGURED"
    user_message = "AI generation is not configured on this server."
