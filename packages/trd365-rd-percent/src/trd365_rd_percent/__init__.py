"""
Manual R&D percentage correction.

Applies a correction to a project fiscal's R&D percentages and every downstream
figure the application would recompute — QRE dollars, qualification, the case
module's copies, the main-database summary, the audit trail.

It exists because the platform's main and org databases are separate Postgres
servers, so no single SQL script can span both. The application does not use a
distributed transaction either; it awaits two connections in sequence. This
mirrors that, one transaction per database, in the same order.
"""
