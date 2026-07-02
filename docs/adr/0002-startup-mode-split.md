# Split startup behavior by runtime mode

API mode now ignores startup task configs and only restores persisted running tasks, while console mode executes startup tasks once and does not run recovery. This keeps production startup deterministic and keeps one-shot console runs from re-entering historical runtime state.
