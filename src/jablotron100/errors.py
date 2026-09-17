"""Library exceptions."""


class JablotronError(Exception):
    """Base class for all library errors."""


class SerialPortNotDetected(JablotronError):
    """The Jablotron USB interface could not be found."""


class TransportClosed(JablotronError):
    """An operation was attempted on a closed transport."""


class ProtocolError(JablotronError):
    """A malformed packet or an invalid protocol value was supplied."""


class ConfigurationError(JablotronError):
    """A standalone or Home Assistant configuration is invalid."""
