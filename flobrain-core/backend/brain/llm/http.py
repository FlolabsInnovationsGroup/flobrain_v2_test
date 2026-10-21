"""HTTP opener for customer keys (BYOK).

Redirects are not followed: a 3xx surfaces as an HTTPError. urllib would
otherwise follow a redirect to any host, possibly an internal one, and keep
sending the customer's Authorization header.
"""

import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def open_customer(request, timeout):
    return _OPENER.open(request, timeout=timeout)
