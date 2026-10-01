"""Errors the data layer raises with a message written for the user.

S12 adds the error-code catalogue; until then the message itself is what the user sees.
"""


class WorkspaceError(RuntimeError):
    """The workspace cannot be opened as it is; the message says what the user can do about it."""
