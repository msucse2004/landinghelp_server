# Cleanup Notes (Planned)

## Temporary legacy items to remove later
- `templates/` directory in backend (temporary migration support only)
- `static/` directory in backend (temporary migration support only)

## Target end state
- Backend serves APIs and private admin/ops endpoints only.
- UI rendering moves to `landinghelp_server_frontend`.
- Static asset ownership shifts to frontend build/runtime pipeline.

## Recommended phased cleanup
1. Migrate each screen to frontend and switch traffic to API usage.
2. Remove corresponding server-rendered view/template.
3. Remove static asset duplication from backend.
4. Keep only backend-required admin assets.
