"""GRAIN canal dataset: bounded member extraction and schema-checked reading (T2.1, T2.3).

The GRAIN v1.0 Zenodo record is one ~1.9 GB global zip. Rather than downloading
the whole archive on the critical path, the zip central directory is read with
HTTP range requests and only the Pakistan GeoParquet member is fetched. Python's
``zipfile`` verifies the member's CRC-32 while decompressing; the archive-level
MD5 published by Zenodo cannot be verified from a partial read and is recorded
as such.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

import httpx

from ..common import USER_AGENT, IngestionError

ZENODO_RECORD_API = "https://zenodo.org/api/records/16786488"
ZIP_URL = "https://zenodo.org/records/16786488/files/GRAIN_v.1.0.zip?download=1"
PAKISTAN_MEMBER = "GRAIN_v.1.0/GeoParquet/pakistan_GRAIN_v.1.0.parquet"
LICENSE_ID = "CC-BY-4.0"
CITATION = "GRAIN v1.0 (UW-SASWE), Zenodo doi:10.5281/zenodo.16786488"


class _HttpRangeFile(io.RawIOBase):
    def __init__(self, url: str, client: httpx.Client):
        self.url, self.client, self.pos = url, client, 0
        h = client.head(url)
        if h.status_code >= 400:
            raise IngestionError(f"{url}: HTTP {h.status_code}")
        self.size = int(h.headers["content-length"])
        self.requests = 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def readinto(self, b) -> int:
        if self.pos >= self.size:
            return 0
        end = min(self.size, self.pos + len(b)) - 1
        r = self.client.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        self.requests += 1
        if r.status_code != 206:
            raise IngestionError(f"range request not honoured (HTTP {r.status_code})")
        data = r.content
        b[: len(data)] = data
        self.pos += len(data)
        return len(data)


@dataclass
class MemberFetch:
    member: str
    content: bytes
    archive_size: int
    compress_size: int
    file_size: int
    crc32: str
    listing: list[str]
    range_requests: int


def fetch_member(url: str = ZIP_URL, member: str = PAKISTAN_MEMBER) -> MemberFetch:
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": USER_AGENT}) as c:
        raw = _HttpRangeFile(url, c)
        z = zipfile.ZipFile(io.BufferedReader(raw, 1 << 20))
        names = z.namelist()
        if member not in names:
            raise IngestionError(f"{member} not in GRAIN archive listing ({len(names)} entries)")
        info = z.getinfo(member)
        content = z.read(member)  # CRC-32 checked by zipfile; raises BadZipFile on mismatch
        return MemberFetch(
            member=member,
            content=content,
            archive_size=raw.size,
            compress_size=info.compress_size,
            file_size=info.file_size,
            crc32=f"{info.CRC:08x}",
            listing=[n for n in names if "pakistan" in n.lower()],
            range_requests=raw.requests,
        )


def read_subset(parquet_path, bbox: tuple[float, float, float, float]):
    """Read GRAIN GeoParquet, assert CRS, clip to bbox, return EPSG:4326 GeoDataFrame."""
    import geopandas as gpd  # noqa: PLC0415

    gdf = gpd.read_parquet(parquet_path)
    if gdf.crs is None:
        raise IngestionError("GRAIN GeoParquet has no CRS")
    gdf = gdf.to_crs("EPSG:4326")
    west, south, east, north = bbox
    return gdf.cx[west:east, south:north].copy()


def schema_summary(gdf) -> dict:
    cats = {}
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        if gdf[col].dtype == object and gdf[col].nunique() <= 30:
            cats[col] = sorted(str(v) for v in gdf[col].dropna().unique())
    return {
        "columns": [str(c) for c in gdf.columns],
        "dtypes": {str(c): str(t) for c, t in gdf.dtypes.items()},
        "crs": str(gdf.crs),
        "rows": int(len(gdf)),
        "categorical_values": cats,
    }


def id_column(gdf) -> str:
    for cand in ("GRAIN_ID", "grain_id", "canal_id", "ID", "id", "fid", "FID"):
        if cand in gdf.columns:
            return cand
    raise IngestionError(f"no identifier column in GRAIN schema: {list(gdf.columns)}")
