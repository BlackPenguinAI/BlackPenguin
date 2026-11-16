"""Observed server data only; local repairs are never new measured points."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).parent;data=json.loads((root/'historico-servidor.json').read_text());rows=data['rows'];x=np.arange(len(rows))
labels=['Observ.\ninicial','Reparación\n1','Reparación\n2','Integrado','Integrada\n1','Integrada\n2','Integrada\n3','Estab.\n1','Estab.\n2']
assert len(labels)==len(rows)
fig,axes=plt.subplots(1,2,figsize=(15,4.2),layout='constrained')
for ax,key,total,title in [(axes[0],'graph_cases_pass',6,'Conversaciones con todos sus controles'),(axes[1],'bookings',5,'Visitas creadas / esperadas')]:
 values=np.array([r[key] for r in rows]);ax.plot(x,values,marker='o',linewidth=2.5,color='#b47e00')
 ax.scatter([x[-1]],[values[-1]],color='#bd604c',zorder=3)
 for i,y in enumerate(values):ax.annotate(f'{y}/{total}',(i,y),xytext=(0,8),textcoords='offset points',ha='center',weight='bold')
 ax.set_xticks(x,labels);ax.set_yticks(np.arange(total+1));ax.set_ylim(0,total+.7);ax.set_title(title,fontsize=11);ax.grid(axis='y',alpha=.2)
fig.suptitle('LangGraph · mismos seis guiones · el historial incluye retrocesos',weight='bold')
fig.savefig(root/'evolucion-seis-casos.png',dpi=170)
fig,ax=plt.subplots(figsize=(8,3.3),layout='constrained');cost=np.array([r['graph_cost_usd'] for r in rows]);bars=ax.bar(x,cost,color='#176b87')
for i,c in enumerate(cost):ax.annotate(f'${c:.8f}',(i,c),xytext=(0,5),textcoords='offset points',ha='center',fontsize=9)
ax.set_xticks(x,labels);ax.set_ylim(0,float(cost.max())*1.3);ax.set_ylabel('USD por corrida');ax.set_title(f"Nueve corridas LangGraph · total USD {data['total_graph_cost_usd']:.8f}",loc='left',fontsize=12)
fig.savefig(root/'consumo-cuatro-corridas.png',dpi=170)
