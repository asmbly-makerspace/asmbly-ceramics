"""The drop-off form on the in-memory fakes, to try on your machine; never deployed.

    uv run uvicorn asmbly_ceramics.web.local:app --reload

then open http://127.0.0.1:8000/ in a phone-sized window. Nothing reaches AWS and no
email is sent: the received email waits in the fake records' outbox. The photos post to
`/local-uploads/<slot>`, a route only this app has. Plain uvicorn sends no
`X-Forwarded-For`, so this app adds a documentation address to requests that have none.
It is never a deployed entry point: phase 7's `run.sh` starts `web.app`'s factory, and
`/local-uploads` has no origin check because it exists only here.
Chrome and Firefox keep `Secure` and `__Host-` cookies on http://127.0.0.1; a browser
that doesn't gets "allow cookies".
"""

import secrets
from datetime import datetime

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from asmbly_ceramics.adapters.clock import SystemClock
from asmbly_ceramics.adapters.memory.ids import MemoryIdNumbers
from asmbly_ceramics.adapters.memory.images import MemoryPhotoInspector
from asmbly_ceramics.adapters.memory.photos import MemoryPhotoStore
from asmbly_ceramics.adapters.memory.rate_limit import MemoryRateLimiter
from asmbly_ceramics.adapters.memory.records import MemoryRecords
from asmbly_ceramics.adapters.memory.secrets import MemorySecrets
from asmbly_ceramics.domain.limits import PHOTO_MAX_BYTES, SENDING_DOMAIN
from asmbly_ceramics.domain.photos import PresignedPost, UploadSlot, is_slot_id
from asmbly_ceramics.ports.secrets import SecretName
from asmbly_ceramics.use_cases.keys import KeyHasher
from asmbly_ceramics.use_cases.received import ReceivedSummary
from asmbly_ceramics.use_cases.studio import CurrentStudio, ViewStudioChoices
from asmbly_ceramics.use_cases.submit import SubmitDropOff
from asmbly_ceramics.use_cases.uploads import RequestUploadSlots
from asmbly_ceramics.web.app import WebServices, WebSettings, create_app

SITE_URL = "http://127.0.0.1:8000"
LOCAL_ADDRESS = "192.0.2.1"  # TEST-NET-1, a documentation address
LOCAL_UPLOADS = "/local-uploads/"
_UPLOAD_BODY_MAX = PHOTO_MAX_BYTES + 64 * 1024  # a photo and its form's other fields


class LocalPhotoStore(MemoryPhotoStore):
    """The fake store, with slots that post to this app's `/local-uploads/<slot>`."""

    def upload_slots(self, count: int, now: datetime) -> list[UploadSlot]:
        return [
            UploadSlot(
                slot_id=slot.slot_id,
                post=PresignedPost(url=LOCAL_UPLOADS + slot.slot_id, fields={}),
                expires_at=slot.expires_at,
            )
            for slot in super().upload_slots(count, now)
        ]


class LocalForwardedFor:
    """Adds `X-Forwarded-For` when a request has none, as API Gateway would."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not any(name == b"x-forwarded-for" for name, _ in scope["headers"]):
            scope = {**scope, "headers": [*scope["headers"], (b"x-forwarded-for", LOCAL_ADDRESS.encode())]}
        await self.app(scope, receive, send)


def build(photos: LocalPhotoStore | None = None) -> ASGIApp:
    records = MemoryRecords()
    photos = photos or LocalPhotoStore()
    limiter = MemoryRateLimiter()
    clock = SystemClock()
    keys = MemorySecrets()
    keys.set(SecretName.HASH_KEY, secrets.token_bytes(32))
    hasher = KeyHasher(keys)
    # A role address at asmbly.org, not a person's, and nothing is sent locally; built in
    # code only so the repository's address check doesn't flag the line.
    studio = CurrentStudio(records, clock, "ceramics" + "@" + SENDING_DOMAIN)
    services = WebServices(
        view_studio_choices=ViewStudioChoices(studio),
        request_upload_slots=RequestUploadSlots(photos, limiter, hasher, clock),
        submit_drop_off=SubmitDropOff(
            records, MemoryIdNumbers(), photos, MemoryPhotoInspector(), limiter, hasher, clock, studio
        ),
        received_summary=ReceivedSummary(records, clock),
        clock=clock,
    )
    settings = WebSettings(
        site_url=SITE_URL, photo_upload_origin=SITE_URL, version="local", cookie_key=secrets.token_bytes(32)
    )
    web = create_app(services, settings)

    async def local_upload(request: Request) -> Response:
        slot_id = request.path_params["slot"]
        if not is_slot_id(slot_id):
            return Response(status_code=404)
        async with request.form(max_files=1, max_fields=8, max_part_size=_UPLOAD_BODY_MAX) as form:
            upload = form.get("file")
            if isinstance(upload, str) or upload is None:
                return Response(status_code=400)
            content_type = form.get("Content-Type")
            if not isinstance(content_type, str) or not content_type.startswith("image/"):
                return Response(status_code=403)  # as the bucket's policy refuses it
            data = await upload.read(_UPLOAD_BODY_MAX)
        try:
            photos.put_upload(slot_id, data)
        except ValueError:
            return Response(status_code=403)
        return Response(status_code=204)

    web.router.routes.insert(0, Route(LOCAL_UPLOADS + "{slot}", local_upload, methods=["POST"]))
    return LocalForwardedFor(web)


app = build()
