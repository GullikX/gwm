#!/usr/bin/env python3
#
# Copyright (C) 2022 Martin Gulliksson <martin@gullik.cc>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import Xlib
import Xlib.X
import Xlib.XK
import Xlib.display
import Xlib.protocol.rq
import enum
import os
from typing import Callable, Dict, List, Tuple
import shutil
import subprocess
import sys

ENV_TASK_WORKDIRS: str = "GWM_TASK_WORKDIRS"  # "task_name:/path/to/dir,another_task_name:/path/to/other/dir,..."

ENV_OUT_TASK_NAME: str = "GWM_TASK_NAME"  # Added to the environment of spawned subprocesses

TASK_NAME_DEFAULT: str = "default"
TASK_WORKDIRS_DEFAULT: Dict[str, str] = {"opt": "/opt", "tmp": "/tmp"}
MASTER_FACTOR_DEFAULT: float = 0.6
MASTER_FACTOR_MIN: float = 0.1
MASTER_FACTOR_MAX: float = 0.9
MASTER_FACTOR_ADJUSTMENT_AMOUNT: float = 0.05
N_WORKSPACES: int = 4

CMD_TERMINAL: Tuple[str, ...] = (shutil.which("st"),)
CMD_LAUNCHER: Tuple[str, ...] = (shutil.which("dmenu_run"),)

KEY_MODMASK = Xlib.X.Mod1Mask

KEY_MOVE_WINDOW_TO_WORKSPACE_0: Tuple[int, int] = (Xlib.XK.XK_1, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_MOVE_WINDOW_TO_WORKSPACE_1: Tuple[int, int] = (Xlib.XK.XK_2, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_MOVE_WINDOW_TO_WORKSPACE_2: Tuple[int, int] = (Xlib.XK.XK_3, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_MOVE_WINDOW_TO_WORKSPACE_3: Tuple[int, int] = (Xlib.XK.XK_4, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_PROMOTE_WINDOW: Tuple[int, int] = (Xlib.XK.XK_Tab, KEY_MODMASK)
KEY_SWITCH_TO_WORKSPACE_0: Tuple[int, int] = (Xlib.XK.XK_1, KEY_MODMASK)
KEY_SWITCH_TO_WORKSPACE_1: Tuple[int, int] = (Xlib.XK.XK_2, KEY_MODMASK)
KEY_SWITCH_TO_WORKSPACE_2: Tuple[int, int] = (Xlib.XK.XK_3, KEY_MODMASK)
KEY_SWITCH_TO_WORKSPACE_3: Tuple[int, int] = (Xlib.XK.XK_4, KEY_MODMASK)
KEY_SPAWN_LAUNCHER: Tuple[int, int] = (Xlib.XK.XK_Return, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_SPAWN_TERMINAL: Tuple[int, int] = (Xlib.XK.XK_Return, KEY_MODMASK)
KEY_QUIT: Tuple[int, int] = (Xlib.XK.XK_F1, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_WINDOW_FOCUS_DEC: Tuple[int, int] = (Xlib.XK.XK_Right, KEY_MODMASK)
KEY_WINDOW_FOCUS_INC: Tuple[int, int] = (Xlib.XK.XK_Left, KEY_MODMASK)


class Key:
    def __init__(self, display: Xlib.display.Display, key: Tuple[int, int], callback: Callable[[], None]) -> None:
        self.display: Xlib.display.display = display
        self.keysym: int = key[0]
        self.mod_mask: int = key[1]
        self.callback: Callable[[], None] = callback
        self.keycode = self.display.keysym_to_keycode(self.keysym)
        self.display.screen().root.grab_key(self.keycode, self.mod_mask, 1, Xlib.X.GrabModeAsync, Xlib.X.GrabModeAsync)

    def _on_event(self, event: Xlib.protocol.rq.Event) -> None:
        if event.detail == self.keycode and event.state == self.mod_mask:
            self.callback()


class Workspace:
    def __init__(self, display: Xlib.display.Display) -> None:
        self.display: Xlib.display.display = display
        self.is_current_workspace: bool = False
        self.windows: List[Xlib.protocol.rq.Window] = []
        self.master_factor: float = MASTER_FACTOR_DEFAULT
        self.i_focused_window: int = 0

        self.keys: Tuple[Key, ...] = (
            Key(self.display, KEY_PROMOTE_WINDOW, lambda: self.promote_focused_window()),
            Key(self.display, KEY_WINDOW_FOCUS_DEC, lambda: self.change_window_focus(-1)),
            Key(self.display, KEY_WINDOW_FOCUS_INC, lambda: self.change_window_focus(1)),
        )

    def show(self) -> None:
        self.is_current_workspace = True
        for window in self.windows:
            window.map()
        self.focus_window(self.get_focused_window())

    def hide(self) -> None:
        self.is_current_workspace = False
        for window in self.windows:
            window.unmap()

    def focus_window(self, window: Xlib.protocol.rq.Window) -> None:
        if self.is_current_workspace:
            if window is not None and window in self.windows:
                self.i_focused_window = self.windows.index(window)
                window.set_input_focus(Xlib.X.RevertToParent, 0)
            else:
                self.display.screen().root.set_input_focus(Xlib.X.RevertToParent, 0)

    def change_window_focus(self, offset: int) -> None:
        if self.get_window_count() == 0:
            return
        self.focus_window(self.windows[(self.i_focused_window + offset) % self.get_window_count()])

    def add_window(self, window: Xlib.protocol.rq.Window) -> None:
        self.windows.append(window)
        self.tile_windows()
        if self.is_current_workspace:
            self.show()
            self.focus_window(window)

    def remove_window(self, window: Xlib.protocol.rq.Window) -> None:
        focused_window: Xlib.protocol.rq.Window = self.get_focused_window()
        if window in self.windows:
            if self.is_window_alive(window):
                window.unmap()
            self.windows.remove(window)
            self.tile_windows()
        if self.is_current_workspace:
            if window.id == focused_window.id:
                self.focus_window(self.get_master_window())
            else:
                self.focus_window(focused_window)
            self.show()

    def promote_focused_window(self) -> None:
        focused_window: Xlib.protocol.rq.Window = self.get_focused_window()
        master_window: Xlib.protocol.rq.Window = self.get_master_window()
        if focused_window is not None:
            if focused_window is not master_window:
                self.remove_window(focused_window)
                self.add_window(focused_window)
            else:
                stack_windows: List[Xlib.protocol.rq.Window] = self.get_stack_windows()
                try:
                    self.remove_window(stack_windows[0])
                    self.add_window(stack_windows[0])
                except IndexError:
                    pass

    def get_master_window(self) -> Xlib.protocol.rq.Window:
        try:
            return self.windows[-1]
        except IndexError:
            return None

    def get_stack_windows(self) -> List[Xlib.protocol.rq.Window]:
        return list(reversed(self.windows[:-1]))

    def get_focused_window(self) -> Xlib.protocol.rq.Window:
        try:
            return self.windows[self.i_focused_window]
        except IndexError:
            return None

    def get_window_count(self) -> int:
        return len(self.windows)

    def tile_windows(self) -> None:
        self.windows = [window for window in self.windows if self.is_window_alive(window)]

        i_screen: int = 0  # TODO: Multi-monitor support
        screen_x: int = self.display.xinerama_query_screens()._data["screens"][i_screen]["x"]
        screen_y: int = self.display.xinerama_query_screens()._data["screens"][i_screen]["y"]
        screen_width: int = self.display.xinerama_query_screens()._data["screens"][i_screen]["width"]
        screen_height: int = self.display.xinerama_query_screens()._data["screens"][i_screen]["height"]

        master_window: Xlib.protocol.rq.Window = self.get_master_window()
        if master_window is not None:
            stack_windows: List[Xlib.protocol.rq.Window] = self.get_stack_windows()
            if len(stack_windows) == 0:
                master_window.configure(x=screen_x, y=screen_y, width=screen_width, height=screen_height)
            else:
                master_window_width: int = int(screen_width * self.master_factor)
                stack_window_width: int = screen_width - master_window_width
                stack_window_height: int = screen_height // len(stack_windows)
                master_window.configure(x=screen_x, y=screen_y, width=master_window_width, height=screen_height)
                for i, window in enumerate(stack_windows):
                    window.configure(
                        x=screen_x + master_window_width,
                        y=screen_y + i * stack_window_height,
                        width=stack_window_width,
                        height=stack_window_height,
                    )

    def adjust_master_factor(self, amount: float) -> None:
        self.master_factor = max(min(self.master_factor + amount, MASTER_FACTOR_MAX), MASTER_FACTOR_MIN)
        self.tile_windows()

    def is_window_alive(self, window: Xlib.protocol.rq.Window) -> bool:
        return window in self.display.screen().root.query_tree().children

    def _on_event(self, event: Xlib.protocol.rq.Event) -> None:
        if event.type == Xlib.X.MapRequest and self.is_current_workspace:
            self.add_window(event.window)
        elif event.type == Xlib.X.DestroyNotify:
            self.remove_window(event.window)
        elif event.type == Xlib.X.KeyPress and self.is_current_workspace:
            for key in self.keys:
                key._on_event(event)


class Task:
    def __init__(self, display: Xlib.display.Display) -> None:
        self.display: Xlib.display.display = display
        self.is_current_task: bool = False
        self.workspaces: List[Workspace] = [Workspace(display) for i in range(N_WORKSPACES)]
        self.i_workspace_current: int = 0

        self.keys: Tuple[Key, ...] = (
            Key(self.display, KEY_MOVE_WINDOW_TO_WORKSPACE_0, lambda: self.move_window_to_workspace(0)),
            Key(self.display, KEY_MOVE_WINDOW_TO_WORKSPACE_1, lambda: self.move_window_to_workspace(1)),
            Key(self.display, KEY_MOVE_WINDOW_TO_WORKSPACE_2, lambda: self.move_window_to_workspace(2)),
            Key(self.display, KEY_MOVE_WINDOW_TO_WORKSPACE_3, lambda: self.move_window_to_workspace(3)),
            Key(self.display, KEY_SWITCH_TO_WORKSPACE_0, lambda: self.switch_to_workspace(0)),
            Key(self.display, KEY_SWITCH_TO_WORKSPACE_1, lambda: self.switch_to_workspace(1)),
            Key(self.display, KEY_SWITCH_TO_WORKSPACE_2, lambda: self.switch_to_workspace(2)),
            Key(self.display, KEY_SWITCH_TO_WORKSPACE_3, lambda: self.switch_to_workspace(3)),
        )

    def show(self) -> None:
        self.is_current_task = True
        self.workspaces[self.i_workspace_current].show()

    def hide(self) -> None:
        self.is_current_task = False
        self.workspaces[self.i_workspace_current].hide()

    def switch_to_workspace(self, i_workspace: int) -> None:
        if i_workspace == self.i_workspace_current:
            return

        self.workspaces[self.i_workspace_current].hide()
        self.i_workspace_current = i_workspace
        self.workspaces[self.i_workspace_current].show()

    def move_window_to_workspace(self, i_workspace: int) -> None:
        if i_workspace == self.i_workspace_current:
            return

        window: Xlib.protocol.rq.Window = self.workspaces[self.i_workspace_current].get_focused_window()
        if window is not None:
            self.workspaces[self.i_workspace_current].remove_window(window)
            self.workspaces[i_workspace].add_window(window)

    def get_window_count(self) -> int:
        return sum(workspace.get_window_count() for workspace in self.workspaces)

    def _on_event(self, event: Xlib.protocol.rq.Event) -> None:
        for workspace in self.workspaces:
            workspace._on_event(event)

        if event.type == Xlib.X.KeyPress and self.is_current_task:
            for key in self.keys:
                key._on_event(event)


class WindowManager:
    def __init__(self, display: Xlib.display.Display) -> None:
        self.display: Xlib.display.Display = display

        self.display.screen().root.change_attributes(
            event_mask=Xlib.X.PropertyChangeMask | Xlib.X.SubstructureNotifyMask | Xlib.X.SubstructureRedirectMask
        )

        self.is_running = True
        self.tasks: Dict[str, Task] = {}
        self.task_current: str = TASK_NAME_DEFAULT
        self.tasks[self.task_current] = Task(display)
        self.tasks[self.task_current].show()

        self.keys: Tuple[Key, ...] = (
            Key(self.display, KEY_SPAWN_TERMINAL, lambda: self.spawn_subprocess(CMD_TERMINAL)),
            Key(self.display, KEY_SPAWN_LAUNCHER, lambda: self.spawn_subprocess(CMD_LAUNCHER)),
            Key(self.display, KEY_QUIT, lambda: self.quit()),
        )

        self.task_workdirs = TASK_WORKDIRS_DEFAULT
        if ENV_TASK_WORKDIRS in os.environ:
            try:
                self.task_workdirs = dict(
                    s.split(":") for s in os.environ[ENV_TASK_WORKDIRS].strip().strip(",").split(",")
                )
            except:
                print("Error: Failed to parse %s, using defaults." % ENV_TASK_WORKDIRS)

    def switch_to_task(self, task_name: str) -> None:
        if task_name == self.task_current:
            return

        self.tasks[self.task_current].hide()
        if self.tasks[self.task_current].get_window_count() == 0:
            self.tasks.pop(self.task_current)
        self.task_current = task_name
        self.tasks[self.task_current] = self.tasks.pop(self.task_current, Task(self.display))
        self.tasks[self.task_current].show()

    def spawn_subprocess(self, command: Tuple[str, ...]) -> None:
        cwd = self.task_workdirs.get(self.task_current, None)
        env: Dict[str, str] = dict(os.environ)
        env.update({ENV_OUT_TASK_NAME: self.task_current})
        subprocess.Popen(command, cwd=cwd, env=env)

    def quit(self) -> None:
        self.is_running = False

    def _on_event(self, event: Xlib.protocol.rq.Event) -> None:
        for task in self.tasks.values():
            task._on_event(event)

        if event.type == Xlib.X.KeyPress:
            for key in self.keys:
                key._on_event(event)


def main(argv: List[str]) -> int:
    display: Xlib.display.Display = Xlib.display.Display()

    window_manager: WindowManager = WindowManager(display)
    while window_manager.is_running:
        event: Xlib.protocol.rq.Event = display.next_event()
        # print(event)
        window_manager._on_event(event)

    display.close()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
