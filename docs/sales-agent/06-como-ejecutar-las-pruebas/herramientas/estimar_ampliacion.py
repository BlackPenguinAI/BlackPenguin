"""Planning arithmetic from a measured run; does not call a model or run tests."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
rows=json.loads((ROOT/'05-resultados-y-mejoras/corridas.json').read_text())
base=next(r for r in rows if r['run']=='sales-compact-repair-5')
assert base['cost_complete']
per_turn={'calls':base['provider_calls']/base['turns'],'tokens':(base['prompt_tokens']+base['completion_tokens'])/base['turns'],'usd':base['cost_usd_recorded']/base['turns']}
stages=[('cerrar_bloqueo',3,4,8),('bateria_base',16,6,8),('variantes',32,8,12),('dialogos_largos',16,12,16),('consistencia_tres_repeticiones',48,8,12)]
result={'status':'PROPOSAL_NOT_EXECUTED','basis':base['run'],'model':base['model'],'configuration_version':base['configuration_version'],'observed_turns':base['turns'],'per_lead_turn':per_turn,'reserve_factor':2,'assumptions':['Scripted leads; no lead LLM or judge.','Same sales model/configuration as baseline.','Linear planning extrapolation, not a measured long-dialogue tariff or confidence interval.','Longer histories, repairs, provider changes and token prices can exceed this reserve.','Costs exclude labor, infrastructure and transport.'],'stages':[]}
for name,count,low,high in stages:
    turns=[count*low,count*high]
    metrics={k:[v*t for t in turns] for k,v in per_turn.items()}
    result['stages'].append({'stage':name,'conversations':count,'lead_turns_per_conversation':[low,high],'total_lead_turns':turns,'estimated_calls':metrics['calls'],'estimated_total_tokens':metrics['tokens'],'estimated_usd':metrics['usd'],'planning_reserve_usd':[2*x for x in metrics['usd']]})
(ROOT/'05-resultados-y-mejoras/propuesta-ampliacion.json').write_text(json.dumps(result,indent=2)+'\n')
