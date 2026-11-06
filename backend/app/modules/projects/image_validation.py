"""Bounded decoding of untrusted project images, without rewriting their bytes."""
from io import BytesIO

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_FRAMES = 100
MAX_TOTAL_FRAME_PIXELS = 80_000_000
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class ImageValidationError(ValueError):
    """A readable failure, safe to show without decoder or filesystem internals."""


def validate_image(content: bytes, mime_type: str) -> None:
    expected = FORMATS.get(mime_type)
    if not expected:
        raise ImageValidationError("Use a JPG, PNG, or WEBP image.")
    try:
        # open() is lazy. Verify the container, then reopen and decode every
        # frame; magic bytes or verify() alone do not prove decodable pixels.
        with Image.open(BytesIO(content), formats=[expected]) as image:
            _check_dimensions(image.size)
            image.verify()
        with Image.open(BytesIO(content), formats=[expected]) as image:
            frames = getattr(image, "n_frames", 1)
            if frames > MAX_IMAGE_FRAMES or frames * image.width * image.height > MAX_TOTAL_FRAME_PIXELS:
                raise ImageValidationError("This image has too many frames or is too large. Use a smaller or static image.")
            total = 0
            for index in range(frames):
                image.seek(index)
                _check_dimensions(image.size)
                total += image.width * image.height
                if total > MAX_TOTAL_FRAME_PIXELS:
                    raise ImageValidationError("This image is too large. Use a smaller or static image.")
                image.load()
    except Image.DecompressionBombError as exc:
        raise ImageValidationError("Image dimensions are too large. Resize the image to at most 40 megapixels.") from exc
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, EOFError, ValueError) as exc:
        raise ImageValidationError("The image is damaged, incomplete, or does not match its file type. Upload a valid JPG, PNG, or WEBP image.") from exc


def _check_dimensions(size: tuple[int, int]) -> None:
    width, height = size
    if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
        raise ImageValidationError("Image dimensions are too large. Resize the image to at most 40 megapixels.")
