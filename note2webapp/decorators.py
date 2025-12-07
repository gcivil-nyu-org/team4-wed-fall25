from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def role_required(*allowed_roles):
    """
    Decorator that:
    - requires the user to be logged in
    - checks that user.profile.role is in allowed_roles
    - otherwise redirects them to the main dashboard
    """
    allowed_roles = set(allowed_roles)

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            profile = getattr(request.user, "profile", None)
            role = getattr(profile, "role", None)

            if role not in allowed_roles:
                messages.error(
                    request,
                    "You do not have permission to access that page.",
                )
                return redirect("dashboard")  # send them to their own dashboard

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator
