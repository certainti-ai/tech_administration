"""
Thin Microsoft Graph client: auth injection, throttling-aware retry, paging, file
download, and chunked upload sessions (for files > 4 MB).

One GraphClient wraps one TenantAuth, so a migration uses two clients (source +
dest). All calls target Graph v1.0.
"""

import time
import requests

GRAPH = "https://graph.microsoft.com/v1.0"
RETRY_STATUS = {429, 500, 502, 503, 504}


class GraphError(RuntimeError):
    def __init__(self, method, url, resp):
        self.status = resp.status_code
        body = ""
        try:
            body = resp.text[:600]
        except Exception:
            pass
        super().__init__(f"{method} {url} -> {resp.status_code}: {body}")


class GraphClient:
    def __init__(self, auth, max_retries=6, timeout=120):
        self.auth = auth
        self.max_retries = max_retries
        self.timeout = timeout
        self.s = requests.Session()

    # ── low-level request with retry/backoff ─────────────────────────────────
    def _req(self, method, url, *, headers=None, absolute=False, stream=False, **kw):
        full = url if (absolute or url.startswith("http")) else GRAPH + url
        for attempt in range(1, self.max_retries + 1):
            try:
                h = {"Authorization": f"Bearer {self.auth.token()}"}
                if headers:
                    h.update(headers)
                resp = self.s.request(method, full, headers=h, timeout=self.timeout, stream=stream, **kw)
            except requests.exceptions.RequestException as exc:
                # network blip / dropped connection — back off and retry so a
                # brief disruption doesn't kill a long migration.
                if attempt < self.max_retries:
                    time.sleep(min(90, 3 * 2 ** attempt))
                    continue
                raise
            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                wait = int(resp.headers.get("Retry-After", 0)) or min(60, 2 ** attempt)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise GraphError(method, full, resp)
            return resp
        raise GraphError(method, full, resp)

    # ── JSON helpers ─────────────────────────────────────────────────────────
    def get(self, url, **kw):
        return self._req("GET", url, **kw).json()

    def get_all(self, url, **kw):
        """Follow @odata.nextLink, yielding every item in a collection."""
        while url:
            data = self._req("GET", url, absolute=url.startswith("http"), **kw).json()
            for item in data.get("value", []):
                yield item
            url = data.get("@odata.nextLink")
            kw.pop("params", None)  # nextLink already carries params

    def post(self, url, json=None, **kw):
        return self._req("POST", url, json=json, **kw).json()

    def patch(self, url, json=None, **kw):
        return self._req("PATCH", url, json=json, **kw).json()

    # ── files ────────────────────────────────────────────────────────────────
    def download_to(self, drive_id, item_id, fileobj):
        """Stream a driveItem's content into an open binary file object."""
        r = self._req("GET", f"/drives/{drive_id}/items/{item_id}/content", stream=True)
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                fileobj.write(chunk)

    def upload_small(self, drive_id, parent_id, name, fileobj, conflict="fail"):
        """Simple PUT for files <= 4 MB. Returns the created driveItem."""
        url = (f"/drives/{drive_id}/items/{parent_id}:/{_esc(name)}:/content"
               f"?@microsoft.graph.conflictBehavior={conflict}")
        return self._req("PUT", url, data=fileobj.read(),
                         headers={"Content-Type": "application/octet-stream"}).json()

    def upload_large(self, drive_id, parent_id, name, path, size, chunk_size,
                     file_system_info=None, conflict="fail"):
        """Chunked upload session for large files. Returns the created driveItem."""
        item = {"@microsoft.graph.conflictBehavior": conflict, "name": name}
        if file_system_info:
            item["fileSystemInfo"] = file_system_info
        sess = self.post(
            f"/drives/{drive_id}/items/{parent_id}:/{_esc(name)}:/createUploadSession",
            json={"item": item})
        upload_url = sess["uploadUrl"]
        with open(path, "rb") as fh:
            start = 0
            while start < size:
                chunk = fh.read(chunk_size)
                end = start + len(chunk) - 1
                headers = {"Content-Length": str(len(chunk)),
                           "Content-Range": f"bytes {start}-{end}/{size}"}
                # upload URLs are pre-authenticated; no bearer needed, own retry.
                # Re-PUTting the same byte range is idempotent, so retrying a chunk
                # after a dropped/again SSL connection is safe.
                for attempt in range(1, self.max_retries + 1):
                    try:
                        r = self.s.put(upload_url, headers=headers, data=chunk, timeout=self.timeout)
                    except requests.exceptions.RequestException:
                        if attempt < self.max_retries:
                            time.sleep(min(90, 3 * 2 ** attempt))
                            continue
                        raise
                    if r.status_code in RETRY_STATUS and attempt < self.max_retries:
                        time.sleep(int(r.headers.get("Retry-After", 0)) or min(60, 2 ** attempt))
                        continue
                    if r.status_code >= 400:
                        raise GraphError("PUT(chunk)", upload_url, r)
                    break
                start = end + 1
                if r.status_code in (200, 201):
                    return r.json()
        return {}


def _esc(name):
    # path segment escaping for Graph ':/name:/' addressing
    return requests.utils.quote(name, safe="")
