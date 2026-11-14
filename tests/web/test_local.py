"""`local.py`: the form on the fakes, whole, as a person tries it on their machine."""

import re

from starlette.testclient import TestClient

from asmbly_ceramics.web.local import SITE_URL, LocalPhotoStore, build
from tests.domain.builders import TEST_EMAIL, TEST_NAME, TEST_PHONE
from tests.web.conftest import PHOTO

ORIGIN = {"origin": SITE_URL}
# Browsers keep `Secure` cookies on http://127.0.0.1; the test client only over https.
BASE = SITE_URL.replace("http://", "https://")


def test_the_local_form_takes_a_drop_off_end_to_end() -> None:
    photos = LocalPhotoStore()
    with TestClient(build(photos), base_url=BASE) as client:
        page = client.get("/")
        assert page.status_code == 200
        token = re.search(r'name="submission" value="([^"]+)"', page.text)
        assert token is not None
        slots = client.post(
            "/drop-off/uploads", json={"count": 1, "submission": token.group(1)}, headers=ORIGIN
        )
        assert slots.status_code == 200
        [slot] = slots.json()["slots"]
        assert slot["url"] == "/local-uploads/" + slot["id"]
        refused = client.post(
            slot["url"], files={"file": ("p.jpg", PHOTO)}, data={"Content-Type": "text/plain"}
        )
        assert refused.status_code == 403
        posted = client.post(
            slot["url"], data={"Content-Type": "image/jpeg"}, files={"file": ("p.jpg", PHOTO)}
        )
        assert posted.status_code == 204
        answer = client.post(
            "/drop-off",
            data={
                "submission": token.group(1),
                "name": TEST_NAME,
                "email": TEST_EMAIL,
                "phone": TEST_PHONE,
                "pieces": "1",
                "firing_type": "bisque",
                "slot": slot["id"],
            },
            headers=ORIGIN,
        )
        assert answer.status_code == 200
        assert 'class="drop-off-id">AC-1<' in answer.text


def test_local_uploads_refuse_what_s3_would() -> None:
    with TestClient(build(), base_url=BASE) as client:
        assert client.post("/local-uploads/not-a-slot", files={"file": ("p", b"x")}).status_code == 404
        unknown = "A" * 22
        response = client.post(
            "/local-uploads/" + unknown, data={"Content-Type": "image/jpeg"}, files={"file": ("p", b"x")}
        )
        assert response.status_code == 403
        no_file = client.post("/local-uploads/" + unknown, data={"Content-Type": "image/jpeg"})
        assert no_file.status_code == 400
