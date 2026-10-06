"""Strategy specification models."""

from pydantic import BaseModel, ConfigDict, Field
from atsits.models.types import FrozenMapping


class StrategySpec(BaseModel):
    """Represents a verified, machine-executable strategy specification.

    Acts as the explicit locked rule set. Parameter values and rules must be explicitly
    taught and verified by the Human Strategy Authority rather than assumed.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    strategy_id: str = Field(..., min_length=1, description="Unique identifier for the strategy specification")
    name: str = Field(..., min_length=1, description="Human-readable strategy name")
    version: str = Field(..., min_length=1, description="Strategy version string (e.g. 1.0.0)")
    description: str = Field(default="", description="Strategy description or summary")
    parameters: FrozenMapping = Field(
        default_factory=dict,
        description="Explicitly verified strategy parameters",
    )
    is_verified: bool = Field(
        default=False,
        description="Flag indicating whether this specification has received human verification",
    )
