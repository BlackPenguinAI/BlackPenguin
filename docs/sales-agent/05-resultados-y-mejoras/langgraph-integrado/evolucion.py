"""Historical six-case server runs; not commercial-quality certification."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).parent
rows=[{'commit':'31023e0','graph_cases_pass':4,'cases':6,'graph_calls':127,'graph_cost_usd':0.11234655,'source':'sales-observation-comparison.zip'},
      {'commit':'ba5c4c5','graph_cases_pass':5,'cases':6,'graph_calls':134,'graph_cost_usd':0.12726405,'source':'sales-observation-repair-1-comparison.zip'},
      {'commit':'cb30201','graph_cases_pass':6,'cases':6,'graph_calls':130,'graph_cost_usd':0.11303685,'source':'sales-observation-repair-2-comparison.zip'}]
(root/'historico-servidor.json').write_text(json.dumps({'scope':'six fixed scripted synthetic cases; graph-observe only','commercial_quality':'NOT_EVALUATED','rows':rows,'total_graph_calls':sum(r['graph_calls'] for r in rows),'total_graph_cost_usd':round(sum(r['graph_cost_usd'] for r in rows),8)},indent=2))
x=np.arange(len(rows));passed=np.array([r['graph_cases_pass'] for r in rows])
fig,ax=plt.subplots(figsize=(8,3.3),layout='constrained')
ax.plot(x,passed,marker='o',linewidth=2.5,color='#b47e00')
for i,y in enumerate(passed):ax.annotate(f'{y}/6',(i,y),xytext=(0,8),textcoords='offset points',ha='center',weight='bold')
ax.set_xticks(x,['Observaciones','Reparación 1','Reparación 2']);ax.set_yticks(np.arange(0,7));ax.set_ylim(0,6.7)
ax.set_ylabel('Casos con controles satisfechos');ax.set_title('LangGraph · los mismos seis casos en el servidor',loc='left',weight='bold');ax.grid(axis='y',alpha=.2)
fig.savefig(root/'evolucion-seis-casos.png',dpi=170)
