from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGES = 1
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ImageAttachment(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(min_length=1, max_length=255)
    mime_type: str
    data: bytes = Field(repr=False)

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in ALLOWED_IMAGE_TYPES:
            raise ValueError(
                f"unsupported image type; expected one of {sorted(ALLOWED_IMAGE_TYPES)}"
            )
        return normalized

    @field_validator("data")
    @classmethod
    def validate_size(cls, value: bytes) -> bytes:
        if not value:
            raise ValueError("image cannot be empty")
        if len(value) > MAX_IMAGE_BYTES:
            raise ValueError("image cannot exceed 10 MB")
        return value


class RouteRequest(BaseModel):
    text: str = ""
    images: list[ImageAttachment] = Field(default_factory=list, max_length=MAX_IMAGES)
    image_count_hint: int = Field(default=0, ge=0, le=MAX_IMAGES)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_content(self) -> "RouteRequest":
        if not self.text and not self.has_images:
            raise ValueError("a request requires text or an image")
        return self

    @property
    def has_images(self) -> bool:
        return bool(self.images) or self.image_count_hint > 0

    @property
    def image_count(self) -> int:
        return max(len(self.images), self.image_count_hint)

    def classification_text(self) -> str:
        context = (
            "An image is attached to this message."
            if self.has_images
            else "No image is attached to this message."
        )
        return f"{context}\nUser message: {self.text}"
