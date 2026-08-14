# Knowledge base

This folder is the bot's **knowledge base**: what we know about *Kingshot*.
It is split into three roles so files stay small and decisions are easy to make:

| Folder        | Role                        | Content type            |
| ------------- | --------------------------- | ----------------------- |
| `knowledge/`  | **What is true** (facts)    | Static game data (JSON) |
| `../memory/`  | **What we learned**         | Dynamic notes (JSON)    |
| `../planner/` | **What to do with it**      | Priorities & strategies |
| `../executor/`| **How to do it** (routines) | Python action code      |

## `knowledge/` — static facts

One JSON file per game domain. Every file follows [`_schema.json`](_schema.json):

- `domain` / `title` / `description` — what the file covers.
- `status` — `scaffold` (empty), `partial` (some data), or `complete`.
- `last_updated` — ISO date of the last edit.
- `sources` — how we learned it (live test, in-game screen, user, wiki...).
- `entries` — the actual facts, each with a stable `id`.
- `open_questions` — what we still need to find out.

### Domains

Player, Buildings, Heroes, Research, Troops, Arena, Alliance, Events,
Daily Missions, Weekly Missions, Resources, Premium Currency, Shops, Rally,
Bosses, Exploration, Formation, Inventory, Pets, Hero Gear.

Most start as `scaffold` and are filled in as we learn, keeping each file focused.

## How to add/expand knowledge

1. Open the relevant `knowledge/<domain>.json` (or copy `_schema.json` for a new one).
2. Add an object to `entries` with a stable `id`.
3. Bump `last_updated` and, when the file has real data, set `status` to `partial`/`complete`.
4. If it is a rule the bot must always obey, put it in `../memory/user_rules.json`.
5. If it is a fix for a mistake we hit, add it to `../memory/mistakes_learned.json`.
