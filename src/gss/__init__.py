"""gamepass-save-syncer (gss): back up, restore and move Xbox Game Pass for PC saves."""

__version__ = "0.1.1"


class GssError(Exception):
    """A problem to report to the user as a plain message, without a traceback."""
