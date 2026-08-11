from __future__ import annotations

from collections.abc import Mapping


ACCESS_RESTRICTED_MESSAGE = (
    "This website requires browser security verification, so I couldn't read its "
    "content automatically. You can upload a document, retry once, or continue manually."
)


class AccessRestrictedError(Exception):
    """Raised when a remote site returns a browser-verification challenge."""

    code = "access_restricted"

    def __init__(self, message: str = ACCESS_RESTRICTED_MESSAGE) -> None:
        super().__init__(message)


def raise_for_access_restriction(
    *,
    status_code: int,
    headers: Mapping[str, str],
    body: bytes,
) -> None:
    """Classify structural challenge signals without attempting to bypass them."""

    normalized_headers = {str(key).lower(): str(value).lower() for key, value in headers.items()}
    sample = body[:200_000].lower()
    has_challenge_header = normalized_headers.get("cf-mitigated") == "challenge"
    has_cloudflare_ray = "cf-ray" in normalized_headers
    challenge_markers = (
        b"/cdn-cgi/challenge-platform/",
        b"cf-chl-",
        b"cf_clearance",
        b"challenge-form",
    )
    has_challenge_markup = any(marker in sample for marker in challenge_markers)

    if has_challenge_header or has_challenge_markup or (
        status_code in {403, 503} and has_cloudflare_ray
    ):
        raise AccessRestrictedError()
