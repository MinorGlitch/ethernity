"""Geometry checks shared by production screen captures."""

from textual.dom import DOMNode
from textual.widget import Widget


def assert_scrollbar_gaps(root: DOMNode) -> None:
    """Check visible tracks; inputs scroll text without painting a scrollbar."""
    for host in root.query(Widget):
        if (
            host.is_scrollable
            and host.show_vertical_scrollbar
            and host.display
            and all(parent.display for parent in host.ancestors)
        ):
            if not host.vertical_scrollbar.region.area:
                continue
            track = host.vertical_scrollbar.content_region
            assert track.width == 1, (host, host.region, host.vertical_scrollbar.region)
            assert track.x - host.scrollable_content_region.right == 2
