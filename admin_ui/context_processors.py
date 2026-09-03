from admin_ui.roles import can_administer, can_edit, role_of


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
