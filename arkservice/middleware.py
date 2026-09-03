"""Response headers that Django does not set for us."""

from __future__ import annotations

from django.conf import settings

#: Everything this service needs comes from its own origin: htmx is vendored
#: into static/, there is no CDN, and no page embeds anything external.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'"
)

#: The resolver redirects to targets all over the web; sending the full ARK URL
#: as a referrer tells every one of them what was looked up.
DEFAULT_REFERRER_POLICY = "strict-origin-when-cross-origin"

DEFAULT_PERMISSIONS_POLICY = "geolocation=(), microphone=(), camera=(), interest-cohort=()"


class SecurityHeadersMiddleware:
    """Adds CSP, Referrer-Policy and Permissions-Policy to every response."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = getattr(settings, "CONTENT_SECURITY_POLICY", DEFAULT_CSP)
        self.referrer = getattr(settings, "REFERRER_POLICY", DEFAULT_REFERRER_POLICY)
        self.permissions = getattr(settings, "PERMISSIONS_POLICY", DEFAULT_PERMISSIONS_POLICY)

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.csp)
        response.setdefault("Referrer-Policy", self.referrer)
        response.setdefault("Permissions-Policy", self.permissions)
        return response
