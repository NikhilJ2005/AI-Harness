"""The interface the rest of the code uses to talk to a language model.

Stages depend on this small ``StructuredLLM`` protocol rather than on a concrete
client. That keeps the heavy ``litellm`` / ``instructor`` imports out of the
stage modules and, more importantly, lets tests pass in a simple fake client
with no network calls.
"""

from enum import Enum
from typing import Protocol, TypeVar

from pydantic import BaseModel


class ModelTier(str, Enum):
    """Which cost/quality tier of model to use for a request.

    Cheap models handle routine work; the premium tier is reserved for hard
    reasoning. The concrete model behind each tier is set in ``Settings``.
    """

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
        """Call the model and return an instance of ``response_model``."""
        ...
