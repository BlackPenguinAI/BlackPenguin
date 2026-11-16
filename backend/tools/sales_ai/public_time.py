"""Parse public visit wording in scripted buyers; no private offer access."""
import re
from datetime import datetime,timezone
from zoneinfo import ZoneInfo


def public_selection_time(message,project_timezone):
    """Read the public clock/zone, using the buyer's known project timezone only.

    New friendly labels and prior IANA labels are supported; a different city
    is not silently assumed to have the project's offset.
    """
    match=re.search(r'(\d{4}-\d{2}-\d{2} at \d{2}:\d{2} [AP]M) \(([^)]+)\)',message)
    if not match:return None
    zone=match[2].split(',')[0]
    friendly=project_timezone.rsplit('/',1)[-1].replace('_',' ')+' local time'
    if zone==friendly:zone=project_timezone
    try:return datetime.strptime(match[1],'%Y-%m-%d at %I:%M %p').replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError,KeyError):return None
