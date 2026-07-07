from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ethernity.app.app_types import PathSelectionCallback
from ethernity.app.input_parsers import parse_setting_value
from ethernity.app.path_utils import save_picker_parts
from ethernity.app.screens.edit_field import EditFieldScreen

if TYPE_CHECKING:
    from ethernity.app.application import EthernityApp


class SettingsController:
    """Owns settings editing, parsing, and auto-save behavior."""

    def __init__(self, app: EthernityApp) -> None:
        self._app = app

    async def edit_selected(self) -> None:
        key = self.selected_key()
        if key is None:
            self._app.notify("Choose a setting first.", severity="warning")
            return
        await self.edit(key)

    def clear_selected(self) -> None:
        key = self.selected_key()
        if key is None:
            self._app.notify("Choose a setting first.", severity="warning")
            return
        descriptor = self._app.settings_state.descriptor(key)
        if descriptor is None:
            self._app.notify("That setting is read-only.", severity="warning")
            return
        self._app.settings_state.clear_setting(key)
        self.save_after_change()

    def selected_key(self) -> str | None:
        focused = self._app.screen.focused
        if focused is None or focused.id is None:
            return None
        if focused.id.startswith("setting-control-"):
            return focused.id.removeprefix("setting-control-")
        return None

    async def edit(self, key: str) -> None:
        descriptor = self._app.settings_state.descriptor(key)
        if descriptor is None:
            self._app.notify("That setting is read-only.", severity="warning")
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
                allow_files=False,
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
                allow_files=False,
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
        setting_value = None if value == "__none__" else str(value)
        self._app.settings_state.set_setting_value(key, setting_value)
        self.save_after_change()

    def apply_switch(self, key: str, value: bool) -> None:
        self._app.settings_state.set_setting_value(key, value)
        self.save_after_change()

    def apply_text(self, key: str, value: str | None) -> None:
        if value is None:
            return
        descriptor = self._app.settings_state.descriptor(key)
        if descriptor is None:
            return
        try:
            parsed = parse_setting_value(
                value,
                kind=descriptor.kind,
                options=self._app.settings_state.options.get(descriptor.option_key or "", ()),
                default=descriptor.default,
            )
        except ValueError as exc:
            self._app.notify(str(exc), severity="error")
            return
        self._app.settings_state.set_setting_value(key, parsed)
        self.save_after_change()

    def save_after_change(self) -> None:
        validation = self._app.settings_state.validate_task()
        if not validation.ready:
            self._app._last_execution_result = None
            self._app.refresh_task_view()
            return
        try:
            self._app._last_execution_result = self._app.settings_state.execute()
        except Exception as exc:
            self._app._last_execution_result = None
            self._app.notify(str(exc), severity="error")
        self._app.refresh_task_view()

    def _path_callback(self, key: str) -> PathSelectionCallback:
        def apply_path(paths: tuple[Path, ...] | None) -> None:
            self._apply_path(key, paths)

        return apply_path

    def _apply_path(self, key: str, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self._app.settings_state.set_setting_value(key, str(paths[0]) if paths else None)
            self.save_after_change()
