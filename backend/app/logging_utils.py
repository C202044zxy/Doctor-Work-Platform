"""Keep WebSocket bearer query parameters out of server access/error logs."""

import logging
import re


class RedactWebSocketToken(logging.Filter):
    def filter(self, record):
        pattern = r"([?&]token=)[^\s\"&]+"
        if record.name == "uvicorn.access" and isinstance(record.args, tuple):
            # AccessFormatter unpacks five arguments to build its colored fields.
            # Keep that structure; the third argument is the full request path.
            record.args = tuple(
                re.sub(pattern, r"\1[redacted]", value) if isinstance(value, str) else value
                for value in record.args
            )
        else:
            record.msg = re.sub(pattern, r"\1[redacted]", record.getMessage())
            record.args = ()
        return True


def protect_socket_logs():
    for name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactWebSocketToken) for item in logger.filters):
            logger.addFilter(RedactWebSocketToken())
