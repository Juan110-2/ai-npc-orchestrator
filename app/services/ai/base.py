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
    model: str
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output


@dataclass
class StreamResult:
    """
    Métricas finales que un stream debe entregar al consumidor cuando termina.
    Permite persistir tokens/latencia/TTFT también en el camino streaming.
    """
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: float = 0.0
    ttft_ms: float = 0.0  # time-to-first-token
    extra: dict = field(default_factory=dict)

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output


class AIClient(ABC):
    """
    Contrato que cualquier proveedor de IA debe cumplir.

    Todos los clientes deben implementar:
    - generate_response: llamada completa, devuelve AIResponse.
    - generate_stream: llamada en streaming, devuelve Generator de chunks str
      y, vía StopIteration.value, un StreamResult con métricas finales.

    Las subclases DEBEN definir los atributos de clase `provider` y `model`
    para permitir trazabilidad en streaming y logging de llamadas.
    """

    provider: str = "unknown"
    model: str = "unknown"

    @abstractmethod
    def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> AIResponse:
        """Llamada completa (no streaming). Devuelve AIResponse con métricas."""

    @abstractmethod
    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context_messages: list[dict[str, str]] | None = None,
    ) -> Generator[str, None, "StreamResult"]:
        """
        Llamada en streaming. Devuelve un generator que yield chunks de texto.
        El último valor del generator (StopIteration.value) es un StreamResult
        con métricas finales (tokens, latencia total, TTFT).
        """
