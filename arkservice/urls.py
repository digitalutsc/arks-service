from django.urls import path, re_path

from resolver import views as resolver_views

urlpatterns = [
    # Any /ark:... request. The view re-reads the raw URI so a trailing bare
    # '?' (an inflection, not a query string) is not lost.
    re_path(r"^ark:.*$", resolver_views.resolve, name="resolve"),
    path("", resolver_views.landing, name="landing"),
]
