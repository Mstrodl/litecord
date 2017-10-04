
class ImageError(Exception):
    pass


class ConfigError(Exception):
    pass


class VoiceError(Exception):
    pass


class PayloadLengthExceeded(Exception):
    """used by ws"""
    pass


class RequestCheckError(Exception):
    pass


class InvalidateSession(Exception):
    """used by ws"""
    pass


class InconsistencyError(Exception):
    """Raise on server cache inconsistencies
    for proper code function"""
    pass
