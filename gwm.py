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
import signal
import subprocess

ENV_TASK_WORKDIRS: str = "GWM_TASK_WORKDIRS"  # "task_name:/path/to/dir,another_task_name:/path/to/other/dir,..."

ENV_OUT_TASK_NAME: str = "GWM_TASK_NAME"  # Added to the environment of spawned subprocesses

TASK_NAME_DEFAULT: str = "default"
TASK_WORKDIRS_DEFAULT: Dict[str, str] = {"opt": "/opt", "tmp": "/tmp"}
MASTER_FACTOR_DEFAULT: float = 0.6
MASTER_FACTOR_MIN: float = 0.1
MASTER_FACTOR_MAX: float = 0.9
MASTER_FACTOR_ADJUST_AMOUNT: float = 0.05
N_WORKSPACES: int = 4

CMD_DMENU: str = "dmenu"
CMD_LAUNCHER: str = "dmenu_run"
CMD_TERMINAL: str = "st"
CMD_TR: str = "tr"
CMD_XARGS: str = "xargs"
CMD_XSETROOT: str = "xsetroot"

CMDS: Tuple[str, ...] = (CMD_DMENU, CMD_TERMINAL, CMD_LAUNCHER, CMD_TR, CMD_XARGS, CMD_XSETROOT)

KEY_MODMASK = Xlib.X.Mod4Mask

KEY_MASTER_FACTOR_DEC: Tuple[int, int] = (Xlib.XK.XK_Left, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_MASTER_FACTOR_INC: Tuple[int, int] = (Xlib.XK.XK_Right, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_MOVE_WINDOW_TO_WORKSPACE_0: Tuple[int, int] = (Xlib.XK.XK_1, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_MOVE_WINDOW_TO_WORKSPACE_1: Tuple[int, int] = (Xlib.XK.XK_2, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_MOVE_WINDOW_TO_WORKSPACE_2: Tuple[int, int] = (Xlib.XK.XK_3, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_MOVE_WINDOW_TO_WORKSPACE_3: Tuple[int, int] = (Xlib.XK.XK_4, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_PROMOTE_WINDOW: Tuple[int, int] = (Xlib.XK.XK_Tab, KEY_MODMASK)
KEY_QUIT: Tuple[int, int] = (Xlib.XK.XK_F12, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_SWITCH_TO_WORKSPACE_0: Tuple[int, int] = (Xlib.XK.XK_1, KEY_MODMASK)
KEY_SWITCH_TO_WORKSPACE_1: Tuple[int, int] = (Xlib.XK.XK_2, KEY_MODMASK)
KEY_SWITCH_TO_WORKSPACE_2: Tuple[int, int] = (Xlib.XK.XK_3, KEY_MODMASK)
KEY_SWITCH_TO_WORKSPACE_3: Tuple[int, int] = (Xlib.XK.XK_4, KEY_MODMASK)
KEY_SPAWN_LAUNCHER: Tuple[int, int] = (Xlib.XK.XK_d, KEY_MODMASK)
KEY_SPAWN_TASK_SWITCHER: Tuple[int, int] = (Xlib.XK.XK_space, KEY_MODMASK)
KEY_SPAWN_TERMINAL: Tuple[int, int] = (Xlib.XK.XK_Return, KEY_MODMASK)
KEY_WINDOW_FOCUS_DEC: Tuple[int, int] = (Xlib.XK.XK_Right, KEY_MODMASK)
KEY_WINDOW_FOCUS_INC: Tuple[int, int] = (Xlib.XK.XK_Left, KEY_MODMASK)


class Key:
    def __init__(self, display: Xlib.display.Display, key: Tuple[int, int], callback: Callable[[], None]) -> None:
        self._display: Xlib.display.display = display
        self._keysym: int = key[0]
        self._mod_mask: int = key[1]
        self._callback: Callable[[], None] = callback
        self._keycode = self._display.keysym_to_keycode(self._keysym)
        self._display.screen().root.grab_key(self._keycode, self._mod_mask, 1, Xlib.X.GrabModeAsync, Xlib.X.GrabModeAsync)

    def on_event(self, event: Xlib.protocol.rq.Event) -> None:
        if event.detail == self._keycode and event.state == self._mod_mask:
            self._callback()


class Workspace:
    def __init__(self, display: Xlib.display.Display) -> None:
        self._display: Xlib.display.display = display
        self._root_window: Xlib.protocol.rq.Window = self._display.screen().root
        self._is_current_workspace: bool = False
        self._windows: List[Xlib.protocol.rq.Window] = []
        self._master_factor: float = MASTER_FACTOR_DEFAULT
        self._i_focused_window: int = 0

        self._keys: Tuple[Key, ...] = (
            Key(self._display, KEY_MASTER_FACTOR_DEC, lambda: self._adjust_master_factor(-MASTER_FACTOR_ADJUST_AMOUNT)),
            Key(self._display, KEY_MASTER_FACTOR_INC, lambda: self._adjust_master_factor(MASTER_FACTOR_ADJUST_AMOUNT)),
            Key(self._display, KEY_PROMOTE_WINDOW, lambda: self._promote_focused_window()),
            Key(self._display, KEY_WINDOW_FOCUS_DEC, lambda: self._focus_window_by_offset(-1)),
            Key(self._display, KEY_WINDOW_FOCUS_INC, lambda: self._focus_window_by_offset(1)),
        )

    def on_event(self, event: Xlib.protocol.rq.Event) -> None:
        if event.type == Xlib.X.DestroyNotify:
            self.remove_window(event.window)
        elif self._is_current_workspace:
            if event.type == Xlib.X.MapRequest:
                self.add_window(event.window)
            elif event.type == Xlib.X.KeyPress:
                for key in self._keys:
                    key.on_event(event)

    def show(self) -> None:
        self._is_current_workspace = True
        for window in self._windows:
            self._show_window(window)
        self._focus_window(self.get_focused_window())

    def hide(self) -> None:
        self._focus_window(None)
        for window in self._windows:
            self._hide_window(window)
        self._is_current_workspace = False

    def add_window(self, window: Xlib.protocol.rq.Window) -> None:
        if window in self._windows or not self._is_window_valid(window):
            return
        self._windows.append(window)
        self._tile_windows()
        self._show_window(window)
        self._focus_window(window)

    def remove_window(self, window: Xlib.protocol.rq.Window) -> None:
        focused_window: Xlib.protocol.rq.Window = self.get_focused_window()
        if window in self._windows:
            self._hide_window(window)
            self._windows.remove(window)
            self._tile_windows()
        if window == focused_window:
            self._focus_window(self._get_master_window())
        else:
            self._focus_window(focused_window)

    def get_focused_window(self) -> Xlib.protocol.rq.Window:
        try:
            return self._windows[self._i_focused_window]
        except IndexError:
            return None

    def get_window_count(self) -> int:
        return len(self._windows)

    def _focus_window(self, window: Xlib.protocol.rq.Window) -> None:
        if window in self._windows and self._is_window_valid(window):
            self._i_focused_window = self._windows.index(window)
        if self._is_current_workspace:
            if window in self._windows and self._is_window_valid(window):
                window.set_input_focus(Xlib.X.RevertToParent, 0)
            else:
                self._root_window.set_input_focus(Xlib.X.RevertToParent, 0)

    def _focus_window_by_offset(self, offset: int) -> None:
        if self.get_window_count() > 0:
            self._focus_window(self._windows[(self._i_focused_window + offset) % self.get_window_count()])
        else:
            self._focus_window(None)

    def _show_window(self, window: Xlib.protocol.rq.Window) -> None:
        if self._is_current_workspace and window in self._windows and self._is_window_valid(window):
            window.map()

    def _hide_window(self, window: Xlib.protocol.rq.Window) -> None:
        if self._is_current_workspace and window in self._windows and self._is_window_valid(window):
            window.unmap()

    def _promote_focused_window(self) -> None:
        focused_window: Xlib.protocol.rq.Window = self.get_focused_window()
        master_window: Xlib.protocol.rq.Window = self._get_master_window()
        if focused_window is not None:
            if focused_window is not master_window:
                self.remove_window(focused_window)
                self.add_window(focused_window)
            else:
                stack_windows: List[Xlib.protocol.rq.Window] = self._get_stack_windows()
                try:
                    self.remove_window(stack_windows[0])
                    self.add_window(stack_windows[0])
                except IndexError:
                    pass

    def _tile_windows(self) -> None:
        i_screen: int = 0  # TODO: Multi-monitor support
        screen_x: int = self._display.xinerama_query_screens()._data["screens"][i_screen]["x"]
        screen_y: int = self._display.xinerama_query_screens()._data["screens"][i_screen]["y"]
        screen_width: int = self._display.xinerama_query_screens()._data["screens"][i_screen]["width"]
        screen_height: int = self._display.xinerama_query_screens()._data["screens"][i_screen]["height"]

        master_window: Xlib.protocol.rq.Window = self._get_master_window()
        if master_window is not None:
            stack_windows: List[Xlib.protocol.rq.Window] = self._get_stack_windows()
            if len(stack_windows) == 0:
                master_window.configure(x=screen_x, y=screen_y, width=screen_width, height=screen_height)
            else:
                master_window_width: int = int(screen_width * self._master_factor)
                stack_window_width: int = screen_width - master_window_width
                stack_window_height: int = screen_height // len(stack_windows)
                master_window.configure(x=screen_x, y=screen_y, width=master_window_width, height=screen_height)
                for i, window in enumerate(reversed(stack_windows)):
                    window.configure(
                        x=screen_x + master_window_width,
                        y=screen_y + i * stack_window_height,
                        width=stack_window_width,
                        height=stack_window_height,
                    )

    def _adjust_master_factor(self, amount: float) -> None:
        self._master_factor = max(min(self._master_factor + amount, MASTER_FACTOR_MAX), MASTER_FACTOR_MIN)
        self._tile_windows()

    def _get_master_window(self) -> Xlib.protocol.rq.Window:
        try:
            return self._windows[-1]
        except IndexError:
            return None

    def _get_stack_windows(self) -> List[Xlib.protocol.rq.Window]:
        return self._windows[:-1]

    def _is_window_valid(self, window: Xlib.protocol.rq.Window) -> bool:
        return window in self._root_window.query_tree().children


class Task:
    def __init__(self, display: Xlib.display.Display) -> None:
        self._display: Xlib.display.display = display
        self._is_current_task: bool = False
        self._workspaces: List[Workspace] = [Workspace(display) for i in range(N_WORKSPACES)]
        self._i_workspace_current: int = 0

        self.keys: Tuple[Key, ...] = (
            Key(self._display, KEY_MOVE_WINDOW_TO_WORKSPACE_0, lambda: self._move_window_to_workspace(0)),
            Key(self._display, KEY_MOVE_WINDOW_TO_WORKSPACE_1, lambda: self._move_window_to_workspace(1)),
            Key(self._display, KEY_MOVE_WINDOW_TO_WORKSPACE_2, lambda: self._move_window_to_workspace(2)),
            Key(self._display, KEY_MOVE_WINDOW_TO_WORKSPACE_3, lambda: self._move_window_to_workspace(3)),
            Key(self._display, KEY_SWITCH_TO_WORKSPACE_0, lambda: self._switch_workspace(0)),
            Key(self._display, KEY_SWITCH_TO_WORKSPACE_1, lambda: self._switch_workspace(1)),
            Key(self._display, KEY_SWITCH_TO_WORKSPACE_2, lambda: self._switch_workspace(2)),
            Key(self._display, KEY_SWITCH_TO_WORKSPACE_3, lambda: self._switch_workspace(3)),
        )

    def on_event(self, event: Xlib.protocol.rq.Event) -> None:
        for workspace in self._workspaces:
            workspace.on_event(event)

        if self._is_current_task:
            if event.type == Xlib.X.KeyPress:
                for key in self.keys:
                    key.on_event(event)

    def show(self) -> None:
        self._is_current_task = True
        self._workspaces[self._i_workspace_current].show()

    def hide(self) -> None:
        self._is_current_task = False
        self._workspaces[self._i_workspace_current].hide()

    def get_window_count(self) -> int:
        return sum(workspace.get_window_count() for workspace in self._workspaces)

    def _switch_workspace(self, i_workspace: int) -> None:
        if i_workspace == self._i_workspace_current:
            return
        self._workspaces[self._i_workspace_current].hide()
        self._i_workspace_current = i_workspace
        self._workspaces[self._i_workspace_current].show()

    def _move_window_to_workspace(self, i_workspace: int) -> None:
        if i_workspace == self._i_workspace_current:
            return
        window: Xlib.protocol.rq.Window = self._workspaces[self._i_workspace_current].get_focused_window()
        self._workspaces[self._i_workspace_current].remove_window(window)
        self._workspaces[i_workspace].add_window(window)


class WindowManager:
    def __init__(self, display: Xlib.display.Display) -> None:
        self._display: Xlib.display.Display = display
        self._root_window: Xlib.protocol.rq.Window = self._display.screen().root

        self._root_window.change_attributes(
            event_mask=Xlib.X.PropertyChangeMask | Xlib.X.SubstructureNotifyMask | Xlib.X.SubstructureRedirectMask
        )

        self._is_running = True
        self._tasks: Dict[str, Task] = {}
        self._task_current: str = TASK_NAME_DEFAULT
        self._tasks[self._task_current] = Task(display)
        self._tasks[self._task_current].show()

        self._keys: Tuple[Key, ...] = (
            Key(self._display, KEY_QUIT, lambda: self._quit()),
            Key(self._display, KEY_SPAWN_LAUNCHER, lambda: self._spawn_subprocess(CMD_LAUNCHER)),
            Key(self._display, KEY_SPAWN_TASK_SWITCHER, lambda: self._spawn_task_switcher()),
            Key(self._display, KEY_SPAWN_TERMINAL, lambda: self._spawn_subprocess(CMD_TERMINAL)),
        )

        self._task_workdirs = TASK_WORKDIRS_DEFAULT
        if ENV_TASK_WORKDIRS in os.environ:
            try:
                self._task_workdirs = dict(
                    s.split(":") for s in "".join(os.environ[ENV_TASK_WORKDIRS].split()).strip(",").split(",")
                )
            except:
                print("Error: Failed to parse %s: '%s'" % (ENV_TASK_WORKDIRS, os.environ[ENV_TASK_WORKDIRS]))

    def on_event(self, event: Xlib.protocol.rq.Event) -> None:
        for task in self._tasks.values():
            task.on_event(event)

        if event.type == Xlib.X.PropertyNotify and event.window == self._root_window:
            self._switch_task(self._root_window.get_wm_name())
        elif event.type == Xlib.X.KeyPress:
            for key in self._keys:
                key.on_event(event)

    def is_running(self) -> bool:
        return self._is_running

    def _switch_task(self, task_name: str) -> None:
        if not task_name or task_name == self._task_current:
            return
        self._tasks[self._task_current].hide()
        if self._tasks[self._task_current].get_window_count() == 0:
            self._tasks.pop(self._task_current)
        self._task_current = task_name
        self._tasks[self._task_current] = self._tasks.pop(self._task_current, Task(self._display))
        self._tasks[self._task_current].show()

    def _spawn_subprocess(self, command: str) -> None:
        env: Dict[str, str] = dict(os.environ)
        env.update({ENV_OUT_TASK_NAME: self._task_current})
        cwd = self._task_workdirs.get(self._task_current, None)
        if cwd is not None and os.path.isdir(cwd):
            subprocess.Popen((shutil.which(command),), cwd=cwd, env=env)
        else:
            subprocess.Popen((shutil.which(command),), env=env)

    def _spawn_task_switcher(self) -> None:
        p1: subprocess.Popen = subprocess.Popen(
            (shutil.which(CMD_DMENU),), stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        p2: subprocess.Popen = subprocess.Popen(
            (shutil.which(CMD_TR), "\\n", "\\0"), stdin=p1.stdout, stdout=subprocess.PIPE
        )
        p3: subprocess.Popen = subprocess.Popen(
            (shutil.which(CMD_XARGS), "-0", "-r", shutil.which(CMD_XSETROOT), "-name"), stdin=p2.stdout
        )
        p1.stdin.write(("\n".join(reversed(self._tasks.keys()))).encode())
        p1.stdin.close()
        p1.stdout.close()
        p2.stdout.close()

    def _quit(self) -> None:
        self._is_running = False


def main() -> None:
    for cmd in CMDS:
        assert shutil.which(cmd) is not None, "'%s' not found in PATH." % cmd
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    display: Xlib.display.Display = Xlib.display.Display()
    window_manager: WindowManager = WindowManager(display)
    while window_manager.is_running():
        window_manager.on_event(display.next_event())
    display.close()


if __name__ == "__main__":
    main()
