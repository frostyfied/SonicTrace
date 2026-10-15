"""Sound event classification module."""

from src.event_classification.classifier import SoundClassifier
from src.event_classification.features import extract_acoustic_features
from src.event_classification.types import AcousticFeatures, SoundType

__all__ = [
    "SoundClassifier",
    "extract_acoustic_features",
    "AcousticFeatures",
    "SoundType",
]
