"""Keeps an eval run from changing data. Checked before a call reaches the server.

Until write cases land (they need `evalkit login` and the eval programs), every run is
read-only: any tool that changes data is blocked, whatever the token could do. A blocked
call is answered to Claude as a refusal and reported as a CRITICAL finding.
"""


def why_blocked(session, tool):
    """Why evalkit will not send this call, or None if it may go ahead."""
    if session.is_write(tool):
        return f"{tool} changes data, and evalkit runs are read-only for now; nothing was sent"
    return None
