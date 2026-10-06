"""Common immutable types and helpers for domain models."""

from types import MappingProxyType
from typing import Annotated, Any, Mapping
from pydantic import AfterValidator, PlainSerializer


def freeze_mapping(v: Any) -> MappingProxyType:
    """Recursively freeze mappings and dictionaries into read-only MappingProxyType views."""
    if not isinstance(v, (dict, MappingProxyType)):
        raise ValueError(f"Expected mapping, got {type(v).__name__}")
    return MappingProxyType(
        {
            k: freeze_mapping(val) if isinstance(val, (dict, MappingProxyType)) else val
            for k, val in v.items()
        }
    )


def unfreeze_mapping(v: Any) -> Any:
    """Recursively convert mapping proxies back to standard dictionaries for serialization."""
    if isinstance(v, (MappingProxyType, dict)):
        return {k: unfreeze_mapping(val) for k, val in v.items()}
    return v


# Immutable mapping type that prevents in-place mutation of dictionaries
FrozenMapping = Annotated[
    Mapping[str, Any],
    AfterValidator(freeze_mapping),
    PlainSerializer(unfreeze_mapping, return_type=dict),
]
