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
import Xlib.xobject.colormap
import enum
import os
from typing import Callable, Dict, List, Optional, Tuple, Type, TypeVar
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
WINDOW_BORDER_WIDTH: int = 2
WINDOW_BORDER_COLOR_DEFAULT = "#222222"
WINDOW_BORDER_COLOR_FOCUSED = "#bbbbbb"

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
KEY_MOVE_WINDOW_TO_TASK: Tuple[int, int] = (Xlib.XK.XK_space, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_WINDOW_FOCUS_DEC: Tuple[int, int] = (Xlib.XK.XK_Right, KEY_MODMASK)
KEY_WINDOW_FOCUS_INC: Tuple[int, int] = (Xlib.XK.XK_Left, KEY_MODMASK)
KEY_SCREEN_FOCUS_DEC: Tuple[int, int] = (Xlib.XK.XK_Page_Down, KEY_MODMASK)
KEY_SCREEN_FOCUS_INC: Tuple[int, int] = (Xlib.XK.XK_Page_Up, KEY_MODMASK)
KEY_MOVE_WINDOW_TO_PREVIOUS_SCREEN: Tuple[int, int] = (Xlib.XK.XK_Page_Up, KEY_MODMASK | Xlib.X.ShiftMask)
KEY_MOVE_WINDOW_TO_NEXT_SCREEN: Tuple[int, int] = (Xlib.XK.XK_Page_Down, KEY_MODMASK | Xlib.X.ShiftMask)

INT16_MAX: int = (1 << 15) - 1
TASK_WINDOW_MOVE_MARKER = "TASK_WINDOW_MOVE_MARKER"

T = TypeVar("T", bound="Node")


class Key:
    def __init__(self, display: Xlib.display.Display, key: Tuple[int, int], callback: Callable[[], None]) -> None:
        self._display: Xlib.display.display = display
        self._keysym: int = key[0]
        self._mod_mask: int = key[1]
        self._callback: Callable[[], None] = callback
        self._keycode = self._display.keysym_to_keycode(self._keysym)
        self._display.screen().root.grab_key(
            self._keycode, self._mod_mask, 1, Xlib.X.GrabModeAsync, Xlib.X.GrabModeAsync
        )

    def on_event(self, event: Xlib.protocol.rq.Event) -> None:
        if event.detail == self._keycode and event.state == self._mod_mask:
            self._callback()


class Node:
    def __init__(self: T) -> None:
        self._children: List[T] = []
        self._parent: Optional["Node"] = None
        self._i_active_child: int = 0

    def append(self, child: T, set_active: bool = False) -> None:
        child._parent = self
        self._children.append(child)
        if set_active:
            self._i_active_child = len(self._children) - 1

    def remove(self: T) -> None:
        if self._parent is not None:
            active_child = self._parent._children[self._parent._i_active_child]
            self._parent._children.remove(self)
            if active_child == self:
                self._parent._i_active_child = len(self._parent._children) - 1
            else:
                self._parent._i_active_child = self._parent._children.index(active_child)

    def get_sibling_by_index(self: T, index: int) -> Optional[T]:
        if self._parent is None:
            return None
        else:
            try:
                return self._parent._children[index]
            except IndexError:
                return None

    def get_sibling_by_offset(self: T, offset: int) -> T:
        if self._parent is None:
            return self
        else:
            return self._parent._children[(self.get_index() + offset) % len(self._parent._children)]

    def activate(self, promote: bool = False) -> None:
        if self._parent is not None and promote:
            self.remove()
            self._parent.append(self)
        node: "Node" = self
        while node._parent is not None:
            node._parent._i_active_child = node.get_index()
            node = node._parent

    def search_active(self, cls: Type[T]) -> Optional[T]:
        if type(self) == cls:
            return self
        try:
            return self._children[self._i_active_child].search_active(cls)
        except IndexError as e:
            pass
        return None

    def search_all(self, cls: Type[T]) -> List[T]:
        matches: List[T] = []
        self._search_all_recursive(cls, matches)
        return matches

    def _search_all_recursive(self, cls: Type[T], matches: List[T]) -> None:
        if type(self) == cls:
            matches.append(self)
        for child in self._children:
            child._search_all_recursive(cls, matches)

    def get_index(self: T) -> int:
        if self._parent is None:
            return 0
        else:
            return self._parent._children.index(self)

    def is_highest_index(self) -> bool:
        if self._parent is None:
            return False
        else:
            return self.get_index() == len(self._parent._children) - 1

    def __str__(self) -> str:
        data: List[str] = []
        self._str_recursive(data, 0)
        return "\n".join(data)

    def _str_recursive(self, data: List[str], indent: int) -> None:
        data.append(indent * " " + self.__repr__())
        for child in self._children:
            child._str_recursive(data, indent + 1)


class Window(Node):
    def __init__(self, xlib_window: Xlib.protocol.rq.Window) -> None:
        super().__init__()
        self._xlib_window = xlib_window

    def get_xlib_window(self) -> Xlib.protocol.rq.Window:
        return self._xlib_window


class Workspace(Node):
    def __init__(self) -> None:
        super().__init__()
        self._master_factor: float = MASTER_FACTOR_DEFAULT

    def get_master_factor(self) -> float:
        return self._master_factor

    def adjust_master_factor(self, amount: float) -> None:
        self._master_factor = max(min(self._master_factor + amount, MASTER_FACTOR_MAX), MASTER_FACTOR_MIN)


class Screen(Node):
    def __init__(self) -> None:
        super().__init__()


class Task(Node):
    def __init__(self, name: str) -> None:
        super().__init__()
        self._name: str = name

    def get_name(self) -> str:
        return self._name


class Tree:
    def __init__(self, display: Xlib.display.Display) -> None:
        self._display: Xlib.display.Display = display
        self._keys: Tuple[Key, ...] = (
            Key(self._display, KEY_MASTER_FACTOR_DEC, lambda: self._adjust_master_factor(-MASTER_FACTOR_ADJUST_AMOUNT)),
            Key(self._display, KEY_MASTER_FACTOR_INC, lambda: self._adjust_master_factor(MASTER_FACTOR_ADJUST_AMOUNT)),
            Key(self._display, KEY_PROMOTE_WINDOW, lambda: self._promote_window()),
            Key(self._display, KEY_WINDOW_FOCUS_DEC, lambda: self._focus_window_by_offset(-1)),
            Key(self._display, KEY_WINDOW_FOCUS_INC, lambda: self._focus_window_by_offset(1)),
            Key(self._display, KEY_MOVE_WINDOW_TO_WORKSPACE_0, lambda: self._move_window_to_workspace(0)),
            Key(self._display, KEY_MOVE_WINDOW_TO_WORKSPACE_1, lambda: self._move_window_to_workspace(1)),
            Key(self._display, KEY_MOVE_WINDOW_TO_WORKSPACE_2, lambda: self._move_window_to_workspace(2)),
            Key(self._display, KEY_MOVE_WINDOW_TO_WORKSPACE_3, lambda: self._move_window_to_workspace(3)),
            Key(self._display, KEY_SWITCH_TO_WORKSPACE_0, lambda: self._switch_workspace(0)),
            Key(self._display, KEY_SWITCH_TO_WORKSPACE_1, lambda: self._switch_workspace(1)),
            Key(self._display, KEY_SWITCH_TO_WORKSPACE_2, lambda: self._switch_workspace(2)),
            Key(self._display, KEY_SWITCH_TO_WORKSPACE_3, lambda: self._switch_workspace(3)),
            Key(self._display, KEY_SCREEN_FOCUS_DEC, lambda: self._focus_screen_by_offset(-1)),
            Key(self._display, KEY_SCREEN_FOCUS_INC, lambda: self._focus_screen_by_offset(1)),
            Key(self._display, KEY_MOVE_WINDOW_TO_PREVIOUS_SCREEN, lambda: self._move_window_to_screen(-1)),
            Key(self._display, KEY_MOVE_WINDOW_TO_NEXT_SCREEN, lambda: self._move_window_to_screen(1)),
        )
        self._root_window: Xlib.protocol.rq.Window = self._display.screen().root
        self._colormap: Xlib.xobject.colormap.Colormap = self._display.screen().default_colormap
        self.root = Node()
        self._switch_task(TASK_NAME_DEFAULT)

    def on_event(self, event: Xlib.protocol.rq.Event) -> None:
        if event.type == Xlib.X.PropertyNotify:
            if event.window == self._root_window:
                name: Optional[str] = self._root_window.get_wm_name()
                if name:
                    if name.startswith(TASK_WINDOW_MOVE_MARKER):
                        self._move_window_to_task(name.lstrip(TASK_WINDOW_MOVE_MARKER))
                    else:
                        self._switch_task(name)
        elif event.type == Xlib.X.MapRequest:
            self._handle_window(event.window)
        elif event.type == Xlib.X.UnmapNotify:
            self._unhandle_window(event.window)
        elif event.type == Xlib.X.KeyPress:
            for key in self._keys:
                key.on_event(event)

    def get_active_task_name(self) -> str:
        task: Optional[Task] = self.root.search_active(Task)
        assert task is not None, "No active task?"
        return task.get_name()

    def get_all_task_names(self) -> List[str]:
        return [task.get_name() for task in self.root.search_all(Task)]

    def _create_task(self, name: str) -> Task:
        task = Task(name)
        for i_screen in range(self._get_screen_count()):
            screen: Screen = Screen()
            for i_workspace in range(N_WORKSPACES):
                screen.append(Workspace())
            task.append(screen)
        self.root.append(task)
        return task

    def _switch_task(self, name: str) -> None:
        task_previous: Optional[Task] = self.root.search_active(Task)
        if task_previous is None or name != task_previous.get_name():
            task_new: Optional[Task] = None
            try:
                tasks: List[Task] = self.root.search_all(Task)
                for task in tasks:
                    if task.get_name() == name:
                        task_new = task
            except IndexError:
                pass
            if task_new is None:
                task_new = self._create_task(name)
            if task_previous is not None and len(task_previous.search_all(Window)) == 0:
                task_previous.remove()
            task_new.activate(promote=True)
            self._update_window_positions()

    def _move_window_to_task(self, name: str) -> None:
        task_previous: Optional[Task] = self.root.search_active(Task)
        assert task_previous is not None, "No active task?"
        if task_previous.get_name() != name:
            window: Optional[Window] = self.root.search_active(Window)
            if window is not None:
                window.remove()
                task_new: Optional[Task] = None
                try:
                    tasks: List[Task] = self.root.search_all(Task)
                    for task in tasks:
                        if task.get_name() == name:
                            task_new = task
                except IndexError:
                    pass
                if task_new is None:
                    task_new = self._create_task(name)
                workspace_new: Optional[Workspace] = task_new.search_active(Workspace)
                assert workspace_new is not None, "Unable to find workspace?"
                workspace_new.append(window, set_active=True)
                task_previous.activate(promote=True)
                self._update_window_positions()

    def _move_window_to_screen(self, offset: int) -> None:
        screen_previous: Optional[Screen] = self.root.search_active(Screen)
        assert screen_previous is not None, "No active screen?"
        screen_new: Screen = screen_previous.get_sibling_by_offset(offset)
        if screen_new != screen_previous:
            window: Optional[Window] = self.root.search_active(Window)
            if window is not None:
                window.remove()
                workspace_new: Optional[Workspace] = screen_new.search_active(Workspace)
                assert workspace_new is not None, "Unable to find workspace?"
                workspace_new.append(window, set_active=True)
                self._update_window_positions()

    def _switch_workspace(self, i_workspace: int) -> None:
        workspace: Optional[Workspace] = self.root.search_active(Workspace)
        assert workspace is not None, "No active workspace?"
        if i_workspace != workspace.get_index():
            workspace_new: Optional[Workspace] = workspace.get_sibling_by_index(i_workspace)
            assert workspace_new is not None, "Unable to find workspace?"
            workspace_new.activate()
            self._update_window_positions()

    def _move_window_to_workspace(self, i_workspace: int) -> None:
        workspace: Optional[Workspace] = self.root.search_active(Workspace)
        assert workspace is not None, "No active workspace?"
        if i_workspace != workspace.get_index():
            window: Optional[Window] = self.root.search_active(Window)
            if window is not None:
                window.remove()
                workspace_new: Optional[Workspace] = workspace.get_sibling_by_index(i_workspace)
                assert workspace_new is not None, "Unable to find workspace?"
                workspace_new.append(window, set_active=True)
                self._update_window_positions()

    def _handle_window(self, xlib_window: Xlib.protocol.rq.Window) -> None:
        if not self._is_window_valid(xlib_window):
            return

        for window in self.root.search_all(Window):
            if window.get_xlib_window() == xlib_window:
                return  # Already exists

        workspace: Optional[Workspace] = self.root.search_active(Workspace)
        assert workspace is not None, "No active workspace?"
        window_new: Window = Window(xlib_window)
        workspace.append(window_new, set_active=True)
        window_new.activate()
        self._update_window_positions()

    def _unhandle_window(self, xlib_window: Xlib.protocol.rq.Window) -> None:
        for window in self.root.search_all(Window):
            if window.get_xlib_window() == xlib_window:
                window.remove()
                self._update_window_positions()

    def _focus_window_by_offset(self, offset: int) -> None:
        window: Optional[Window] = self.root.search_active(Window)
        if window is not None:
            window_new: Window = window.get_sibling_by_offset(offset)
            window_new.activate()
            self._update_window_focus()

    def _promote_window(self) -> None:
        window_focused: Optional[Window] = self.root.search_active(Window)
        if window_focused is not None:
            if not window_focused.is_highest_index():
                window_focused.activate(promote=True)
                self._update_window_positions()
            else:
                workspace: Optional[Workspace] = self.root.search_active(Workspace)
                assert workspace is not None, "No active workspace?"
                for window in reversed(workspace.search_all(Window)):
                    if window != window_focused:
                        window.activate(promote=True)
                        self._update_window_positions()
                        break

    def _update_window_positions(self) -> None:
        windows_all: List[Window] = self.root.search_all(Window)
        window_ids: List[int] = [window.get_xlib_window().id for window in windows_all]
        duplicates: List[int] = [i for i in window_ids if window_ids.count(i) > 1]
        assert len(duplicates) == 0, "Duplicate windows?"

        for window in windows_all:
            position_hidden: int = INT16_MAX
            window.get_xlib_window().configure(x=position_hidden, y=position_hidden)
            window.get_xlib_window().map()

        task: Optional[Task] = self.root.search_active(Task)
        assert task is not None, "No active task?"

        screens: List[Screen] = task.search_all(Screen)
        assert len(screens) > 0, "No screens found?"
        assert len(screens) <= self._get_screen_count(), "Windows on non-existent screen?"

        for i_screen, screen in enumerate(screens):
            workspace: Optional[Workspace] = screen.search_active(Workspace)
            assert workspace is not None, "No active workspace?"

            screen_x: int = self._get_screen_data(i_screen, "x")
            screen_y: int = self._get_screen_data(i_screen, "y")
            screen_width: int = self._get_screen_data(i_screen, "width")
            screen_height: int = self._get_screen_data(i_screen, "height")

            windows: List[Window] = workspace.search_all(Window)

            if len(windows) > 0:
                master_window: Window = windows[-1]
                stack_windows: List[Window] = windows[:-1]
                if len(stack_windows) == 0:
                    master_window.get_xlib_window().configure(
                        x=screen_x, y=screen_y, width=screen_width, height=screen_height, border_width=0
                    )
                else:
                    master_window_width: int
                    master_window_height: int
                    stack_window_width: int
                    stack_window_height: int
                    if screen_width > screen_height:
                        master_window_width = int(screen_width * workspace.get_master_factor())
                        master_window_height = screen_height
                        stack_window_width = screen_width - master_window_width
                        stack_window_height = screen_height // len(stack_windows)
                        master_window.get_xlib_window().configure(
                            x=screen_x,
                            y=screen_y,
                            width=master_window_width - 2 * WINDOW_BORDER_WIDTH,
                            height=master_window_height - 2 * WINDOW_BORDER_WIDTH,
                            border_width=WINDOW_BORDER_WIDTH,
                        )
                        for i, window in enumerate(reversed(stack_windows)):
                            window.get_xlib_window().configure(
                                x=screen_x + master_window_width,
                                y=screen_y + i * stack_window_height,
                                width=stack_window_width - 2 * WINDOW_BORDER_WIDTH,
                                height=stack_window_height - 2 * WINDOW_BORDER_WIDTH,
                                border_width=WINDOW_BORDER_WIDTH,
                            )
                    else:
                        master_window_width = screen_width
                        master_window_height = int(screen_height * workspace.get_master_factor())
                        stack_window_width = screen_width // len(stack_windows)
                        stack_window_height = screen_height - master_window_height
                        master_window.get_xlib_window().configure(
                            x=screen_x,
                            y=screen_y,
                            width=master_window_width - 2 * WINDOW_BORDER_WIDTH,
                            height=master_window_height - 2 * WINDOW_BORDER_WIDTH,
                            border_width=WINDOW_BORDER_WIDTH,
                        )
                        for i, window in enumerate(reversed(stack_windows)):
                            window.get_xlib_window().configure(
                                x=screen_x + i * stack_window_width,
                                y=screen_y + master_window_height,
                                width=stack_window_width - 2 * WINDOW_BORDER_WIDTH,
                                height=stack_window_height - 2 * WINDOW_BORDER_WIDTH,
                                border_width=WINDOW_BORDER_WIDTH,
                            )
        self._update_window_focus()

    def _update_window_focus(self) -> None:
        for window in self.root.search_all(Window):
            window.get_xlib_window().change_attributes(
                None, border_pixel=self._colormap.alloc_named_color(WINDOW_BORDER_COLOR_DEFAULT).pixel
            )
        focused_window: Optional[Window] = self.root.search_active(Window)
        if focused_window is not None and self._is_window_valid(focused_window.get_xlib_window()):
            focused_window.get_xlib_window().set_input_focus(Xlib.X.RevertToParent, 0)
            focused_window.get_xlib_window().change_attributes(
                None, border_pixel=self._colormap.alloc_named_color(WINDOW_BORDER_COLOR_FOCUSED).pixel
            )
        else:
            self._root_window.set_input_focus(Xlib.X.RevertToParent, 0)

    def _adjust_master_factor(self, amount: float) -> None:
        workspace: Optional[Workspace] = self.root.search_active(Workspace)
        assert workspace is not None, "No active workspace?"
        workspace.adjust_master_factor(amount)
        self._update_window_positions()

    def _focus_screen_by_offset(self, offset: int) -> None:
        screen: Optional[Screen] = self.root.search_active(Screen)
        assert screen is not None, "No active screen?"
        screen_new: Screen = screen.get_sibling_by_offset(offset)
        screen_new.activate()
        self._update_window_focus()

    def _is_window_valid(self, xlib_window: Xlib.protocol.rq.Window) -> bool:
        return xlib_window in self._root_window.query_tree().children

    def _get_screen_count(self) -> int:
        return len(self._display.xinerama_query_screens()._data["screens"])

    def _get_screen_data(self, i_screen: int, data: str) -> int:
        return int(self._display.xinerama_query_screens()._data["screens"][i_screen][data])


class WindowManager:
    def __init__(self, display: Xlib.display.Display, cmds: Dict[str, str]) -> None:
        self._display: Xlib.display.Display = display
        self._cmds = cmds

        self._root_window: Xlib.protocol.rq.Window = self._display.screen().root
        self._root_window.change_attributes(
            event_mask=Xlib.X.PropertyChangeMask | Xlib.X.SubstructureNotifyMask | Xlib.X.SubstructureRedirectMask
        )

        self._is_running: bool = True
        self._tree: Tree = Tree(self._display)

        self._keys: Tuple[Key, ...] = (
            Key(self._display, KEY_QUIT, lambda: self._quit()),
            Key(self._display, KEY_SPAWN_LAUNCHER, lambda: self._spawn_subprocess(CMD_LAUNCHER)),
            Key(self._display, KEY_SPAWN_TASK_SWITCHER, lambda: self._spawn_task_switcher()),
            Key(self._display, KEY_SPAWN_TERMINAL, lambda: self._spawn_subprocess(CMD_TERMINAL)),
            Key(self._display, KEY_MOVE_WINDOW_TO_TASK, lambda: self._spawn_task_switcher(move_window=True)),
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
        self._tree.on_event(event)

        if event.type == Xlib.X.KeyPress:
            for key in self._keys:
                key.on_event(event)

    def is_running(self) -> bool:
        return self._is_running

    def _spawn_subprocess(self, command: str) -> None:
        env: Dict[str, str] = dict(os.environ)
        env.update({ENV_OUT_TASK_NAME: self._tree.get_active_task_name()})
        cwd = self._task_workdirs.get(self._tree.get_active_task_name(), None)
        if cwd is not None and os.path.isdir(cwd):
            subprocess.Popen((self._cmds[command],), cwd=cwd, env=env)
        else:
            subprocess.Popen((self._cmds[command],), env=env)

    def _spawn_task_switcher(self, move_window: bool = False) -> None:
        window_move_marker: str = TASK_WINDOW_MOVE_MARKER if move_window else ""
        p1: subprocess.Popen = subprocess.Popen((self._cmds[CMD_DMENU],), stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        p2: subprocess.Popen = subprocess.Popen(
            (self._cmds[CMD_TR], "\\n", "\\0"), stdin=p1.stdout, stdout=subprocess.PIPE
        )
        p3: subprocess.Popen = subprocess.Popen(
            (self._cmds[CMD_XARGS], "-0", "-r", "-I{}", self._cmds[CMD_XSETROOT], "-name", f"{window_move_marker}{{}}"),
            stdin=p2.stdout,
        )
        if p1.stdin is not None:
            p1.stdin.write(("\n".join(reversed(self._tree.get_all_task_names()))).encode())
            p1.stdin.close()
        if p1.stdout is not None:
            p1.stdout.close()
        if p2.stdout is not None:
            p2.stdout.close()

    def _quit(self) -> None:
        self._is_running = False


def main() -> None:
    cmds: Dict[str, str] = {}
    for cmd in CMDS:
        path: Optional[str] = shutil.which(cmd)
        assert path is not None, "'%s' not found in PATH." % cmd
        cmds[cmd] = path
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    display: Xlib.display.Display = Xlib.display.Display()
    window_manager: WindowManager = WindowManager(display, cmds)
    while window_manager.is_running():
        window_manager.on_event(display.next_event())
    display.close()


if __name__ == "__main__":
    main()
