# Recovery Drill And Blackout Gauntlet

The recovery drill is Somi's compact proof that the continuity stack works as a
system under survival-mode assumptions.

## What It Exercises

- survival-mode hardware profile selection
- offline resilience report
- continuity domain coverage
- resumable workflow execution
- store-and-forward node exchange

## CLI

```powershell
somi offline drill --root C:\somex --runtime-mode survival --scenario blackout
```

## Output

The drill writes a JSON artifact to:

- `audit/phase176_recovery_drill.json`

## Intent

This is not a cinematic simulation. It is a practical confidence check that
Somi's local recovery layers still work together when web assumptions drop
away.
