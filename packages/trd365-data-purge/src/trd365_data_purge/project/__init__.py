"""
Purge a whole project: every one of its fiscal years, in order.

There is no separate SQL and no separate manifest. A project purge *is* the
project-fiscal purge run once per fiscal year, oldest first, with the final one
carrying ``is_last_fiscal`` so that its run also removes the project row and
recomputes the account-level totals. That is the vendor's own design, and
repeating it here rather than writing a project-level deletion is what keeps the
financial arithmetic identical between deleting a project and deleting its years
one at a time.
"""
