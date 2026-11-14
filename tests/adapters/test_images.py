"""`PillowPhotoInspector`, with images made in memory (none is committed)."""

from io import BytesIO

import pytest
from PIL import Image

from asmbly_ceramics.adapters import images
from asmbly_ceramics.adapters.images import PillowPhotoInspector
from asmbly_ceramics.domain.limits import PHOTO_FULL_LONG_SIDE, PHOTO_MAX_BYTES, PHOTO_THUMB_LONG_SIDE
from asmbly_ceramics.domain.photos import PhotoRefusal
from asmbly_ceramics.ports.images import PhotoRefused

GPS_IFD = 0x8825
ORIENTATION = 0x0112
SOFTWARE = 0x0131


def an_image(fmt: str, size: tuple[int, int] = (64, 48), mode: str = "RGB", **save: object) -> bytes:
    image = Image.new(mode, size, (200, 30, 30) if mode == "RGB" else (200, 30, 30, 128))
    out = BytesIO()
    image.save(out, format=fmt, **save)
    return out.getvalue()


def a_jpeg_with_gps_and_orientation(orientation: int = 1, size: tuple[int, int] = (64, 48)) -> bytes:
    image = Image.new("RGB", size)
    for x in range(size[0] // 2):  # the left half white, so turning it shows
        for y in range(size[1]):
            image.putpixel((x, y), (255, 255, 255))
    exif = Image.Exif()
    exif[ORIENTATION] = orientation
    exif[SOFTWARE] = "Made-up camera"
    exif.get_ifd(GPS_IFD).update({1: "N", 2: (30.0, 16.0, 1.0), 3: "W", 4: (97.0, 44.0, 1.0)})
    out = BytesIO()
    image.save(out, format="JPEG", exif=exif, comment=b"made-up comment")
    return out.getvalue()


def segments(jpeg: bytes) -> set[int]:
    """The JPEG's marker segments before the image data (APP1 = 0xE1, COM = 0xFE)."""
    found: set[int] = set()
    at = 2
    while at < len(jpeg) - 4 and jpeg[at] == 0xFF:
        marker = jpeg[at + 1]
        found.add(marker)
        if marker == 0xDA:  # start of scan
            break
        at += 2 + int.from_bytes(jpeg[at + 2 : at + 4], "big")
    return found


def opened(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


@pytest.mark.parametrize(
    "data",
    [an_image("JPEG"), an_image("PNG"), an_image("PNG", mode="RGBA"), an_image("WEBP")],
    ids=["jpeg", "png", "png-alpha", "webp"],
)
def test_jpeg_png_and_webp_are_accepted_and_returned_as_jpeg(data: bytes) -> None:
    checked = PillowPhotoInspector().inspect(data)
    for copy in (checked.full, checked.thumb):
        with opened(copy) as image:
            assert image.format == "JPEG"
            assert image.mode == "RGB"


def test_gps_exif_is_gone_after_inspection() -> None:
    source = a_jpeg_with_gps_and_orientation()
    with opened(source) as image:
        assert image.getexif().get_ifd(GPS_IFD)  # the source has a location
    checked = PillowPhotoInspector().inspect(source)
    for copy in (checked.full, checked.thumb):
        with opened(copy) as image:
            assert not image.getexif()
            assert "exif" not in image.info
            assert "comment" not in image.info
        assert not {0xE1, 0xFE} & segments(copy)  # no APP1 (EXIF, XMP), no comment


def test_rotated_photo_is_turned_upright() -> None:
    # Orientation 6: the camera was turned; the stored 64x48 shows upright as 48x64.
    checked = PillowPhotoInspector().inspect(a_jpeg_with_gps_and_orientation(6))
    with opened(checked.full) as image:
        assert image.size == (48, 64)


def test_full_size_is_at_most_2048_and_thumbnail_320() -> None:
    checked = PillowPhotoInspector().inspect(an_image("PNG", size=(3000, 1500)))
    with opened(checked.full) as full, opened(checked.thumb) as thumb:
        assert full.size == (PHOTO_FULL_LONG_SIDE, 1024)
        assert thumb.size == (PHOTO_THUMB_LONG_SIDE, 160)
    small = PillowPhotoInspector().inspect(an_image("PNG", size=(100, 50)))
    with opened(small.full) as image:
        assert image.size == (100, 50)  # never made larger


def refusal(data: bytes) -> PhotoRefusal:
    with pytest.raises(PhotoRefused) as refused:
        PillowPhotoInspector().inspect(data)
    return refused.value.kind


def test_text_file_is_not_an_image() -> None:
    assert refusal(b"Hello, this is a text file pretending to be a photo.\n") is PhotoRefusal.NOT_IMAGE
    assert refusal(b"") is PhotoRefusal.NOT_IMAGE
    assert refusal(b"%PDF-1.7\n" + b"0" * 100) is PhotoRefusal.NOT_IMAGE


@pytest.mark.parametrize("brand", [b"heic", b"heix", b"mif1", b"avif"])
def test_heic_signature_is_unsupported_type(brand: bytes) -> None:
    header = b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00mif1heic"
    assert refusal(header + b"\x00" * 64) is PhotoRefusal.UNSUPPORTED_TYPE


def test_gif_is_unsupported_type() -> None:
    assert refusal(an_image("GIF")) is PhotoRefusal.UNSUPPORTED_TYPE


def test_a_type_pillow_could_open_but_isnt_allowed_is_not_an_image() -> None:
    assert refusal(an_image("BMP")) is PhotoRefusal.NOT_IMAGE  # `formats=` refuses it


def test_truncated_jpeg_is_not_an_image() -> None:
    whole = an_image("JPEG", size=(256, 256), quality=95)
    assert refusal(whole[: len(whole) // 2]) is PhotoRefusal.NOT_IMAGE


@pytest.mark.parametrize("size", [(15, 10), (20, 20)], ids=["warning", "error"])
def test_decompression_bomb_is_refused(monkeypatch: pytest.MonkeyPatch, size: tuple[int, int]) -> None:
    # Above MAX_IMAGE_PIXELS Pillow warns; above twice it refuses. Both are refused here.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    assert refusal(an_image("PNG", size=size)) is PhotoRefusal.TOO_MANY_PIXELS


def test_over_10_mb_is_refused_before_opening(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("opened")

    monkeypatch.setattr(Image, "open", never)
    assert refusal(b"\xff\xd8" + b"0" * PHOTO_MAX_BYTES) is PhotoRefusal.TOO_LARGE


@pytest.mark.parametrize("error", [IndexError("made-up"), KeyError("made-up"), ZeroDivisionError()])
def test_any_decoder_error_is_not_an_image(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(Image, "open", broken)
    with pytest.raises(PhotoRefused) as refused:
        PillowPhotoInspector().inspect(an_image("PNG"))
    assert refused.value.kind is PhotoRefusal.NOT_IMAGE
    assert refused.value.__suppress_context__


def test_more_than_max_pixels_is_refused_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "PHOTO_MAX_PIXELS", 64 * 48 - 1)
    assert refusal(an_image("PNG")) is PhotoRefusal.TOO_MANY_PIXELS
    monkeypatch.setattr(images, "PHOTO_MAX_PIXELS", 64 * 48)
    PillowPhotoInspector().inspect(an_image("PNG"))


def test_a_palette_png_with_transparency_lands_on_white() -> None:
    image = Image.new("P", (8, 8), 0)
    image.putpalette([0, 0, 0, 255, 0, 0])
    out = BytesIO()
    image.save(out, format="PNG", transparency=0)
    with opened(PillowPhotoInspector().inspect(out.getvalue()).full) as checked:
        r, g, b = checked.convert("RGB").getpixel((4, 4))  # type: ignore[misc]  # an RGB pixel is a 3-tuple; Pillow types it wider
        assert min(r, g, b) > 240
