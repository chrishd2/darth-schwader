from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from darth_schwader.quant.features import Features


@dataclass(frozen=True, slots=True)
class DirectionSignal:
    direction: str
    confidence: Decimal


class DirectionPredictor(Protocol):
    def predict(self, features: Features) -> DirectionSignal:
        ...


class NullDirectionPredictor:
    def predict(self, features: Features) -> DirectionSignal:
        return DirectionSignal(direction="neutral", confidence=Decimal("0.5"))


__all__ = ["DirectionPredictor", "DirectionSignal", "NullDirectionPredictor"]
