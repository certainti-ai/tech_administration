# Legacy maintenance scripts

The operator's original workspace, vendored verbatim on 2026-08-17. 114 files.
Secrets were already replaced with `CHANGE_ME` before upload — see
`trd365_maintenance/SANITIZATION_NOTE.md`.

**This tree is reference material. Do not edit it in place.** Phase 1 refactors
*out* of here into `../packages/`, so the original stays available to compare
against — which matters most for `manual-rd-percent-update`, where the
JavaScript is the specification for the Python port.

What each module does, and every trap found in it, is documented in
[`../docs/knowledge-base.md`](../docs/knowledge-base.md).
