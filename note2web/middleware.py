class DisableClientCacheForAuthUsersMiddleware:
    """
    For any response served to a logged-in user, tell the browser
    not to cache it (so the back button can't show a stale dashboard).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"

        return response
