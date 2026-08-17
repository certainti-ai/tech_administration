"""Site + document-library (drive) resolution on Microsoft Graph."""

from urllib.parse import urlparse


def parse_site_url(site_url):
    """'https://host.sharepoint.com/sites/Name' -> (hostname, '/sites/Name')."""
    u = urlparse(site_url)
    path = u.path.rstrip("/")
    if not path:
        raise ValueError(f"site_url has no server-relative path: {site_url}")
    return u.hostname, path


def get_site(client, site_url):
    """Resolve a site by URL. Returns the Graph site object (has .id)."""
    host, path = parse_site_url(site_url)
    return client.get(f"/sites/{host}:{path}")


def list_drives(client, site_id):
    """All document libraries (drives) of a site: [{id, name, driveType}]."""
    return list(client.get_all(f"/sites/{site_id}/drives"))


def default_drive(client, site_id):
    return client.get(f"/sites/{site_id}/drive")


def create_library(client, site_id, display_name):
    """Create a new document library on the dest site and return its drive.

    Libraries are lists with the documentLibrary template; the backing drive is
    then discoverable via /sites/{id}/drives (may take a moment to appear)."""
    client.post(f"/sites/{site_id}/lists",
                json={"displayName": display_name,
                      "list": {"template": "documentLibrary"}})
    for d in list_drives(client, site_id):
        if d.get("name") == display_name:
            return d
    return None


def get_or_create_library_drive(client, site_id, name, create=True, cache=None):
    """Find a dest drive by library name; optionally create it if missing."""
    if cache is None:
        cache = {d.get("name"): d for d in list_drives(client, site_id)}
    if name in cache:
        return cache[name], cache
    if not create:
        return None, cache
    d = create_library(client, site_id, name)
    if d:
        cache[name] = d
    return d, cache


def iter_children(client, drive_id, item_id):
    """Yield direct children of a folder driveItem."""
    yield from client.get_all(f"/drives/{drive_id}/items/{item_id}/children")


def ensure_folder(client, drive_id, parent_id, name):
    """Create (or return existing) child folder under parent. Returns driveItem."""
    return client.post(
        f"/drives/{drive_id}/items/{parent_id}/children",
        json={"name": name, "folder": {},
              "@microsoft.graph.conflictBehavior": "replace"})


def ensure_path(client, drive_id, root_id, rel_path, cache):
    """Ensure a nested folder path exists (relative to root), returning the leaf
    folder id. NON-destructive: each segment is resolved by path first and only
    CREATED if missing — never 'replace'd (which could disturb existing content).
    `cache` maps a relative path -> folder id to avoid repeated lookups."""
    from urllib.parse import quote
    parent = root_id
    cur = ""
    for seg in [s for s in rel_path.split("/") if s]:
        cur = f"{cur}/{seg}" if cur else seg
        if cur in cache:
            parent = cache[cur]
            continue
        enc = "/".join(quote(p, safe="") for p in cur.split("/"))
        try:
            item = client.get(f"/drives/{drive_id}/root:/{enc}")
            parent = item["id"]
        except Exception as exc:
            if getattr(exc, "status", None) == 404:
                parent = ensure_folder(client, drive_id, parent, seg)["id"]
            else:
                raise
        cache[cur] = parent
    return parent
