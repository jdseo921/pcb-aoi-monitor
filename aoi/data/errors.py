"""Errors the data layer raises; each carries a code from the catalogue in aoi/errors.py."""

from ..errors import AoiError


class WorkspaceError(AoiError):
    """The workspace cannot be opened as it is; the message says what the user can do about it."""
