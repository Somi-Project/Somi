# Somi Learning

This package holds the lighter-weight learning and evaluation helpers that make
Somi more adaptive without giving it unsafe self-modification powers.

Main files:
- `skills.py`: learning-side helpers for skill scoring and selection.
- `scorecards.py`: reusable scoring helpers for comparing runs or strategies.
- `trajectories.py`: trajectory and step-history helpers for longer tasks.

For basic users:
- You usually do not need to edit this folder directly.
- Think of it as Somi's "how did this approach perform?" layer.

For developers:
- Keep this folder focused on evaluation, scoring, and learning signals.
- Do not route destructive actions or execution approval logic through here.
- If a feature needs user approval or side-effect policy, that belongs in
  `runtime/`, `ops/`, or the execution layer instead.
