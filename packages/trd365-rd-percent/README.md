# trd365-rd-percent

Manual R&D percentage correction, reproducing the application's own write path.

Ported from `legacy/trd365_maintenance/manual-rd-percent-update` (Node.js), with
the arithmetic checked against `certainti-ai/rdcredits_platform_be` at `6e16f32`
rather than transcribed — the legacy tool disagrees with the application in two
places, both of which overstate money. See the module docstring in
`calculation.py`.
