# Migration Note: Created from Legacy Monolith

This backend repository skeleton (`landinghelp_server_backend`) is created from the legacy Django monolith (`landinghelp_server`) as a new long-term private backend target.

## Intent
- Legacy monolith is now source/reference, not long-term development repo.
- Backend-private code will be migrated here incrementally.
- Frontend is planned as a separate repository (`landinghelp_server_frontend`).

## Migration Principles
1. Keep backend domain logic private and centralized in this repo.
2. Move code app-by-app with tests, migrations, and API compatibility checks.
3. Avoid broad copy-all operations; use staged migration with validation.
4. Maintain temporary backward compatibility during cutover.

## Initial Skeleton Scope (this step)
- Django project config scaffold
- App package placeholders under `apps/`
- Dependency and container scaffolding
- Temporary legacy support markers for templates/static

## Out of Scope (this step)
- Full code migration from legacy apps
- Frontend implementation
- Final production deployment manifests
