class DeviceApiCorsMiddleware:
    """Allow the Focus Guard browser extension (chrome-extension:// origin) and
    the desktop Focus Agent to call /focus/api/ endpoints using a bearer token.

    Token-based auth does not rely on cookies, so a wildcard origin is safe and
    avoids the credentials/CORS restriction. Preflight OPTIONS requests are
    short-circuited with the required headers.
    """

    ALLOWED_METHODS = 'GET, POST, OPTIONS'
    ALLOWED_HEADERS = 'Authorization, Content-Type, X-Device-Token'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Short-circuit preflight before any view is reached.
        if request.method == 'OPTIONS' and request.path.startswith('/focus/api/'):
            from django.http import HttpResponse
            response = HttpResponse(status=204)
            response['Access-Control-Allow-Origin'] = request.META.get('HTTP_ORIGIN', '*')
            response['Access-Control-Allow-Methods'] = self.ALLOWED_METHODS
            response['Access-Control-Allow-Headers'] = self.ALLOWED_HEADERS
            response['Access-Control-Max-Age'] = '86400'
            return response

        if request.path.startswith('/focus/api/'):
            response = self.get_response(request)
            response['Access-Control-Allow-Origin'] = request.META.get('HTTP_ORIGIN', '*')
            response['Access-Control-Allow-Methods'] = self.ALLOWED_METHODS
            response['Access-Control-Allow-Headers'] = self.ALLOWED_HEADERS
            response['Access-Control-Max-Age'] = '86400'
            return response

        return self.get_response(request)