"""Shared CSS for guided workflow widgets."""

GUIDED_WORKFLOW_CSS = """
WorkflowStepStack {
    height: auto;
    width: 1fr;
}

WorkflowStep {
    height: auto;
    width: 1fr;
}

WorkflowStepHeader {
    height: 2;
    min-height: 2;
    width: 1fr;
    padding: 0 1;
    color: $text-muted;
}

WorkflowStepHeader.step-compact {
    height: 1;
    min-height: 1;
}

WorkflowStepHeader.step-compact .workflow-step-copy {
    height: 1;
}

.workflow-step-marker {
    width: 4;
    height: 1;
}

.workflow-step-number {
    width: 3;
    height: 1;
}

.workflow-step-copy {
    width: 1fr;
    height: 2;
}

.workflow-step-title,
.workflow-step-summary {
    width: 1fr;
    height: 1;
    text-wrap: nowrap;
    text-overflow: ellipsis;
}

.workflow-step-title {
    color: $text;
}

.workflow-step-status {
    width: auto;
    max-width: 19;
    height: 1;
    margin-left: 1;
    content-align: right middle;
    text-wrap: nowrap;
    text-overflow: ellipsis;
}

WorkflowStepHeader:focus {
    background: $surface-active;
    color: $text;
    text-style: bold;
}

WorkflowStepHeader.step-current {
    color: $text;
    text-style: bold;
}

WorkflowStepHeader.step-warning {
    color: $text-warning;
}

WorkflowStepHeader.step-error {
    color: $text-error;
}

.guided-step-body {
    height: auto;
    width: 1fr;
    padding: 1 2 1 4;
    background: $surface;
}

.guided-choice-set {
    height: auto;
    width: 1fr;
}

.guided-choice-empty {
    display: none;
}

.guided-actions,
.guided-field-row,
.guided-loading,
.guided-quorum-fields,
.guided-select-row,
.guided-selects {
    height: auto;
    width: 1fr;
}

.guided-loading LoadingIndicator {
    width: 4;
    height: 1;
    color: $text-primary;
}

.guided-loading-label {
    width: 1fr;
    height: 1;
    color: $text-muted;
}

.guided-actions Button {
    margin-right: 1;
}

.guided-summary,
.guided-empty,
.guided-detail {
    height: auto;
    width: 1fr;
    color: $text-muted;
}

.guided-field-value {
    height: 1;
    min-height: 1;
    width: 1fr;
    color: $text-muted;
    text-wrap: nowrap;
    text-overflow: ellipsis;
}

.guided-field-label {
    width: 16;
    margin-right: 1;
    color: $text;
}

.guided-select-label {
    width: 16;
    color: $text;
    content-align: left middle;
}

.guided-select-row Select {
    width: 1fr;
    max-width: 48;
}

CompositeStepBody {
    height: auto;
    width: 1fr;
}

CompositeStepBody > .guided-step-body {
    margin: 0 0 1 0;
    padding: 0;
    background: transparent;
}

.guided-path-list {
    height: auto;
    max-height: 6;
    width: 1fr;
}

InlineNotice {
    height: auto;
    width: 1fr;
    margin-top: 1;
    padding: 0 1;
}

InlineNotice.notice-info {
    color: $text-muted;
}

InlineNotice.notice-warning {
    color: $text-warning;
}

InlineNotice.notice-error {
    color: $text-error;
}

InlineNotice.notice-success {
    color: $text-success;
}

.guided-quorum-notice {
    margin-bottom: 1;
}

QuorumEditor Input {
    width: 10;
    margin-right: 2;
}

.guided-quorum-label {
    width: 12;
    content-align: left middle;
}

.guided-quorum-field {
    height: auto;
    width: 1fr;
}

Screen.-ethernity-narrow .guided-select-row {
    layout: vertical;
}

Screen.-ethernity-narrow .guided-select-label,
Screen.-ethernity-narrow .guided-select-row Select {
    width: 1fr;
    max-width: 100%;
}

Screen.-ethernity-narrow CompositeStepBody > .guided-step-body {
    padding: 0;
}
"""

__all__ = ["GUIDED_WORKFLOW_CSS"]
