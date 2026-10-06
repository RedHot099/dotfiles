// Per-orientation bar layouts for the Omarchy shell.
//
// Third-party services receive a scoped shell API that can neither rewrite
// the bar layout nor report every change to it. This service therefore
// watches shell.json itself and runs the bundled `sync-layout` script, which
// swaps and saves the layouts in that file and asks the shell to reload it.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: service

  // Injected by omarchy-shell. Not used; declared so the host can set it.
  property var shell: null

  readonly property string pluginId: "bar-orientation"
  readonly property string script: decodeURIComponent(String(Qt.resolvedUrl("sync-layout")).replace(/^file:\/\//, ""))

  // One drag or command can rewrite the file several times. Let it settle,
  // and never run two syncs at once.
  Timer {
    id: settle
    interval: 500
    running: true
    onTriggered: {
      if (sync.running) restart()
      else sync.running = true
    }
  }

  Process {
    id: sync
    command: ["bash", service.script, service.pluginId]
    onExited: function(exitCode) {
      if (exitCode !== 0) console.warn(service.pluginId + ": sync-layout exited with " + exitCode)
    }
  }

  FileView {
    path: Quickshell.env("HOME") + "/.config/omarchy/shell.json"
    watchChanges: true
    printErrors: false
    onFileChanged: {
      reload()
      settle.restart()
    }
  }
}
