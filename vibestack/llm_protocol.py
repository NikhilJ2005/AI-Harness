"""The interface the rest of the code uses to talk to a language model."""

from enum import Enum
from typing import Protocol, TypeVar

from pydantic import BaseModel


class ModelTier(str, Enum):
    """Cost/quality tier; the model behind each is set in Settings."""

    CHEAP = "cheap"
    MID = "mid"
    PREMIUM = "premium"


# A type variable bound to Pydantic models, so ``structured_completion`` returns
# the same model type that the caller requested.
ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class StructuredLLM(Protocol):
    """Anything that can turn a prompt into a validated Pydantic object."""

    def structured_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT],
        tier: ModelTier = ModelTier.MID,
    ) -> ResponseModelT:
        ...
