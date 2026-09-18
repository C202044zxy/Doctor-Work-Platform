"""Keep WebSocket bearer query parameters out of server access/error logs."""

import logging
import re


class RedactWebSocketToken(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r"([?&]token=)[^\s\"&]+", r"\1[redacted]", record.getMessage())
        record.args = ()
        return True


def protect_socket_logs():
    for name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactWebSocketToken) for item in logger.filters):
            logger.addFilter(RedactWebSocketToken())
