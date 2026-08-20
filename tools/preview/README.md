# Preview

Renders a single-page snapshot of what the system currently does, for someone who
wants to see it without a deployment existing.

```bash
python tools/preview/generate.py /tmp/preview.json   # run the utilities, capture output
python tools/preview/build.py    /tmp/preview.json /tmp/console.html
```

`generate.py` runs the real utilities against the packages' own test doubles and
captures what they produce: the registry-generated catalogue, a data-model
snapshot, an account purge dry run, the reports, and the audit records.
`build.py` renders that JSON into a page.

Two rules, because the point of the page is that a reader can trust it:

- **Nothing on the page is written by hand.** Every figure, report and record
  comes out of `generate.py`. If a number looks wrong, the code is wrong.
- **The page says what it is.** It has never been deployed and has never
  contacted a database, and it says so above the fold. A preview that reads like
  a running system is worse than no preview.

Regenerate after any change that would alter the output — a new utility, a
changed report format, a different registry entry.
