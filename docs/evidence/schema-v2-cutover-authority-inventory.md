# Schema v2 cutover authority inventory

This inventory is part of the Task 9 cutover review. The installed catalog is
the only production workflow authority after the cutover commit.

| Existing surface | Schema-v2 replacement or disposition |
|---|---|
| `planner.registry()` and `_fallback()` | verified `packs/index.json`, `load_catalog()`, `compile_matcher()` |
| v1 recipe loading | active adoption records bound to content-addressed recipe artifacts |
| `perception_walker_for()` workflow branches | compiled observation plans and `build_compiled_perception()` |
| `PackRegistry` manifest scanning | `PackRegistry.from_verified()` from `load_catalog()` |
| CLI `--goal` path | `plan_compiled_goal()` → `bind_workflow()` → `run_tour_for_workflow()` |
| CLI `--recipe` path | deleted; raw overlay mode remains available |
| Ask workflow launch | the already materialized `CompiledWorkflow`; no recipe-path lookup |
| `ghostcursor/packs/manifests/` | deleted |
| `ghostcursor/packs/recipes/` | deleted |
| `ghostcursor/reasoning/recipes/` | deleted |
| candidate copies under `docs/superpowers/candidates/` | quarantined and unreachable from production |

The active adoption records bind the exact Task 8 pack, intent, recipe, and
evidence digests. Synthetic Export is bound to its demo-module content SHA;
the VS Code workflows are bound to executable version `1.135.0.0`.

The production target policy is exactly one matching application window after
optional `--target` narrowing. There is no foreground tie-break. If narrowing
still leaves multiple windows, production refuses and names every HWND/title.
