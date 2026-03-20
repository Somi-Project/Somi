# Hardware Tiers And Survival Mode

Somi should preserve capability while adapting gracefully to weaker hardware.

Current posture:
- `ops/hardware_tiers.py` classifies local hardware into `survival`, `low`,
  `balanced`, or `high`
- the profile is advisory, not restrictive
- the profile recommends context size, parallelism, background posture, OCR
  depth, and preferred knowledge-pack variant

Design rule:
- do not weaken Somi globally
- keep the same framework ceiling on strong hardware
- give weaker hardware a practical operating mode instead of a broken one

Current runtime modes:
- `survival`
- `low_power`
- `normal`

Future work:
- expose the runtime mode directly in the Control Room
- persist user-selected mode overrides
- let offline knowledge packs ship both `compact` and `expanded` variants
