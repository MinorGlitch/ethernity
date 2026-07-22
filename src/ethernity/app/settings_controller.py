from __future__ import annotations

from asyncio import Future
from collections.abc import Awaitable, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol, overload

from textual.app import AwaitMount, ScreenResultCallbackType
from textual.screen import Screen

from ethernity.app.app_types import ActiveTask, PathSelectionCallback
from ethernity.app.input_parsers import parse_setting_value
from ethernity.app.path_utils import save_picker_parts
from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerMode
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.settings import SettingsTaskState


class SettingsControllerApp(Protocol):
    """App surface used by settings editing."""

    settings_state: SettingsTaskState
    _last_execution_result: TaskExecutionResult | None

    @property
    def _running_task(self) -> ActiveTask | None: ...

    @property
    def screen(self) -> Screen[object]: ...

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: Literal["information", "warning", "error"] = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None: ...

    def refresh_task_view(self) -> None: ...

    def _rehydrate_workflow_defaults(self) -> None: ...

    @overload
    def push_screen(
        self,
        screen: Screen[bool],
        callback: ScreenResultCallbackType[bool] | None = None,
        wait_for_dismiss: Literal[False] = False,
        *,
        mode: str | None = None,
    ) -> AwaitMount: ...

    @overload
    def push_screen(
        self,
        screen: Screen[str | None] | str,
        callback: ScreenResultCallbackType[str | None] | None = None,
        wait_for_dismiss: Literal[False] = False,
        *,
        mode: str | None = None,
    ) -> AwaitMount: ...

    @overload
    def push_screen(
        self,
        screen: Screen[str | None] | str,
        callback: ScreenResultCallbackType[str | None] | None = None,
        wait_for_dismiss: Literal[True] = True,
        *,
        mode: str | None = None,
    ) -> Future[str | None]: ...

    def _pick_paths(
        self,
        *,
        title: str,
        prompt: str,
        selected_paths: Sequence[Path],
        callback: PathSelectionCallback,
        mode: FilePickerMode = FilePickerMode.OPEN_PATHS,
        multiple: bool = True,
        save_name: str = "",
        save_placeholder: str = "",
        choose_label: str = "Select",
    ) -> Awaitable[None]: ...


class SettingsController:
    """Owns settings editing, parsing, and auto-save behavior."""

    def __init__(self, app: SettingsControllerApp) -> None:
        self._app = app

    async def edit_selected(self) -> None:
        key = self.selected_key()
        if key is None:
            self._app.notify("Focus a setting first.", severity="warning")
            return
        await self.edit(key)

    def clear_selected(self) -> None:
        key = self.selected_key()
        if key is None:
            self._app.notify("Focus a setting first.", severity="warning")
            return
        if self._settings_write_locked():
            return
        descriptor = self._app.settings_state.descriptor(key)
        if descriptor is None:
            self._app.notify("This setting is read-only.", severity="warning")
            return
        self._app.settings_state.clear_setting(key)
        self.save_after_change()

    def reset_group(self, group: str) -> None:
        if self._settings_write_locked():
            return
        if not self._app.settings_state.reset_group(group):
            self._app.notify("Settings section not found.", severity="warning")
            return
        self.save_after_change()

    def reset_selected_group(self) -> None:
        key = self.selected_key()
        if key is None:
            self._app.notify("Focus a setting in the tab first.", severity="warning")
            return
        descriptor = self._app.settings_state.descriptor(key)
        if descriptor is None:
            self._app.notify("Settings section not found.", severity="warning")
            return
        self.reset_group(descriptor.group)

    def reset_all(self) -> None:
        if self._settings_write_locked():
            return
        self._app.settings_state.reset_all()
        self.save_after_change()

    async def request_reset_all(self) -> None:
        if self._settings_write_locked():
            return
        await self._app.push_screen(
            ConfirmActionScreen(
                title="Reset all settings?",
                message="All custom settings will return to their defaults and save immediately.",
                confirm_label="Reset all",
            ),
            self._reset_all_after_confirmation,
        )

    def _reset_all_after_confirmation(self, confirmed: bool | None) -> None:
        if confirmed is True:
            self.reset_all()

    def selected_key(self) -> str | None:
        focused = self._app.screen.focused
        current: Any = focused
        while current is not None:
            current_id = getattr(current, "id", None)
            if isinstance(current_id, str) and current_id.startswith("setting-control-"):
                return current_id.removeprefix("setting-control-")
            current = getattr(current, "parent", None)
        return None

    async def edit(self, key: str) -> None:
        if self._settings_write_locked():
            return
        descriptor = self._app.settings_state.descriptor(key)
        if descriptor is None:
            self._app.notify("This setting is read-only.", severity="warning")
            return
        if descriptor.kind == "bool":
            value = self._app.settings_state.setting_value(key)
            self._app.settings_state.set_setting_value(key, not bool(value))
            self.save_after_change()
            return
        if descriptor.kind == "path":
            selected = self._app.settings_state.path_value(key)
            await self._app._pick_paths(
                title=descriptor.title,
                prompt=descriptor.prompt,
                selected_paths=(selected,) if selected is not None else (),
                callback=self._path_callback(key),
                mode=FilePickerMode.OPEN_DIRECTORY,
                multiple=False,
            )
            return
        if descriptor.kind == "save_path":
            root, name = save_picker_parts(self._app.settings_state.path_value(key))
            await self._app._pick_paths(
                title=descriptor.title,
                prompt=descriptor.prompt,
                selected_paths=(root,),
                callback=self._path_callback(key),
                mode=FilePickerMode.SAVE_DIRECTORY,
                multiple=False,
                save_name=name,
                save_placeholder=descriptor.placeholder,
            )
            return

        text_options = self._app.settings_state.options.get(descriptor.option_key or "", ())
        prompt = descriptor.prompt
        if text_options:
            prompt = f"{prompt}: {', '.join(text_options)}"

        def apply_value(value: str | None, setting_key: str = key) -> None:
            self.apply_text(setting_key, value)

        await self._app.push_screen(
            EditFieldScreen(
                title=descriptor.title,
                prompt=prompt,
                value=self._app.settings_state.edit_value(key),
                placeholder=descriptor.placeholder,
            ),
            apply_value,
        )

    def apply_select(self, key: str, value: object) -> None:
        if self._settings_write_locked():
            return
        setting_value = None if value == "__none__" else str(value)
        self._app.settings_state.set_setting_value(key, setting_value)
        self.save_after_change()

    def apply_switch(self, key: str, value: bool) -> None:
        if self._settings_write_locked():
            return
        self._app.settings_state.set_setting_value(key, value)
        self.save_after_change()

    def apply_text(self, key: str, value: str | None) -> bool:
        if value is None:
            return False
        if self._settings_write_locked():
            return False
        descriptor = self._app.settings_state.descriptor(key)
        if descriptor is None:
            return False
        try:
            parsed = parse_setting_value(
                value,
                kind=descriptor.kind,
                options=self._app.settings_state.options.get(descriptor.option_key or "", ()),
                default=descriptor.default,
            )
        except ValueError as exc:
            self._app.settings_state.save_status = "Not saved"
            self._app._last_execution_result = None
            self._app.notify(f"{descriptor.title}: {exc}", severity="error")
            self._app.refresh_task_view()
            return False
        if parsed == self._app.settings_state.setting_value(key):
            if self._app.settings_state.save_pending:
                return self.save_after_change()
            self._app.refresh_task_view()
            return True
        self._app.settings_state.set_setting_value(key, parsed)
        return self.save_after_change()

    def save_after_change(self) -> bool:
        self._app.settings_state.save_pending = True
        if self._settings_write_locked(restore_saved_state=True):
            return False
        validation = self._app.settings_state.validate_task()
        if not validation.ready:
            self._app.settings_state.save_status = "Not saved"
            self._app._last_execution_result = None
            self._app.refresh_task_view()
            return False
        try:
            self._app.settings_state.save_status = "Saving..."
            result = self._app.settings_state.execute()
        except Exception as exc:
            self._app.settings_state.save_status = "Save failed"
            self._app._last_execution_result = None
            self._app.notify(str(exc), severity="error")
            self._app.refresh_task_view()
            return False

        self._app._last_execution_result = result
        if not result.ok:
            self._app.settings_state.save_status = "Save failed"
            self._app.notify(result.message, severity="error")
            self._app.refresh_task_view()
            return False

        self._app._rehydrate_workflow_defaults()
        self._app.settings_state.save_status = "Saved"
        self._app.settings_state.save_pending = False
        self._app.refresh_task_view()
        return True

    def retry_save(self) -> None:
        if not self._app.settings_state.save_pending:
            self._app.notify("Settings are saved.")
            return
        self.save_after_change()

    def _path_callback(self, key: str) -> PathSelectionCallback:
        def apply_path(paths: tuple[Path, ...] | None) -> None:
            self._apply_path(key, paths)

        return apply_path

    def _apply_path(self, key: str, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            if self._settings_write_locked():
                return
            self._app.settings_state.set_setting_value(key, str(paths[0]) if paths else None)
            self.save_after_change()

    def _settings_write_locked(self, *, restore_saved_state: bool = False) -> bool:
        if getattr(self._app, "_running_task", None) is None:
            return False

        if restore_saved_state:
            config_path = self._app.settings_state.config_path
            try:
                self._app.settings_state = SettingsTaskState.from_current(config_path)
            except (OSError, RuntimeError, ValueError):
                pass
        self._app.settings_state.save_status = "Locked while task runs"
        self._app._last_execution_result = None
        self._app.notify(
            "Finish the running task before changing settings.",
            severity="warning",
        )
        self._app.refresh_task_view()
        return True
