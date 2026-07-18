# ADR-002: Single-Domain Deployment

**Status:** Accepted

## Decision

- Each service instance binds one `settings.plugins.default_namespace`.
- UI shows domain read-only; users select `kb_name` only.
- Cross-domain retrieval uses multiple instances, not fan-out in Core.
