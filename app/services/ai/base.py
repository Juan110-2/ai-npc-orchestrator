from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generator


@dataclass
class AIResponse:
    """
    Resultado estandarizado de cualquier llamada a un proveedor de IA.
    Encapsula contenido, métricas de consumo y trazabilidad de proveedor.
    """
    content: str
    provider: str
    