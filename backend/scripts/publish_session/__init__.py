"""cc-publish-session — the dashboard publication gate.

Stamps ``pl_session_release`` once a session's data is complete and (normal
path) its NotebookLM audio is present, so the dashboard flip to the newest
session is atomic and can happen the same evening. See ``main`` for the rules.
"""
