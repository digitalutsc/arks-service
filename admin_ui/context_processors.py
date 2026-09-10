from urllib.parse import urlsplit

from django.conf import settings

from admin_ui.roles import can_administer, can_edit, role_of

#: Hostnames that mean "this is somebody's laptop or a container on it".
#: ``urlsplit().hostname`` lowercases and strips the brackets from an IPv6 host.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


def organisation(request):
    """Expose the organisation and the viewer's role to every template."""
    from core.models import Organisation

    user = getattr(request, "user", None)
    return {
        "organisation": Organisation.load(),
        "user_role": role_of(user),
        "can_edit": can_edit(user),
        "can_administer": can_administer(user),
    }


#: Which sidebar entry each view belongs under. Kept here rather than passed
#: from eleven render() calls, where it would drift the first time a view moved.
SECTIONS = {
    "collections": frozenset(
        {
            "collection_list",
            "collection_create",
            "collection_detail",
            "mint",
            "mint_template",
            "bulk_bind",
            "job_detail",
            "job_results",
        }
    ),
    "arks": frozenset({"ark_list", "ark_detail", "ark_purge", "export"}),
    "users": frozenset({"user_list"}),
}


def navigation(request):
    """The sidebar entry to mark as current, from the view being rendered."""
    match = getattr(request, "resolver_match", None)
    name = match.url_name if match else None
    current = next((key for key, names in SECTIONS.items() if name in names), "")
    return {"section": current}


def environment(request):
    """
    Where this instance's ARKs actually resolve, and whether that is production.

    ``ark_base_url`` always ends in a single ``/`` so a template can write
    ``{{ ark_base_url }}{{ ark.path }}`` and get a working link. It is derived
    from the request unless ``ARK_PUBLIC_BASE_URL`` overrides it — behind
    Apache the request already carries the public host and scheme.

    The label is shown in the sidebar so nobody copies a localhost URL into a
    catalogue record, or binds a production ARK thinking they are on a laptop.
    """
    configured = (settings.ARK_PUBLIC_BASE_URL or "").strip()
    base = configured.rstrip("/") + "/" if configured else request.build_absolute_uri("/")
    host = urlsplit(base).hostname or ""
    is_local = host in LOCAL_HOSTS
    return {
        "ark_base_url": base,
        "environment_label": "Local" if is_local else host,
        "environment_is_local": is_local,
    }
