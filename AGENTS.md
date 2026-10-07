# AGENTS.md

Notes for coding agents (and people) working in this repo. User-facing docs are in `README.md`.

## Layout

| Path | What |
| --- | --- |
| `custom_components/pawport/api.py` | Cloud client: REST sign-in, GraphQL reads and door commands. |
| `custom_components/pawport/models.py` | Typed views of the `authDataGet` response. |
| `custom_components/pawport/coordinator.py` | 30s poll, door commands, silent re-sign-in with a stored password. |
| `custom_components/pawport/entity.py` | Door, pet and tag base entities, and discovery of ones added later. |
| `custom_components/pawport/{switch,number,select}.py` | Door settings, each a description naming its `sendDoorCommand` command and argument. |
| `custom_components/pawport/config_flow.py` | Email, then code or password; reauth reuses the same steps. |
| `tests/conftest.py` | `FakePawport`, an in-memory cloud the tests run the real client against. |

## Rules

- `api.py` and `models.py` import nothing from Home Assistant. Keep it that way, so the client can move to a library unchanged.
- The API is unofficial. Command shapes, ranges and units come from how the Pawport app itself builds and renders them; note that source in a comment when adding one. The models treat every field as optional, so a missing key costs one entity, not the whole poll.
- Translations live only in `translations/en.json`, as literal text. Custom integrations don't get `strings.json` or `[%key:...]` references resolved.
- New behaviour comes with tests through `FakePawport`, not by mocking the client. Coverage floor is in `pyproject.toml`.
- `quality_scale.yaml` tracks the HA Integration Quality Scale. Update it when a rule's status changes.
- Reverse-engineering material (app dumps, captures) is never committed here.
- `manifest.json` keeps version `0.0.0`; the release workflow sets the real one from the pushed tag. Releases are immutable, so the workflow must create a release with its asset in one step, never publish first and upload after.

## Commands

```bash
scripts/setup     # uv sync
scripts/lint      # ruff format, ruff check --fix, mypy (strict)
scripts/test      # pytest with coverage
scripts/develop   # dev Home Assistant on :8123
```

Conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
