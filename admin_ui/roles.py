"""
Roles.

Three levels, implemented as Django groups so they can also be managed from the
Django admin if anyone needs to:

    Admin   everything, including collections, purging and user management
    Editor  mint, bind, unbind, bulk bind, export
    Viewer  search and export only

A superuser counts as an Admin whatever groups they are in. A user in none of
the groups can do nothing — accounts are useless until someone gives them a
role, which is deliberate.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q

ADMIN = "Admin"
EDITOR = "Editor"
VIEWER = "Viewer"

#: Most privileged first.
ROLES = (ADMIN, EDITOR, VIEWER)

#: What each role implies, weakest to strongest.
_RANK = {VIEWER: 1, EDITOR: 2, ADMIN: 3}


def ensure_groups() -> None:
    """Create the three groups if they are not there yet."""
    for name in ROLES:
        Group.objects.get_or_create(name=name)


#: Attribute caching a user's role on the user object. ``request.user`` is
#: loaded once per request, so the cache lives exactly as long as the request;
#: every staff page asked four times (the view guard plus three context values).
_ROLE_CACHE = "_arkservice_role"


def role_of(user) -> str | None:
    """The user's role, or ``None`` if they have not been given one."""
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return ADMIN
    cached = getattr(user, _ROLE_CACHE, False)
    if cached is not False:
        return cached
    names = set(user.groups.values_list("name", flat=True))
    role = next((each for each in ROLES if each in names), None)  # most privileged wins
    setattr(user, _ROLE_CACHE, role)
    return role


def _forget_role(user) -> None:
    if hasattr(user, _ROLE_CACHE):
        delattr(user, _ROLE_CACHE)


def set_role(user, role: str) -> None:
    """Give ``user`` exactly one role, replacing any it already had."""
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role!r}")
    ensure_groups()
    # One transaction: a concurrent request must never see the user between
    # losing the old role and gaining the new one.
    with transaction.atomic():
        user.groups.remove(*Group.objects.filter(name__in=ROLES))
        user.groups.add(Group.objects.get(name=role))
    _forget_role(user)


def clear_role(user) -> None:
    """Take every role away, leaving an account that can sign in but do nothing."""
    with transaction.atomic():
        user.groups.remove(*Group.objects.filter(name__in=ROLES))
    _forget_role(user)


def is_last_administrator(user) -> bool:
    """
    True when demoting ``user`` would leave nobody able to administer.

    Superusers count, since they are Admins whatever their groups say.
    """
    from django.contrib.auth import get_user_model

    others = (
        get_user_model()
        .objects.filter(is_active=True)
        .exclude(pk=user.pk)
        .filter(Q(is_superuser=True) | Q(groups__name=ADMIN))
    )
    return not others.exists()


def has_role(user, minimum: str) -> bool:
    """True when the user's role is at least ``minimum``."""
    role = role_of(user)
    if role is None:
        return False
    return _RANK[role] >= _RANK[minimum]


def can_edit(user) -> bool:
    return has_role(user, EDITOR)


def can_administer(user) -> bool:
    return has_role(user, ADMIN)


def require_role(minimum: str):
    """
    Refuse the request unless the user's role is at least ``minimum``.

    Anonymous users fall through to Django's login redirect; a signed-in user
    without enough privilege gets a 403 rather than being bounced to a login
    page they have already passed.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if not has_role(request.user, minimum):
                raise PermissionDenied(
                    f"This needs the {minimum} role; yours is {role_of(request.user) or 'none'}."
                )
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
