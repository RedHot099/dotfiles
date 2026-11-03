# Agents panel

User clone of the Omarchy 4 agents plugin. The stock Panel.qml, Main.qml,
Agent.qml, manifest settings, and icons were copied from the installed
Omarchy package on 2026-11-03. Main.qml uses the adjacent `update-usage`
command instead of the packaged updater.

The packaged Codex collector calls select() on a text-buffered pipe and then
readline(). When a notification and RPC response arrive together, readline()
can buffer the response while select() waits on an empty OS pipe. The result
is a false `account/read` timeout even with a working login.

`update-usage` delegates other providers to the packaged updater. For Codex,
it loads the packaged collector and replaces only its RPC reader with raw
pipe reads. Local session scanning, caches, authentication, and limit parsing
continue to use the installed collector. Records use the usual atomic rename.

The clone is selected as `kuba.agents` in both bar layouts. Its `clonedFrom`
metadata preserves the `omarchy.agents` IPC alias. User configuration and the
packaged Omarchy tree remain separate.

Verify with `./scripts/verify-bootstrap.sh`. The regression tests send a
notification and response in one pipe write, split a response across writes,
and exercise EOF and timeout errors. After Omarchy changes the collector or
plugin API, recheck this clone against the packaged version. Once upstream
fixes the pipe reader, the clone can be retired.
