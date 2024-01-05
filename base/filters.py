import re
import logging

class IgnoreUrls(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        for url in [r"^/apple-touch-icon.*\.png$", r"^/favicon\.ico$", r"^/robots\.txt$", r"^/apple-touch-icon-precomposed\.png$", r"^/admin/jsi18n/?$"]:
            if re.search(url, message):
                return False
        return True