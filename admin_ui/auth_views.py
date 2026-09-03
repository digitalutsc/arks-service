"""Sign-in, with a limit on how often it may be guessed at."""

from __future__ import annotations

import logging

from django.contrib.auth import views as auth_views
from django.shortcuts import render

from admin_ui.throttle import clear, client_address, is_locked_out, record_failure

logger = logging.getLogger(__name__)


class ThrottledLoginView(auth_views.LoginView):
    """
    Django's login view, refusing to keep answering guesses.

    Failures are counted per username and client address; past the limit the
    form stops being processed at all, so a correct password guessed later in
    the same window is still refused.
    """

    template_name = "admin_ui/login.html"

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "")
        if is_locked_out(request, username):
            logger.warning(
                "login locked out for %r from %s", username[:64], client_address(request)
            )
            return render(request, "admin_ui/locked_out.html", status=429)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        clear(self.request, form.get_user().get_username())
        return super().form_valid(form)

    def form_invalid(self, form):
        username = self.request.POST.get("username", "")
        total = record_failure(self.request, username)
        logger.warning(
            "failed login for %r from %s (%s failures)",
            username[:64],
            client_address(self.request),
            total,
        )
        return super().form_invalid(form)
