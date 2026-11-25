"""Allow embedding the Django UI inside the Chrome/Edge Side Panel extension and HF Spaces."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

FRAME_ANCESTORS_POLICY = (
    "frame-ancestors 'self' chrome-extension: edge-extension: https://*.hf.space https://huggingface.co"
)


class SidebarFrameMiddleware:
    """Set CSP frame-ancestors instead of X-Frame-Options: DENY so the sidebar extension works."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.headers.pop("X-Frame-Options", None)
        response["Content-Security-Policy"] = FRAME_ANCESTORS_POLICY
        return response
