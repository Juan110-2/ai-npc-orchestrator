-- =============================================================================
-- Fix: recalcular cost_usd para filas existentes de Gemini que se grabaron
-- antes de que el pricing reconociera el modelo actual.
--
-- Ejecutar en Supabase SQL Editor. Idempotente.
-- =============================================================================

-- Diagnostico: ver que modelos hay registrados sin costo aun teniendo tokens
select provider, model, status,
       count(*) as n_rows,
       sum(tokens_input) as in_tokens,
       sum(tokens_output) as out_tokens,
       count(cost_usd) as n_with_cost
from public.ai_call_logs
where provider = 'gemini'
group by provider, model, status
order by model, status;

-- Recalcular cost para gemini-2.5-flash-lite (tarifa: $0.10 in / $0.40 out por 1M tokens)
update public.ai_call_logs
set cost_usd = (
    coalesce(tokens_input, 0)::numeric  / 1000000 * 0.100 +
    coalesce(tokens_output, 0)::numeric / 1000000 * 0.400
)
where provider = 'gemini'
  and model = 'gemini-2.5-flash-lite'
  and status = 'ok'
  and (cost_usd is null or cost_usd = 0)
  and (tokens_input > 0 or tokens_output > 0);

-- Recalcular tambien para gemini-1.5-flash si quedo alguna llamada exitosa
-- (en tu caso fueron todas error 404, pero por completitud)
update public.ai_call_logs
set cost_usd = (
    coalesce(tokens_input, 0)::numeric  / 1000000 * 0.075 +
    coalesce(tokens_output, 0)::numeric / 1000000 * 0.300
)
where provider = 'gemini'
  and model = 'gemini-1.5-flash'
  and status = 'ok'
  and (cost_usd is null or cost_usd = 0)
  and (tokens_input > 0 or tokens_output > 0);

-- Verificacion final
select provider, model,
       count(*) filter (where status='ok') as n_ok,
       sum(cost_usd) filter (where status='ok') as total_cost_usd
from public.ai_call_logs
where provider = 'gemini'
group by provider, model;
