r"""
Bench reproducible para la matriz comparativa del Capitulo 3 del TG.

Para cada proveedor (openai, gemini, deepseek), ejecuta:
- N llamadas al "orchestrator" (respuesta del NPC sobre un prompt fijo).
- N llamadas al "classifier" sobre un set fijo de turnos.
- N llamadas al "evaluator" sobre el mismo set.

Cada llamada queda registrada en ai_call_logs con purpose=bench.
Al final, imprime las metricas agregadas leyendo de v_provider_metrics filtrado
por purpose=bench.

Robustez:
- Cada llamada usa una sesion BD propia para que un error no contamine las demas.
- Cada llamada esta protegida con try/except amplio (incluye errores SSL/timeout).

Ejecucion (desde la raiz del proyecto, con .venv activo):
    python scripts/bench_providers.py --turns 10
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
) -> None:
    """
    Ejecuta UNA llamada IA con su propia sesion BD.
    Cualquier error queda registrado como AICallLog con status='error_*'
    sin contaminar el resto del bench.
    """
    db = SessionLocal()
    try:
        with log_ai_call(db, purpose="bench", provider_override=provider) as ctx:
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
                # Atrapamos BaseException para evitar que SSL EOF u otros
                # corten el bench. log_ai_call tambien lo persiste con error.
                print(f"  [{label} {idx+1}/{total}] ERROR {type(e).__name__}: {str(e)[:120]}")
                # Re-raise para que el context manager registre el error correctamente
                raise
    except BaseException:
        # Ya impreso. Continuar al siguiente.
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass


def run_bench_for_provider(provider: str, turns: int = 10) -> None:
    print(f"\n=== BENCH provider={provider} (n={turns}) ===")
    # Forzar singleton del proveedor objetivo
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
        )
    for i in range(turns):
        _run_single_call(
            provider, "classifier", i, turns,
            CLASSIFIER_SYSTEM,
            CLASSIFIER_INPUTS[i % len(CLASSIFIER_INPUTS)],
            expect_json=True,
        )
    for i in range(turns):
        _run_single_call(
            provider, "evaluator ", i, turns,
            EVALUATOR_SYSTEM,
            EVALUATOR_INPUTS[i % len(EVALUATOR_INPUTS)],
            expect_json=True,
        )


def print_summary() -> None:
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
            where purpose = 'bench'
            order by provider, model
        """)).mappings().all()
    finally:
        db.close()

    print("\n=========== RESUMEN (purpose=bench) ===========")
    if not rows:
        print("(no hay datos. Verifica logs de [metrics_logger] arriba.)")
        return
    headers = list(rows[0].keys())
    print(" | ".join(h.ljust(14) for h in headers))
    print("-" * (17 * len(headers)))
    for r in rows:
        print(" | ".join(str(r[h] if r[h] is not None else "-").ljust(14) for h in headers))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", nargs="+", default=["openai", "gemini", "deepseek"])
    parser.add_argument("--turns", type=int, default=10)
    args = parser.parse_args()

    for p in args.providers:
        try:
            run_bench_for_provider(p, turns=args.turns)
        except Exception as e:
            print(f"[ERROR] no se pudo correr bench para {p}: {type(e).__name__}: {e}")

    print_summary()


if __name__ == "__main__":
    main()
