## Scope

<!-- WHAT you're doing and WHY. The big picture. -->

closes #<issue>

## Implementation

<!-- HOW you achieved it: high-level flow, refactors, tradeoffs, and anything you
want reviewers to look at closely. The line-by-line "how" lives in the diff. -->

## Renders / Screenshots

<!-- collajit is a visual app — show, don't tell. For changes to the mosaic /
generative / compositor output, include the SAME target rendered before & after
at the SAME settings. For UI, a screenshot. For pure backend/core internals, the
relevant numbers or a flow note is fine. -->

|        | before | after |
| ------ | ------ | ----- |
| render |        |       |

## How to Test

<!-- 1) Automated: the unit/integration tests you added or updated for this
behavior (no PR merges without them — see CLAUDE.md → Testing).
2) Manual: step-by-step to see the change. -->

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`
- `cd frontend && npm test && npm run build`

## Risk

<!-- Anything that changes catalog schema (bump FEATURE_VERSION?), the compositor
output, the fetch/source behavior, or stored prefs. Call out migrations explicitly. -->
