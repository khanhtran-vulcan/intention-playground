import pytest
from pydantic import ValidationError

from core.request import ImageAttachment, RouteRequest


def test_route_request_includes_attachment_context():
    request = RouteRequest(
        text="Describe this",
        images=[
            ImageAttachment(
                name="image.png",
                mime_type="image/png",
                data=b"small-image",
            )
        ],
    )

    assert request.has_images
    assert request.image_count == 1
    assert request.classification_text().startswith("An image is attached")


def test_rejects_unsupported_image_type():
    with pytest.raises(ValidationError, match="unsupported image type"):
        ImageAttachment(name="image.gif", mime_type="image/gif", data=b"gif")


def test_rejects_image_over_10_mb():
    with pytest.raises(ValidationError, match="10 MB"):
        ImageAttachment(
            name="large.png",
            mime_type="image/png",
            data=b"x" * (10 * 1024 * 1024 + 1),
        )
