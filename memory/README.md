# Memory

**Dynamic** knowledge: things we *learned* while running, as opposed to static
game facts (which live in `../knowledge/`).

| File                    | What it holds                                             |
| ----------------------- | -------------------------------------------------------- |
| `user_rules.json`       | Hard rules from the player the bot must always obey.     |
| `mistakes_learned.json` | Bugs we hit and the fix, so we don't repeat them.        |

## When to write here

- The player states a rule ("never spend money", "always do X first") -> `user_rules.json`.
- We fix a non-obvious bug and the lesson is reusable -> `mistakes_learned.json`
  (add an entry with `context`, `mistake`, `fix`, `tags`).

Keep entries short. Bump `last_updated` on every edit.
