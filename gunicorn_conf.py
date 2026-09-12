"""Gunicorn config — quiet noisy demo UI / healthcheck access logs."""

import os

from gunicorn.glogging import Logger

bind = f"0.0.0.0:{os.environ.get('PORT', '8065')}"
workers = 1
threads = 8
timeout = 120
accesslog = "-"
errorlog = "-"
capture_output = True


def _should_skip_access_log(environ) -> bool:
    path = environ.get("PATH_INFO", "") or ""
    if path.startswith("/api/debug") or path.startswith("/api/settings"):
        return True
    # Browser UI polls / button clicks
    if environ.get("HTTP_X_TRAFFICLIGHT_UI") == "1":
        return True
    # Container healthchecks hitting status
    ua = (environ.get("HTTP_USER_AGENT") or "").lower()
    remote = environ.get("REMOTE_ADDR") or ""
    if path.startswith("/api/traffic-light") and "curl/" in ua and remote in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        return True
    return False


class QuietLogger(Logger):
    """Filter out UI/debug/healthcheck noise from access logs."""

    def access(self, resp, req, environ, request_time):
        if _should_skip_access_log(environ):
            return
        return super().access(resp, req, environ, request_time)


logger_class = QuietLogger
