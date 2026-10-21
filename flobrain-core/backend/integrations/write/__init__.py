"""Write-back connectors (growth round W4, flag ``write_integrations``).

Buddies propose writes to Google Workspace, Microsoft 365, Jira, HubSpot, Odoo and Zoho. Every
write is an approval-gated tool registered through ``actions.plugins.register_tool``: nothing runs
until a person approves it. Tokens are stored encrypted (``integrations.crypto``) and calls go only
to each provider's allowlisted HTTPS hosts through ``integrations.write.transport``.

Layout:
- ``registry``: Provider and Action declarations and lookup.
- ``catalog``: one module per provider (schemas, previews, executors, demo results).
- ``models``: connections, OAuth state, per-org action switches.
- ``transport``: the allowlisted HTTPS client with one token refresh on 401.
- ``oauth``: authorization code + PKCE helpers.
- ``connections``: which connection a call uses and what the API shows about it.
- ``tools``: registration, ``check`` and ``execute`` for the action registry.
"""
