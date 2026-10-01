"""Client für die SpeechMind GraphQL API v2.

Ablauf laut SpeechMind-Doku (https://www.speechmind.com/docs/introduction/):
  1. getUploadUrl(uniqueObjName)       -> presigned S3-POST (url + fields)
  2. Datei per multipart/form-data an diese URL senden
  3. initProtocol(...)                 -> Protokoll anlegen, Verarbeitung startet
  4. getResults(protocolSlug)          -> pollen bis creationDone
  5. getTextsegmentsByProtocolAndPage  -> Transkript seitenweise abholen
"""

import json
from pathlib import Path

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
UPLOAD_TIMEOUT = httpx.Timeout(1800.0, connect=30.0)


class SpeechMindError(Exception):
    pass


Q_PROJECTS = """
query GetAllProjects { getAllProjects { slug name } }
"""

M_CREATE_PROJECT = """
mutation CreateProject($name: String!) {
  createProject(name: $name) { project { slug name } }
}
"""

Q_UPLOAD_URL = """
query GetUploadUrl($uniqueObjName: String!) {
  getUploadUrl(uniqueObjName: $uniqueObjName) { url fields }
}
"""

M_INIT_PROTOCOL = """
mutation InitProtocol(
  $date: Date!
  $name: String!
  $agendaItemList: [AgendaItemListInput]
  $speakerList: [PersonInputList]
  $projectSlug: String!
  $language: String!
  $uniqueObjName: String!
  $typeOfDocument: String!
) {
  initProtocol(
    name: $name
    date: $date
    language: $language
    typeOfDocument: $typeOfDocument
    agendaItemList: $agendaItemList
    speakerList: $speakerList
    uniqueObjName: $uniqueObjName
    projectSlug: $projectSlug
  ) {
    success
    protocol { slug name status creatingStep }
  }
}
"""

Q_RESULTS = """
query GetResults($protocolSlug: String!) {
  getResults(protocolSlug: $protocolSlug) {
    creationDone
    protocol { slug name status creatingStep }
    agendaItemList {
      id
      title
      texts { depth name text hasBulletpoints }
      resolutionList { decision resolution }
    }
    taskItemList { id text date assignedTo done }
  }
}
"""

Q_TRANSCRIPT_PAGE = """
query GetTextsegmentsByProtocolAndPage($protocolSlug: String!, $page: Int!) {
  getTextsegmentsByProtocolAndPage(protocolSlug: $protocolSlug, page: $page) {
    textsegmentList {
      id
      pos
      speakerObj { slug givenName familyName }
      textJson { text startTime endTime }
    }
  }
}
"""


class SpeechMindClient:
    def __init__(self, api_url: str, api_key: str):
        if not api_key:
            raise SpeechMindError("Kein SpeechMind-API-Key hinterlegt.")
        self.api_url = api_url
        self.api_key = api_key

    async def _gql(self, query: str, variables: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            try:
                resp = await client.post(
                    self.api_url,
                    json={"query": query, "variables": variables or {}},
                    headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise SpeechMindError(f"SpeechMind nicht erreichbar: {exc}") from exc

        if resp.status_code in (401, 403):
            raise SpeechMindError("SpeechMind hat den API-Key abgelehnt.")
        if resp.status_code >= 400:
            raise SpeechMindError(f"SpeechMind antwortet mit HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise SpeechMindError("SpeechMind lieferte keine gültige JSON-Antwort.") from exc
        if body.get("errors"):
            messages = "; ".join(e.get("message", str(e)) for e in body["errors"])
            raise SpeechMindError(f"SpeechMind-Fehler: {messages}")
        return body.get("data") or {}

    # --- Projekte -----------------------------------------------------------

    async def list_projects(self) -> list[dict]:
        data = await self._gql(Q_PROJECTS)
        return data.get("getAllProjects") or []

    async def create_project(self, name: str) -> dict:
        data = await self._gql(M_CREATE_PROJECT, {"name": name})
        return (data.get("createProject") or {}).get("project") or {}

    # --- Upload & Protokoll -------------------------------------------------

    async def upload_file(self, unique_obj_name: str, path: Path, content_type: str = "audio/mpeg") -> None:
        data = await self._gql(Q_UPLOAD_URL, {"uniqueObjName": unique_obj_name})
        target = data.get("getUploadUrl") or {}
        url = target.get("url")
        fields = target.get("fields") or {}
        if isinstance(fields, str):
            fields = json.loads(fields)
        if not url:
            raise SpeechMindError("SpeechMind lieferte keine Upload-URL.")

        async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT) as client:
            with path.open("rb") as fh:
                # S3 verlangt, dass "file" das letzte Feld ist – httpx sendet data vor files.
                resp = await client.post(
                    url,
                    data={k: str(v) for k, v in fields.items()},
                    files={"file": (unique_obj_name, fh, content_type)},
                )
        if resp.status_code not in (200, 201, 204):
            raise SpeechMindError(f"Upload fehlgeschlagen (HTTP {resp.status_code}): {resp.text[:300]}")

    async def init_protocol(
        self,
        *,
        name: str,
        date: str,
        language: str,
        document_type: str,
        project_slug: str,
        unique_obj_name: str,
        speakers: list[dict] | None = None,
    ) -> str:
        variables = {
            "name": name,
            "date": date,
            "language": language,
            "typeOfDocument": document_type,
            "projectSlug": project_slug,
            "uniqueObjName": unique_obj_name,
            "agendaItemList": [],
            "speakerList": speakers or [],
        }
        data = await self._gql(M_INIT_PROTOCOL, variables)
        result = data.get("initProtocol") or {}
        protocol = result.get("protocol") or {}
        if not result.get("success") or not protocol.get("slug"):
            raise SpeechMindError("SpeechMind konnte das Protokoll nicht anlegen.")
        return protocol["slug"]

    # --- Ergebnisse ---------------------------------------------------------

    async def get_results(self, protocol_slug: str) -> dict:
        data = await self._gql(Q_RESULTS, {"protocolSlug": protocol_slug})
        return data.get("getResults") or {}

    async def get_transcript(self, protocol_slug: str, max_pages: int = 500) -> list[dict]:
        segments: list[dict] = []
        for page in range(1, max_pages + 1):
            data = await self._gql(Q_TRANSCRIPT_PAGE, {"protocolSlug": protocol_slug, "page": page})
            page_items = (data.get("getTextsegmentsByProtocolAndPage") or {}).get("textsegmentList") or []
            if not page_items:
                break
            segments.extend(page_items)
        return [_flatten_segment(s) for s in sorted(segments, key=lambda s: s.get("pos") or 0)]


def _flatten_segment(segment: dict) -> dict:
    speaker = segment.get("speakerObj") or {}
    name = " ".join(p for p in (speaker.get("givenName"), speaker.get("familyName")) if p).strip()
    parts = segment.get("textJson") or []
    if isinstance(parts, dict):
        parts = [parts]
    text = " ".join((p.get("text") or "").strip() for p in parts).strip()
    start = next((p.get("startTime") for p in parts if p.get("startTime") is not None), None)
    return {
        "speaker": name or speaker.get("slug") or "Unbekannt",
        "start": start,
        "text": text,
    }
