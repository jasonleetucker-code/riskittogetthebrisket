# MCP protocol schema fixture

`schema-2026-07-28.json` is the upstream MCP JSON Schema copied from
[`modelcontextprotocol/schema/2026-07-28/schema.json`](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/dae694f61a31f7a3ec2af3aff709e11f70f61e48/schema/2026-07-28/schema.json)
at upstream commit `dae694f61a31f7a3ec2af3aff709e11f70f61e48`.

Upstream schema SHA-256: `ef70b61f99b6d2e5e3b46863822eab08dff6a45bedc7a08914e0e5b133f40203`.
The vendored fixture preserves the schema and removes one surplus terminal blank line to satisfy the repository's whitespace check.

The API tests validate the JSON-RPC discovery, tool-list, and tool-call
responses against the schema definitions in that fixture. Refresh this file
only from an official protocol revision and update the pinned source and hash.
