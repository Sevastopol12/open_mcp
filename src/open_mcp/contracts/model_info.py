from typing import Annotated, Any

from pydantic import BaseModel, Field, computed_field


class ModelCompatibility(BaseModel):
    reasoningField: Annotated[
        str | None,
        Field(default=None, description="Provider-specific reasoning output field"),
    ]


class ModelCapabilities(BaseModel):
    tools: Annotated[
        bool,
        Field(description="Whether the model supports tool calling"),
    ]
    input: Annotated[
        list[str],
        Field(
            description="Supported input modalities. Ex: text, image, video, audio, pdf"
        ),
    ]
    output: Annotated[
        list[str],
        Field(description="Supported output modalities. Ex: text, image, audio"),
    ]
    temperature: Annotated[
        bool,
        Field(description="Whether the model supports temperature configuration"),
    ]


class ModelVariant(BaseModel):
    id: Annotated[
        str,
        Field(description="Variant identifier. Ex: low, medium, high, xhigh, max"),
    ]
    settings: Annotated[
        dict[str, Any],
        Field(description="Provider-specific settings for this reasoning variant"),
    ]


class ModelCostCache(BaseModel):
    read: Annotated[
        float,
        Field(description="Cache read cost"),
    ]
    write: Annotated[
        float,
        Field(description="Cache write cost"),
    ]


class ModelCostTier(BaseModel):
    type: Annotated[
        str,
        Field(description="Tier classification. Ex: context"),
    ]
    size: Annotated[
        int,
        Field(description="Context size associated with this pricing tier"),
    ]


class ModelCost(BaseModel):
    tier: Annotated[
        ModelCostTier | None,
        Field(default=None, description="Optional pricing tier"),
    ]
    input: Annotated[
        float,
        Field(description="Input token cost"),
    ]
    output: Annotated[
        float,
        Field(description="Output token cost"),
    ]
    cache: Annotated[
        ModelCostCache,
        Field(description="Cache pricing information"),
    ]


class ModelTime(BaseModel):
    released: Annotated[
        int,
        Field(description="Model release timestamp in Unix milliseconds"),
    ]


class ModelLimit(BaseModel):
    context: Annotated[
        int,
        Field(description="Maximum context window size"),
    ]
    input: Annotated[
        int | None,
        Field(default=None, description="Maximum input token limit"),
    ]
    output: Annotated[
        int,
        Field(description="Maximum output token limit"),
    ]


class ModelInfo(BaseModel):
    id: Annotated[
        str,
        Field(description="Unique model identifier"),
    ]
    modelID: Annotated[
        str,
        Field(description="Model identifier used by the provider"),
    ]
    providerID: Annotated[
        str,
        Field(description="Model provider identifier"),
    ]
    type: Annotated[
        str,
        Field(description="Model type. Ex: chat, decision, image, string"),
    ]
    name: Annotated[
        str,
        Field(description="Human-readable model name"),
    ]
    compatibility: Annotated[
        ModelCompatibility | None,
        Field(default=None, description="Provider compatibility configuration"),
    ]
    package: Annotated[
        str,
        Field(description="Provider integration package"),
    ]
    headers: Annotated[
        dict[str, str] | None,
        Field(
            default=None, description="Additional HTTP headers for provider requests"
        ),
    ]
    capabilities: Annotated[
        ModelCapabilities,
        Field(
            description=(
                "Model capabilities, including tools, modalities, and temperature"
            )
        ),
    ]
    variants: Annotated[
        list[ModelVariant],
        Field(description="Available reasoning or model configuration variants"),
    ]
    time: Annotated[
        ModelTime,
        Field(description="Model release information"),
    ]
    cost: Annotated[
        list[ModelCost],
        Field(
            description=(
                "Model pricing information, potentially with multiple pricing tiers"
            )
        ),
    ]
    status: Annotated[
        str,
        Field(description="Model availability status. Ex: active, beta, deprecated"),
    ]
    enabled: Annotated[
        bool,
        Field(description="Whether the model is enabled"),
    ]
    limit: Annotated[
        ModelLimit,
        Field(description="Model token limits"),
    ]

    @computed_field
    @property
    def free_tier_available(self) -> bool:
        for model_cost in self.cost:
            if (
                model_cost.input == 0
                and model_cost.output == 0
                and model_cost.cache.read == 0
                and model_cost.cache.write == 0
            ):
                return True
        return False
