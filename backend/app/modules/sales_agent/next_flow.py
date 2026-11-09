"""The deployed workflow is current for every scope; permissions live downstream.

Historical environment flags and project lists no longer select a production engine.
The compatibility accessor remains for stored turns and existing integrations.
"""


def selected(scope):
    return True
