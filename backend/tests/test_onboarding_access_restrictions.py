import pytest

from app.modules.onboarding_jobs.errors import (
    ACCESS_RESTRICTED_MESSAGE,
    AccessRestrictedError,
    raise_for_access_restriction,
)


@pytest.mark.parametrize(
    ("status_code", "headers", "body"),
    [
        (403, {"cf-ray": "abc-LIM"}, b"Forbidden"),
        (503, {"cf-mitigated": "challenge"}, b"Service unavailable"),
        (200, {}, b'<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/jsch/v1"></script>'),
        (200, {}, b'<input type="hidden" name="cf-chl-token" value="token">'),
        (403, {"server": "CloudFront", "x-cache": "Error from cloudfront"}, b"Request blocked"),
    ],
)
def test_browser_verification_is_classified_as_access_restricted(status_code, headers, body):
    with pytest.raises(AccessRestrictedError) as captured:
        raise_for_access_restriction(
            status_code=status_code,
            headers=headers,
            body=body,
        )

    assert captured.value.code == "access_restricted"
    assert str(captured.value) == ACCESS_RESTRICTED_MESSAGE


@pytest.mark.parametrize("status_code", [429, 500, 502, 504])
def test_ordinary_transient_responses_are_not_classified_as_browser_verification(status_code):
    raise_for_access_restriction(
        status_code=status_code,
        headers={},
        body=b"Temporary upstream failure",
    )


def test_cloudflare_ray_alone_does_not_classify_successful_content_as_a_challenge():
    raise_for_access_restriction(
        status_code=200,
        headers={"cf-ray": "abc-LIM"},
        body=b"<html><body>Highland Homes corporate content</body></html>",
    )
