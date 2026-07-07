from __future__ import annotations

from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.common import section_value
from ethernity.tasks.presentation.models import WorkspaceGroup


def doctor_groups(sections: tuple[TaskSection, ...]) -> tuple[WorkspaceGroup, ...]:
    return (
        WorkspaceGroup(
            key="checks",
            title="Setup checks",
            kind="checks",
            values=tuple(section_value(section) for section in sections),
            empty_label="No checks available",
        ),
    )
