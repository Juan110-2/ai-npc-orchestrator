r"""
Bench reproducible con tag configurable para comparaciones entre corridas.

Extensión mínima de bench_providers.py: misma lógica, mismos prompts, pero
el purpose que se escribe en ai_call_logs es configurable por CLI.

Esto permite correr el mismo benchmark bajo condiciones distintas
(nuevo modelo, nuevo prompt, nueva config) y comparar los resultados
contra el bench base sin mezclar datos.

Ejecución (desde la raiz del proyecto, con .venv activo):
    # Corrida base (equivalente a bench_providers.py)
    python scripts/bench_providers_tagged.py --benchmark-tag bench

    # Corrida con tag diferente para comparar
    python scripts/bench_providers_tagged.py --benchmark-tag bench_v2
    python scripts/bench_providers_tagged.py --benchmark-tag bench_gpt4o --providers openai

    # Subset de providers, más turnos
    python scripts/bench_providers_tagged.py --benchmark-tag bench_stress --turns 20 --providers openai gemini
"""
from __future__ import annotations

import os
import sys
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import json

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.ai.factory import get_ai_client
from app.services.ai.metrics_logger import log_ai_call
import app.services.ai.metrics_logger as _metrics_logger


# ── Prompts (idénticos al bench base) ────────────────────────────────────────

ORCHESTRATOR_SYSTEM = (
    "[ROL] Eres una persona que esta atravesando un momento emocional dificil. "
    "Responde como persona real, en primera persona, breve, en español. "
    "Maximo 2 frases. Nunca digas que eres una IA o paciente simulado."
)

ORCHESTRATOR_TURNS = [
    "Hola, cuentame como te has sentido hoy.",
    "Entiendo, debe ser dificil sostener todo eso solo.",
    "Y cuando te pasa eso, que haces normalmente?",
    "Lo que me cuentas tiene mucho sentido.",
    "Me parece muy valioso lo que estas haciendo al hablar de esto.",
    "Si algo te ayudara ahora, que crees que seria?",
    "No tienes que tener todo claro hoy. Vamos paso a paso.",
    "Que ha cambiado entre como te sentias antes y ahora?",
    "Cuentame mas sobre ese momento.",
    "Gracias por compartirlo. Eso es importante.",
]

CLASSIFIER_SYSTEM = (
    "Eres un clasificador de turnos para simulacion clinica. "
    "Clasifica el ultimo mensaje del trainee en EXACTAMENTE una categoria: "
    "supportive, indifferent, neutral, confusing, invalidating, inappropriate, risk. "
    "Responde SOLO JSON con esta forma: "
    '{"category":"...","confidence":0.0,"rationale":"breve"}'
)

CLASSIFIER_INPUTS = [
    "Te entiendo, debe ser muy duro lo que estas viviendo.",
    "Mira, deja de quejarte y supera eso ya.",
    "Hoy esta soleado, que clima.",
    "asdfgh sdf 1234 ?? .",
    "Eso no es para tanto, todos pasamos por cosas peores.",
    "Eres una basura y no mereces ayuda.",
    "A veces pienso en hacerme dano.",
]

EVALUATOR_SYSTEM = (
    "Eres un evaluador de intervenciones en formacion en psicologia. "
    "Devuelve SOLO JSON con: empathy_score (0-1), assertiveness_score (0-1), "
    "pressure_score (0-1), overall_impact (-1, 0 o 1)."
)

EVALUATOR_INPUTS = [
    "Te entiendo, debe ser muy duro.",
    "Tienes que dejar de pensar asi de una vez.",
    "Cuentame mas, te escucho.",
    "Eso es absurdo, supera ya eso.",
    "Lo que sientes tiene sentido.",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_json(text_value: str) -> bool:
    try:
        json.loads(text_value)
        return True
    except Exception:
        return False


def _run_single_call(
    provider: str,
    label: str,
    idx: int,
    total: int,
    system_prompt: str,
    user_input: str,
    *,
    expect_json: bool,
    benchmark_tag: str,
) -> None:
    """
    Ejecuta UNA llamada IA con su propia sesion BD.
    Cualquier error queda registrado como AICallLog con status='error_*'
    sin contaminar el resto del bench.
    """
    db = SessionLocal()
    try:
        with log_ai_call(db, purpose=benchmark_tag, provider_override=provider) as ctx:
            ctx.record_prompt_chars(len(system_prompt) + len(user_input))
            try:
                resp = ctx.client.generate_response(system_prompt, user_input)
                valid = None
                if expect_json:
                    valid = _is_json((resp.content or "").strip())
                ctx.record_response(resp, json_valid=valid)
                extra = f"valid_json={valid} " if expect_json else ""
                tokens = f"tokens={resp.tokens_input}+{resp.tokens_output} "
                print(
                    f"  [{label} {idx+1}/{total}] {tokens}{extra}"
                    f"latency={resp.latency_ms:.0f}ms"
                )
            except BaseException as e:
                print(f"  [{label} {idx+1}/{total}] ERROR {type(e).__name__}: {str(e)[:120]}")
                raise
    except BaseException:
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass


def run_bench_for_provider(provider: str, turns: int, benchmark_tag: str) -> None:
    print(f"\n=== BENCH provider={provider} tag={benchmark_tag!r} (n={turns}) ===")
    try:
        get_ai_client(provider)
    except Exception as e:
        print(f"  [ABORT] no se pudo inicializar cliente {provider}: {e}")
        return

    for i in range(turns):
        _run_single_call(
            provider, "orchestrator", i, turns,
            ORCHESTRATOR_SYSTEM,
            ORCHESTRATOR_TURNS[i % len(ORCHESTRATOR_TURNS)],
            expect_json=False,
            benchmark_tag=benchmark_tag,
        )
    for i in range(turns):
        _run_single_call(
            provider, "classifier", i, turns,
            CLASSIFIER_SYSTEM,
            CLASSIFIER_INPUTS[i % len(CLASSIFIER_INPUTS)],
            expect_json=True,
            benchmark_tag=benchmark_tag,
        )
    for i in range(turns):
        _run_single_call(
            provider, "evaluator ", i, turns,
            EVALUATOR_SYSTEM,
            EVALUATOR_INPUTS[i % len(EVALUATOR_INPUTS)],
            expect_json=True,
            benchmark_tag=benchmark_tag,
        )


def print_summary(benchmark_tag: str) -> None:
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
                   round(coalesce(json_valid_rate_pct, 0)::numeric, 1) as json_pct,
                   round(coalesce(total_cost_usd, 0)::numeric, 6) as cost_usd
            from public.v_provider_metrics
            where purpose = :tag
            order by provider, model
        """), {"tag": benchmark_tag}).mappings().all()
    finally:
        db.close()

    print(f"\n=========== RESUMEN (purpose={benchmark_tag!r}) ===========")
    if not rows:
        print("(no hay datos. Verifica logs de [metrics_logger] arriba.)")
        return
    headers = list(rows[0].keys())
    print(" | ".join(h.ljust(14) for h in headers))
    print("-" * (17 * len(headers)))
    for r in rows:
        print(" | ".join(str(r[h] if r[h] is not None else "-").ljust(14) for h in headers))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark comparativo con tag configurable. "
            "Misma lógica que bench_providers.py, pero el purpose es un argumento CLI."
        )
    )
    parser.add_argument(
        "--providers", nargs="+",
        default=["openai", "gemini", "deepseek"],
        help="Proveedores a correr (default: openai gemini deepseek).",
    )
    parser.add_argument(
        "--turns", type=int, default=10,
        help="Llamadas por rol por proveedor (default: 10).",
    )
    parser.add_argument(
        "--benchmark-tag",
        default="bench",
        metavar="TAG",
        help=(
            'Etiqueta de esta corrida, usada como purpose en ai_call_logs '
            'y en el resumen final (default: "bench"). '
            'Ejemplos: bench_v2, bench_refactor, bench_gpt4o.'
        ),
    )
    args = parser.parse_args()

    # Registrar el tag como purpose válido antes de cualquier llamada.
    # ALLOWED_PURPOSES es un set mutable en metrics_logger; esto no altera
    # la lógica de ningún otro proceso en ejecución.
    _metrics_logger.ALLOWED_PURPOSES.add(args.benchmark_tag)

    print(
        f"[bench] tag={args.benchmark_tag!r}  "
        f"providers={args.providers}  turns={args.turns}"
    )

    for p in args.providers:
        try:
            run_bench_for_provider(p, turns=args.turns, benchmark_tag=args.benchmark_tag)
        except Exception as e:
            print(f"[ERROR] no se pudo correr bench para {p}: {type(e).__name__}: {e}")

    print_summary(args.benchmark_tag)


if __name__ == "__main__":
    main()
