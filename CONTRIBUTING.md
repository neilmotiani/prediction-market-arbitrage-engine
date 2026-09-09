# Contributing

Use Python 3.12, uv, and Node 22. Run `make install`, then start `make backend` and `make frontend` in separate terminals. Mock data requires no credentials. `make dev` boots the complete PostgreSQL Compose environment.

Before a change is ready:

```bash
make test
make lint
cd frontend && npm run build
```

Use `uv run ruff format backend tests scripts` and `cd frontend && npm run format`. Commit both lockfiles whenever dependencies change. Keep financial values Decimal through backend calculations and use explicit USD/share units. Never replace book walking with a top-quote multiplication.

Add focused tests when changing fee schedules, settlement assumptions, matching rules, capital accounting, or persistence. A regression test should demonstrate a wrong economic decision or failed user operation, not just mirror a private method. Keep network-dependent tests opt-in; venue parsing belongs in deterministic fixture tests.

New adapters implement the read-only `VenueConnector` interface, preserve timestamp provenance, and fail closed on schema or fee uncertainty. Do not add secret values or a real execution path to the default application. Matching changes must preserve explicit settlement validation.

Explain concrete before/after behavior and validation in pull requests. For database changes, introduce a reviewed migration instead of assuming startup `create_all` will alter existing tables. One backend worker is intentional until portfolio locking moves into a dedicated transactional service.

For dashboard changes, verify filters, keyboard dialog navigation, paper execution/settlement, reconnect states, mobile layouts, and 200% zoom in a real browser. See `docs/VALIDATION.md` for the initial run's browser limitation.
