"""Remove URL credentials from persisted settings and diagnostic metadata."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def redact_url(value):
    if not isinstance(value, str) or not value.lower().startswith(('http://', 'https://')):
        return value
    try:
        parts = urlsplit(value)
        sensitive = ('key', 'token', 'secret', 'password', 'credential', 'auth', 'signature')
        query = [(name, '[redacted]' if any(term in name.lower() for term in sensitive) else content)
                 for name, content in parse_qsl(parts.query, keep_blank_values=True)]
        return urlunsplit((parts.scheme, parts.netloc.rsplit('@', 1)[-1], parts.path, urlencode(query), ''))
    except ValueError:
        return '[invalid URL]'


def redact_settings(value):
    """Copy settings while removing credentials at every nesting level."""
    if isinstance(value, dict):
        sensitive = ('api_key', 'apikey', 'secret', 'token', 'password', 'credential',
                     'authorization', 'cookie')
        return {str(key): redact_settings(nested) for key, nested in value.items()
                if str(key).lower() in ('max_tokens', 'max_output_tokens')
                or not any(part in str(key).lower() for part in sensitive)}
    if isinstance(value, (list, tuple)):
        return [redact_settings(item) for item in value]
    return redact_url(value)
