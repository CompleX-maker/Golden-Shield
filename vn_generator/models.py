from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from enum import Enum

class SequenceType(str, Enum):
    NARRATION = "narration"
    DIALOGUE = "dialogue"
    CHOICE = "choice"
    TRANSITION = "transition"

class Character(BaseModel):
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str
    default_expression: str = "neutral"
    expressions: List[str] = Field(default_factory=lambda: ["neutral"])
    text_color: Optional[str] = None  # Hex color

class Background(BaseModel):
    id: str
    description: str

class ChoiceOption(BaseModel):
    text: str
    jump_to: str
    set_variable: Optional[dict] = None  # {"name": "var", "value": True}

class Sequence(BaseModel):
    type: SequenceType
    # For narration
    text: Optional[str] = None
    # For dialogue
    character: Optional[str] = None
    expression: Optional[str] = None
    # For choice
    options: Optional[List[ChoiceOption]] = None
    # For transition
    transition_type: Optional[Literal["fade", "dissolve", "cut"]] = None
    duration: Optional[float] = None

class Scene(BaseModel):
    id: str
    title: str
    background: str
    bgm: Optional[str] = None
    sfx: Optional[str] = None
    sequences: List[Sequence]

class Script(BaseModel):
    title: str
    metadata: dict
    characters: List[Character]
    backgrounds: List[Background]
    scenes: List[Scene]

class RenpyFile(BaseModel):
    path: str
    content: str

class GenerationResult(BaseModel):
    script: Script
    files: List[RenpyFile]
    assets_needed: List[dict]
    output_path: Optional[str] = None