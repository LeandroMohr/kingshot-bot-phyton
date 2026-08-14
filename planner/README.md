# Planner

**Applies** the knowledge base to decide *what to do and in which order*.
Kept separate from `../knowledge/` (facts) and `../executor/` (how to act) so
files stay small and focused.

| File               | Role                                                        |
| ------------------ | ----------------------------------------------------------- |
| `priorities.json`  | Order/enable-state of tasks each cycle (mirrors the loop).  |
| `strategies.json`  | Higher-level policies (what to prioritize when). Scaffold.  |

Today the running order lives in `tasks/__init__.py`; `priorities.json`
documents it in data form. As the planner grows it will read these files to
drive decisions instead of hard-coding order in code.
