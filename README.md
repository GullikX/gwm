# gwm - task-based, tiling window manager

Do you usually run out of workspaces or have trouble keeping track of your way-too-many windows? gwm is a new window manager for X which tries to solve these problems by using a task-based structure.

A typical *nix window manager usually has a linear workspace layout like this:

* Workspace 1
* Workspace 2
* Workspace 3
* Workspace 4
* Workspace 5
* Workspace 6
* Workspace 7
* Workspace 8
* Workspace 9
* ...

Compare this to the workspace layout of gwm:

* Task "just some lazy web surf"
    * Workspace 1
    * Workspace 2
    * Workspace 3
    * Workspace 4
* Task "master thesis"
    * Workspace 1
    * Workspace 2
    * Workspace 3
    * Workspace 4
* Task "update remote web server"
    * Workspace 1
    * Workspace 2
    * Workspace 3
    * Workspace 4
* ...

In gwm, workspaces are grouped by their *task*, and these tasks can be created and destroyed on the fly. When you want to start working on something new, create a new task and you have 4 blank workspaces to use. Leave an empty task and it is automatically destroyed.

Switching tasks is done using `dmenu` and `xsetroot`. Press the keybinding (`super+space` by default) to fire up the dmenu task switcher. Select an already existing task to switch to it or enter a new name to create a new task. The information is sent to gwm by setting the name of the root window using xsetroot.

The task-based nature of gwm not only simplifies keeping track of windows, but also makes it possible for the window manager behave differently depending on the active task. Currently there is a feature which automatically sets the work directory of external commands (notably terminal emulators) depending on the current task name. For example, you may define something like this:
```
"gwm" => "/home/username/gitrepos/gwm"
"music" => "/home/username/data/music"
```


### Default keybindings

* `super+space` launch task switcher
* `super+{1, 2, 3, 4}` switch to workspace {1, 2, 3, 4} within the current task
* `super+shift+{1, 2, 3, 4}` move window to workspace {1, 2, 3, 4} within the current task
* `super+{left, right}` change focused window in current workspace
* `super+shift+{left, right}` change size of the master window area
* `super+tab` move focused window to master area (or move to stack if already there)
* `super+F4` close focused window
* `super+enter` launch a terminal (st by default)
* `super+shift+enter` start the dmenu application launcher
* `super+shift+F12` close all open windows and exit gwm


### Configuration

gwm is configured by editing the file `config.h` and recompiling.


### Notes

* gwm is a 100% tiling window manager. Any applications which require floating windows or specific window sizes *will* break.
* gwm currently only supports single-monitor configurations.


### Dependencies

* dmenu
* libx11
* xsetroot
* gcc (compilation)
* libx11-dev (compilation)


### Installing and running

Compile and install:

```
make && sudo make install
```

Start gwm by specifying it in your ~/.xinitrc:

```
exec gwm
```

and running `startx` from the tty.


### Links

* Main repo: https://github.com/GullikX/gwm
* Repo mirrors:
    * https://bitbucket.org/Gullik/gwm
    * https://git.sr.ht/~gullik/gwm
* Build service: https://builds.sr.ht/~gullik/gwm


### Acknowledgments

* gwm is heavily inspired by dwm, written by the Suckless team. Check it out if you haven't: https://dwm.suckless.org
