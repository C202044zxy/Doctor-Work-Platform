# Repository Guidelines

## Project Structure & Module Organization

This repository is currently in the planning phase for the Doctor Work Platform. `project_plan.md` is the source of truth for baseline scope, task IDs, ownership, dependencies, capacity, milestones, and unresolved decisions.

No application source, tests, assets, dependency manifests, or startup scripts exist yet. The planned stack is FastAPI, Vue 3, MySQL with Alembic migrations, and Redis, with WebSocket messaging and browser WebRTC. When scaffolding lands, document the actual backend, frontend, test, and asset paths here and in the README.

## Build, Test, and Development Commands

There are no configured build, development, or automated test commands yet. Do not assume commands such as `npm test` work.

Available review commands:

- `git diff --check`: detect whitespace errors before committing.
- `git diff -- project_plan.md AGENTS.md`: review documentation changes.
- `git status --short`: confirm the intended change set.

Task T04 requires a README and one-command startup script. Add verified setup and execution commands when implementing the scaffold.

## Coding Style & Naming Conventions

Use ATX Markdown headings (`## Heading`), hyphen bullets, and readable tables consistent with `project_plan.md`. Preserve task identifiers such as T01 and M01 and module identifiers such as M1 and M8.

No code formatter, linter, or language-specific indentation standard is configured. Establish those conventions with the initial scaffold and document the selected tools.

## Testing Guidelines

No test framework or coverage threshold exists yet. For planning edits, check task totals, owner allocations, dependencies, and milestone consistency. Distinguish estimated task-hours from actual availability and preserve the four-hour daily cap per person.

Future acceptance checks should cover the three documented demonstration flows, including role and department access, allergy blocking, archive locking, and consultations. Document test locations, naming conventions, and commands when tests are introduced.

## Commit & Pull Request Guidelines

Existing history uses `docs: add project plan and schedule`; follow the concise `type: imperative summary` pattern. Keep changes focused.

PRs should explain the change, reference relevant task IDs or issues, and report validation performed. Include screenshots for UI changes once an interface exists. For scope or schedule changes, state the capacity impact and record unresolved decisions explicitly.
