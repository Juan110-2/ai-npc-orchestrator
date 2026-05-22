r"""
Generador de sesiones clínicas multi-turno para benchmark 2×N.

Ejecuta N sesiones completas cruzando dos arquetipos de trainee
(empático / confrontativo) con los proveedores NPC configurados
(openai, gemini, deepseek). El trainee siempre es Gemini.

Por cada combinación:
- Se genera una conversación completa de M turnos con historial acumulado.
- Las llamadas del NPC quedan registradas en ai_call_logs.
- El transcript se exporta a JSON en scripts/transcripts/.

Al final se imprime:
- Resumen local por sesión.
- Resumen agregado por arquetipo.
- Resumen DB filtrado por benchmark_tag (v_provider_metrics).

Ejecución (desde la raíz del proyecto, con .venv activo):
    # Corrida completa (2 arquetipos × 3 NPC = 6 sesiones, 5 turnos c/u)
    python scripts/generate_clinical_sessions_2x1.py

    # Parámetros personalizados
    python scripts/generate_clinical_sessions_2x1.py --turns 8 --benchmark-tag bench_v2
    python scripts/generate_clinical_sessions_2x1.py --archetypes empatico --npc-providers openai gemini
    python scripts/generate_clinical_sessions_2x1.py --workers 2 --turns 10

Notas:
- Los clientes AI son singletons (lru_cache por proveedor). Las llamadas HTTP
  son I/O-bound y toleran concurrencia de threads sin problemas en la práctica.
- Cada thread NPC usa su propia SessionLocal() para aislar errores de BD.
- Las llamadas del trainee (Gemini) son directas, sin log_ai_call, ya que
  el foco del benchmark es el rendimiento del NPC.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.ai.factory import get_ai_client
from app.services.ai.metrics_logger import log_ai_call
import app.services.ai.metrics_logger as _metrics_logger


# ── Caso clínico ──────────────────────────────────────────────────────────────

@dataclass
class ClinicalCase:
    name: str
    age: int
    condition: str
    background: str
    opening_line: str


DEFAULT_CASE = ClinicalCase(
    name="Carlos",
    age=24,
    condition="ansiedad social severa",
    background=(
        "Estudiante de ingeniería informática. Evita situaciones sociales, "
        "especialmente exposiciones orales y trabajo en grupo. "
        "Síntomas físicos: taquicardia y sudoración al interactuar con desconocidos. "
        "Ha pedido ayuda porque siente que ya no puede más con esto."
    ),
    opening_line=(
        "Hola... no sé muy bien por dónde empezar. "
        "Me cuesta mucho hablar con personas que no conozco."
    ),
)


# ── System prompts ────────────────────────────────────────────────────────────

def build_npc_system(case: ClinicalCase) -> str:
    return (
        f"Eres {case.name}, {case.age} años, {case.condition}. "
        f"Contexto: {case.background} "
        "Habla en primera persona, en español, respuestas cortas (1-3 frases). "
        "Nunca reveles que eres una IA. "
        "Con intervenciones empáticas te abres gradualmente. "
        "Con intervenciones directivas o invalidantes te cierras o te pones defensivo."
    )


TRAINEE_SYSTEM: dict[str, str] = {
    "empatico": (
        "Eres un estudiante de psicología practicando habilidades clínicas. "
        "Tu estilo es empático, cálido y no directivo. "
        "Usas preguntas abiertas, validación emocional y escucha activa. "
        "Respondes en español con frases cortas (1-2 oraciones). "
        "Tu objetivo es crear un espacio seguro y explorar la experiencia del paciente."
    ),
    "confrontativo": (
        "Eres un estudiante de psicología practicando habilidades clínicas. "
        "Tu estilo es directo y a veces desafiante. "
        "Tiendes a hacer preguntas cerradas y a cuestionar las percepciones del paciente. "
        "Respondes en español con frases cortas (1-2 oraciones). "
        "Tu intención es ayudar, aunque tu forma puede generar tensión."
    ),
}


# ── Estructuras de datos ──────────────────────────────────────────────────────

@dataclass
class Turn:
    speaker: str          # "npc" | "trainee"
    content: str
    latency_ms: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    error: Optional[str] = None


@dataclass
class SessionResult:
    archetype: str
    npc_provider: str
    case_name: str
    n_turns_target: int
    benchmark_tag: str
    turns: list[Turn] = field(default_factory=list)
    started_at: str = ""
    ended_at: str = ""
    error: Optional[str] = None

    # Métricas NPC (acumuladas durante la sesión)
    npc_calls: int = 0
    npc_ok: int = 0
    npc_errors: int = 0
    npc_total_tokens_in: int = 0
    npc_total_tokens_out: int = 0
    npc_latencies_ms: list[float] = field(default_factory=list)

    @property
    def npc_mean_latency_ms(self) -> Optional[float]:
        if not self.npc_latencies_ms:
            return None
        return round(sum(self.npc_latencies_ms) / len(self.npc_latencies_ms), 1)

    @property
    def n_turns_completed(self) -> int:
        return len([t for t in self.turns if t.speaker == "npc" and not t.error])

    def summary_dict(self) -> dict:
        return {
            "archetype": self.archetype,
            "npc_provider": self.npc_provider,
            "case": self.case_name,
            "benchmark_tag": self.benchmark_tag,
            "n_turns_target": self.n_turns_target,
            "n_turns_completed": self.n_turns_completed,
            "npc_calls": self.npc_calls,
            "npc_ok": self.npc_ok,
            "npc_errors": self.npc_errors,
            "npc_mean_latency_ms": self.npc_mean_latency_ms,
            "npc_total_tokens_in": self.npc_total_tokens_in,
            "npc_total_tokens_out": self.npc_total_tokens_out,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
        }


# ── Construcción de contexto ──────────────────────────────────────────────────

def _build_context(history: list[Turn], perspective: str) -> list[dict]:
    """
    Convierte el historial de turnos en context_messages para el API de chat.

    perspective="npc":     trainee=user, npc=assistant
    perspective="trainee": npc=user,     trainee=assistant

    El último mensaje del historial se pasa como user_prompt en generate_response,
    así que el caller debe usar esta lista sin el último elemento.
    """
    result = []
    for turn in history:
        if perspective == "npc":
            role = "user" if turn.speaker == "trainee" else "assistant"
        else:
            role = "user" if turn.speaker == "npc" else "assistant"
        result.append({"role": role, "content": turn.content})
    return result


# ── Lógica de una sesión ──────────────────────────────────────────────────────

def run_clinical_session(
    archetype: str,
    npc_provider: str,
    case: ClinicalCase,
    n_turns: int,
    benchmark_tag: str,
    trainee_client,
) -> SessionResult:
    """
    Ejecuta una sesión multi-turno completa.
    El trainee (Gemini) genera intervenciones; el NPC (npc_provider) responde.
    Las llamadas NPC se persisten en ai_call_logs con purpose=benchmark_tag.
    """
    result = SessionResult(
        archetype=archetype,
        npc_provider=npc_provider,
        case_name=case.name,
        n_turns_target=n_turns,
        benchmark_tag=benchmark_tag,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    history: list[Turn] = []
    npc_sys = build_npc_system(case)
    trainee_sys = TRAINEE_SYSTEM[archetype]

    # Turno 0: apertura del NPC (sin API call — es el mensaje inicial del caso)
    opening = Turn(speaker="npc", content=case.opening_line)
    history.append(opening)
    result.turns.append(opening)

    try:
        for turn_n in range(n_turns):
            # ── Trainee responde (sin log — siempre Gemini, no es lo que benchmarkeamos) ──
            trainee_ctx = _build_context(history, perspective="trainee")
            last_npc_content = history[-1].content
            trainee_turn = Turn(speaker="trainee", content="")
            try:
                trainee_resp = trainee_client.generate_response(
                    trainee_sys,
                    last_npc_content,
                    context_messages=trainee_ctx[:-1] or None,
                )
                trainee_turn.content = trainee_resp.content or ""
                trainee_turn.latency_ms = trainee_resp.latency_ms
                trainee_turn.tokens_input = trainee_resp.tokens_input
                trainee_turn.tokens_output = trainee_resp.tokens_output
            except BaseException as e:
                trainee_turn.content = "[trainee sin respuesta]"
                trainee_turn.error = f"{type(e).__name__}: {str(e)[:200]}"
                print(
                    f"  [{archetype}/{npc_provider}] turno {turn_n+1}/{n_turns} "
                    f"trainee ERROR: {trainee_turn.error[:80]}"
                )

            history.append(trainee_turn)
            result.turns.append(trainee_turn)

            # ── NPC responde (con log_ai_call, sesion BD propia) ──────────────────────
            npc_ctx = _build_context(history, perspective="npc")
            last_trainee_content = trainee_turn.content
            npc_turn = Turn(speaker="npc", content="[npc sin respuesta]")
            result.npc_calls += 1

            db = SessionLocal()
            try:
                with log_ai_call(
                    db,
                    purpose=benchmark_tag,
                    provider_override=npc_provider,
                ) as ctx:
                    ctx.record_prompt_chars(len(npc_sys) + len(last_trainee_content))
                    try:
                        npc_resp = ctx.client.generate_response(
                            npc_sys,
                            last_trainee_content,
                            context_messages=npc_ctx[:-1] or None,
                        )
                        ctx.record_response(npc_resp)
                        npc_turn.content = npc_resp.content or ""
                        npc_turn.latency_ms = npc_resp.latency_ms
                        npc_turn.tokens_input = npc_resp.tokens_input
                        npc_turn.tokens_output = npc_resp.tokens_output
                        result.npc_ok += 1
                        result.npc_latencies_ms.append(npc_resp.latency_ms)
                        result.npc_total_tokens_in += npc_resp.tokens_input
                        result.npc_total_tokens_out += npc_resp.tokens_output
                    except BaseException as e:
                        npc_turn.error = f"{type(e).__name__}: {str(e)[:200]}"
                        result.npc_errors += 1
                        raise  # log_ai_call registra el error y re-lanza
            except BaseException:
                pass  # error ya registrado en npc_turn.error
            finally:
                try:
                    db.close()
                except Exception:
                    pass

            history.append(npc_turn)
            result.turns.append(npc_turn)

            t_lat = f"{trainee_turn.latency_ms:.0f}ms" if not trainee_turn.error else "ERR"
            n_lat = f"{npc_turn.latency_ms:.0f}ms" if not npc_turn.error else "ERR"
            print(
                f"  [{archetype}/{npc_provider}] turno {turn_n+1}/{n_turns} "
                f"trainee={t_lat} npc={n_lat}"
            )

    except BaseException as e:
        result.error = f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        result.ended_at = datetime.now(timezone.utc).isoformat()

    return result


# ── Export ────────────────────────────────────────────────────────────────────

def export_transcript(result: SessionResult, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"session_{result.archetype}_{result.npc_provider}_{ts}.json"
    path = output_dir / filename
    payload = {
        "meta": result.summary_dict(),
        "transcript": [
            {
                "speaker": t.speaker,
                "content": t.content,
                "latency_ms": t.latency_ms,
                "tokens_in": t.tokens_input,
                "tokens_out": t.tokens_output,
                "error": t.error,
            }
            for t in result.turns
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_jsonl(results: list[SessionResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"all_sessions_{ts}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in results:
            record = {
                **r.summary_dict(),
                "transcript": [
                    {"speaker": t.speaker, "content": t.content}
                    for t in r.turns
                ],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def export_csv(results: list[SessionResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"metrics_{ts}.csv"
    rows = [r.summary_dict() for r in results]
    if not rows:
        return path
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


# ── Resúmenes ─────────────────────────────────────────────────────────────────

def print_local_summary(results: list[SessionResult]) -> None:
    print("\n========== RESUMEN LOCAL (por sesión) ==========")
    headers = [
        "archetype", "npc_provider", "n_turns_completed",
        "npc_ok", "npc_errors", "npc_mean_latency_ms",
    ]
    col = 22
    print(" | ".join(h.ljust(col) for h in headers))
    print("-" * ((col + 3) * len(headers)))
    for r in results:
        d = r.summary_dict()
        print(" | ".join(str(d.get(h) or "-").ljust(col) for h in headers))


def print_archetype_summary(results: list[SessionResult]) -> None:
    print("\n========== RESUMEN POR ARQUETIPO ==========")
    by_arch: dict[str, list[SessionResult]] = {}
    for r in results:
        by_arch.setdefault(r.archetype, []).append(r)
    for arch, sessions in sorted(by_arch.items()):
        total_ok = sum(s.npc_ok for s in sessions)
        total_err = sum(s.npc_errors for s in sessions)
        all_lat = [lat for s in sessions for lat in s.npc_latencies_ms]
        mean_lat = f"{sum(all_lat) / len(all_lat):.1f}ms" if all_lat else "-"
        total_tok_out = sum(s.npc_total_tokens_out for s in sessions)
        print(
            f"  {arch:<16} npc_ok={total_ok}  npc_errors={total_err}  "
            f"mean_latency={mean_lat}  total_tokens_out={total_tok_out}"
        )


def print_db_summary(benchmark_tag: str) -> None:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            select provider, model,
                   n_calls, n_ok, n_errors,
                   round(success_rate_pct::numeric, 1) as success_rate_pct,
                   round(p50_latency_ms::numeric, 0) as p50_ms,
                   round(p95_latency_ms::numeric, 0) as p95_ms,
                   round(mean_tokens_input::numeric, 0) as mean_in,
                   round(mean_tokens_output::numeric, 0) as mean_out,
                   round(coalesce(total_cost_usd, 0)::numeric, 6) as cost_usd
            from public.v_provider_metrics
            where purpose = :tag
            order by provider, model
        """), {"tag": benchmark_tag}).mappings().all()
    except Exception as e:
        print(f"[db_summary] ERROR al consultar v_provider_metrics: {e}")
        return
    finally:
        db.close()

    print(f"\n========== RESUMEN DB (purpose={benchmark_tag!r}) ==========")
    if not rows:
        print("(sin datos en v_provider_metrics para este tag.)")
        return
    headers = list(rows[0].keys())
    print(" | ".join(h.ljust(14) for h in headers))
    print("-" * (17 * len(headers)))
    for r in rows:
        print(" | ".join(str(r[h] if r[h] is not None else "-").ljust(14) for h in headers))


# ── Runner ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera sesiones clínicas multi-turno. Trainee=Gemini, NPC rotante."
    )
    parser.add_argument(
        "--archetypes", nargs="+",
        default=["empatico", "confrontativo"],
        choices=["empatico", "confrontativo"],
        help="Arquetipos de trainee a correr (default: ambos).",
    )
    parser.add_argument(
        "--npc-providers", nargs="+",
        default=["openai", "gemini", "deepseek"],
        help="Proveedores NPC (default: openai gemini deepseek).",
    )
    parser.add_argument(
        "--turns", type=int, default=5,
        help="Turnos por sesión, sin contar la apertura del NPC (default: 5).",
    )
    parser.add_argument(
        "--benchmark-tag", default="bench_v2", metavar="TAG",
        help='Tag para log_ai_call purpose y resumen DB (default: "bench_v2").',
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Hilos concurrentes (default: total de sesiones = archetypes × providers).",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(_PROJECT_ROOT, "scripts", "transcripts"),
        help="Directorio de salida para transcripts y métricas.",
    )
    args = parser.parse_args()

    # Registrar purpose custom antes de cualquier llamada
    _metrics_logger.ALLOWED_PURPOSES.add(args.benchmark_tag)

    output_dir = Path(args.output_dir)
    trainee_client = get_ai_client("gemini")

    session_configs = [
        (arch, prov)
        for arch in args.archetypes
        for prov in args.npc_providers
    ]
    workers = args.workers or len(session_configs)

    print(
        f"[clinical_sessions] tag={args.benchmark_tag!r}  "
        f"archetypes={args.archetypes}  npc={args.npc_providers}  "
        f"turns={args.turns}  sessions={len(session_configs)}  workers={workers}"
    )
    print(f"[clinical_sessions] output -> {output_dir}")

    results: list[SessionResult] = []
    results_lock = threading.Lock()

    def _run_session(arch: str, prov: str) -> SessionResult:
        print(f"\n=== SESIÓN {arch}/{prov} iniciando ===")
        r = run_clinical_session(
            archetype=arch,
            npc_provider=prov,
            case=DEFAULT_CASE,
            n_turns=args.turns,
            benchmark_tag=args.benchmark_tag,
            trainee_client=trainee_client,
        )
        path = export_transcript(r, output_dir)
        print(f"=== SESIÓN {arch}/{prov} completa -> {path.name} ===")
        return r

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_run_session, arch, prov): (arch, prov)
            for arch, prov in session_configs
        }
        for fut in as_completed(futures):
            arch, prov = futures[fut]
            try:
                r = fut.result()
                with results_lock:
                    results.append(r)
            except Exception as e:
                print(f"[ERROR] sesión {arch}/{prov}: {type(e).__name__}: {e}")

    # Export agregados
    if results:
        jsonl_path = export_jsonl(results, output_dir)
        csv_path = export_csv(results, output_dir)
        print(f"\n[export] JSONL -> {jsonl_path}")
        print(f"[export] CSV   -> {csv_path}")

    print_local_summary(results)
    print_archetype_summary(results)
    print_db_summary(args.benchmark_tag)


if __name__ == "__main__":
    main()
