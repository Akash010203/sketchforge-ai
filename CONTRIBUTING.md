# Contributing

```bash
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -e ".[ui,dev]"
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check src tests scripts
```

Rules that keep the project honest:

1. **No application API.** No FastAPI/Flask/REST/GraphQL, no local HTTP server, no microservices.
   Modules call each other directly. Remote providers are outbound clients under `integrations/` only.
2. **Design IR is the contract.** Don't invent a second representation of a design; change the IR
   through `editor` commands so edits are validated and undoable.
3. **Measure, then change.** State the expected measurable improvement, run the baseline, make the
   smallest coherent change, run targeted then full tests, and record the before/after in
   `docs/EXPERIMENT_LOG.md`. Never weaken a test to make it pass. Three failed attempts at the same
   failure → stop and reassess.
4. **Say what is verified.** A feature is `VERIFIED` in `TASKS.md` only when its acceptance criterion
   was measured. Synthetic-only results must be labelled synthetic.
5. **No secrets, no big data in git** (`datasets/raw`, `checkpoints`, `output` are ignored).
6. Report fixture changes as fixture changes (see EXPERIMENT_LOG E6).
