"""
Fallback pages: an operator-supplied landing page and error pages.

``FALLBACK_PAGES_DIR`` names a directory on the server holding ``index.html``,
``403.html``, ``404.html``, ``500.html`` (and ``503.html``, reserved) plus the
stylesheets and images they reference, served at ``/fallback/<name>``. The
files are written by whoever has shell access, never through the web, because
they are shown to the anonymous public on the resolver's own hostname and must
be available when the database is not (that is what a 500 page is for).

Pages are served as they are, with the real status code. The one exception is
``index.html``, which may carry three placeholders replaced by plain string
substitution: ``{{organisation_name}}``, ``{{organisation_website}}`` and
``{{naa_table}}``. Error pages get no substitution: a 500 page never reads the
database. With the setting empty, nothing here is used and Django's defaults
apply, exactly as before this module existed.

A signed-in staff request under /admin/ that is refused keeps the staff shell
(templates/admin_ui/403.html) rather than the public 403 page; the resolver has
no authentication, so staff are nearly the only people who ever see a 403.
"""

from __future__ import annotations

import logging
import mimetypes
import re
import threading
import time
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import render
from django.utils.html import escape, format_html, format_html_join
from django.views import defaults

from arkservice.middleware import DEFAULT_CSP

logger = logging.getLogger(__name__)

#: The pages the directory may hold, by the key the GUI and the preview use.
PAGES = {
    "index": "index.html",
    "403": "403.html",
    "404": "404.html",
    "500": "500.html",
    "503": "503.html",
}
#: Filenames never served as assets.
RESERVED = frozenset(PAGES.values())

#: What a page may reference beside itself. No HTML (a second page would bypass
#: the status codes) and nothing executable but a plain .js file, which only an
#: operator can put there.
ASSET_EXTENSIONS = frozenset(
    {".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".woff", ".woff2"}
)

#: Seconds a file's content is reused before its mtime is looked at again, so
#: a 404 storm does not read the disk per request and an edit shows within a minute.
CACHE_SECONDS = 60

#: The policy fallback responses carry: inline <style> allowed, nothing else relaxed.
FALLBACK_CSP = DEFAULT_CSP.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")

#: Placeholders index.html may use; anything else in the file is left alone.
PLACEHOLDER = re.compile(r"\{\{\s*(organisation_name|organisation_website|naa_table)\s*\}\}")

_cache: dict[str, tuple[float, float, bytes | None]] = {}
_cache_lock = threading.Lock()
_last_warning = 0.0


def directory() -> Path | None:
    """The configured directory, or None when the feature is off."""
    configured = (getattr(settings, "FALLBACK_PAGES_DIR", "") or "").strip()
    return Path(configured) if configured else None


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _warn(message: str, *args) -> None:
    """At most one warning a minute: a broken 404 page must not log per 404."""
    global _last_warning
    now = time.monotonic()
    if now - _last_warning >= 60:
        _last_warning = now
        logger.warning(message, *args)


def _read(filename: str) -> bytes | None:
    """The file's bytes, or None when the feature is off or the file is absent."""
    base = directory()
    if base is None:
        return None
    path = base / filename
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(filename)
    if cached is not None and now - cached[0] < CACHE_SECONDS:
        return cached[2]
    try:
        stat = path.stat()
    except OSError:
        with _cache_lock:
            _cache[filename] = (now, 0.0, None)
        return None
    if cached is not None and cached[1] == stat.st_mtime:
        with _cache_lock:
            _cache[filename] = (now, stat.st_mtime, cached[2])
        return cached[2]
    try:
        body = path.read_bytes()
    except OSError:
        _warn("fallback page %s exists but could not be read", path)
        body = None
    with _cache_lock:
        _cache[filename] = (now, stat.st_mtime, body)
    return body


def page(key: str) -> bytes | None:
    """The configured page for ``key`` ("index", "403", …), or None."""
    filename = PAGES.get(str(key))
    return _read(filename) if filename else None


def _landing_values() -> dict[str, str]:
    """The three placeholder values, HTML-escaped; empty if the database is down."""
    try:
        from core.models import Collection, Organisation

        organisation = Organisation.load()
        rows = (
            Collection.objects.exclude(naan="").order_by("name").values_list("naan", "naa", "name")
        )
    except Exception:  # noqa: BLE001 - the page must still render
        _warn("fallback landing page: database unavailable, placeholders left empty")
        return {"organisation_name": "", "organisation_website": "", "naa_table": ""}
    body = format_html_join(
        "\n",
        "<tr><td><code>{}</code></td><td>{}</td></tr>",
        ((naan, naa or name) for naan, naa, name in rows),
    )
    table = (
        format_html(
            '<table class="naa"><thead><tr><th>NAAN</th><th>Authority</th></tr></thead>'
            "<tbody>{}</tbody></table>",
            body,
        )
        if body
        else ""
    )
    return {
        "organisation_name": escape(organisation.name),
        "organisation_website": escape(organisation.website),
        "naa_table": str(table),
    }


def landing_page() -> bytes | None:
    """``index.html`` with its placeholders filled, or None when there is none."""
    raw = page("index")
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="replace")
    if PLACEHOLDER.search(text) is None:
        return raw
    values = _landing_values()
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], text).encode("utf-8")


def asset_path(name: str) -> Path | None:
    """
    The file behind ``/fallback/<name>``, or None.

    Only a bare filename with an allowed extension, directly inside the
    directory, that is a regular file and resolves to a path still inside the
    directory (so a symlink cannot point elsewhere). The page files themselves
    are not assets.
    """
    base = directory()
    if base is None or not name or name != Path(name).name or name in RESERVED:
        return None
    if Path(name).suffix.lower() not in ASSET_EXTENSIONS:
        return None
    path = base / name
    try:
        resolved = path.resolve(strict=True)
        if resolved.parent != base.resolve(strict=True) or not resolved.is_file():
            return None
    except OSError:
        return None
    return resolved


def active() -> list[dict]:
    """What the GUI card shows: each page, its file, and whether it is there."""
    base = directory()
    rows = []
    for key, filename in PAGES.items():
        present = base is not None and (base / filename).is_file()
        rows.append({"key": key, "file": filename, "present": present})
    return rows


# --- responses ---------------------------------------------------------------


def _html(body: bytes, status: int) -> HttpResponse:
    response = HttpResponse(body, status=status, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = FALLBACK_CSP
    return response


def landing_response() -> HttpResponse | None:
    """The configured landing page as a response, or None to use the built-in one."""
    body = landing_page()
    return _html(body, 200) if body is not None else None


def permission_denied(request, exception=None):
    """handler403: staff stay in the shell; everyone else gets 403.html or the default."""
    user = getattr(request, "user", None)
    if request.path.startswith("/admin/") and user is not None and user.is_authenticated:
        message = str(exception) if exception and str(exception) else ""
        return render(request, "admin_ui/403.html", {"message": message}, status=403)
    body = page("403")
    if body is not None:
        return _html(body, 403)
    return defaults.permission_denied(request, exception)


def csrf_failure(request, reason=""):
    """
    CSRF_FAILURE_VIEW: Django does not route a CSRF failure through handler403,
    and that failure is, in practice, the only public 403 there is.
    """
    body = page("403")
    if body is not None:
        return _html(body, 403)
    from django.views.csrf import csrf_failure as default_csrf_failure

    return default_csrf_failure(request, reason=reason)


def page_not_found(request, exception=None):
    """handler404: 404.html when configured, Django's default otherwise."""
    body = page("404")
    if body is not None:
        return _html(body, 404)
    return defaults.page_not_found(request, exception)


def server_error(request):
    """handler500: reads one file and nothing else, so it works with the database down."""
    body = page("500")
    if body is not None:
        return _html(body, 500)
    return defaults.server_error(request)


def asset(request, name: str):
    """``GET /fallback/<name>``: a stylesheet or image beside the pages."""
    path = asset_path(name)
    if path is None:
        raise Http404("No such fallback asset")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    response = FileResponse(path.open("rb"), content_type=content_type)
    response["Cache-Control"] = "public, max-age=3600"
    return response


def preview(request, key: str):
    """``GET /fallback/preview/<key>/``: the page with status 200, superusers only."""
    from django.core.exceptions import PermissionDenied

    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path())
    if not request.user.is_superuser:
        raise PermissionDenied("Previewing fallback pages needs a superuser.")
    if key not in PAGES:
        raise Http404("No such fallback page")
    body = landing_page() if key == "index" else page(key)
    if body is None:
        raise Http404(f"No {PAGES[key]} in the fallback directory")
    return _html(body, 200)
