from django.urls import include, path, re_path

from resolver import fallback
from resolver import views as resolver_views
from resolver.health import healthz

# Operator-supplied error pages when FALLBACK_PAGES_DIR is set; Django's
# defaults otherwise. A refused staff request keeps the staff shell.
handler403 = "resolver.fallback.permission_denied"
handler404 = "resolver.fallback.page_not_found"
handler500 = "resolver.fallback.server_error"

urlpatterns = [
    # Any /ark:... request. The view re-reads the raw URI so a trailing bare
    # '?' (an inflection, not a query string) is not lost.
    re_path(r"^ark:.*$", resolver_views.resolve, name="resolve"),
    path("healthz", healthz, name="healthz"),
    path("fallback/preview/<str:key>/", fallback.preview, name="fallback_preview"),
    path("fallback/<str:name>", fallback.asset, name="fallback_asset"),
    path("admin/", include("admin_ui.urls")),
    path("", resolver_views.landing, name="landing"),
]
