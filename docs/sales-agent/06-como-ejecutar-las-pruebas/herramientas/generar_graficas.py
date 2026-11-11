"""NumPy/Matplotlib figures from observed server runs; no smoothing or estimates."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
ROOT=Path(__file__).resolve().parents[2]
rows=json.loads((ROOT/'05-resultados-y-mejoras/corridas.json').read_text())
out=ROOT/'05-resultados-y-mejoras/figuras';out.mkdir(exist_ok=True)
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white'})

def save(fig,name):
    fig.tight_layout();fig.savefig(out/name,dpi=160,bbox_inches='tight');plt.close(fig)

three=[r for r in rows if r['suite']=='compact' and set(r['selected_cases'])=={'first_time_A','move_up_B','unknown_A'}]
x=np.arange(len(three));labels=[r['run'].replace('sales-compact-repair-','Repair ') for r in three]
fig,axes=plt.subplots(1,2,figsize=(10,3.6))
for ax,field,total,title in [(axes[0],'approved_cases','cases','Conversaciones aprobadas automáticamente'),(axes[1],'actual_bookings','expected_bookings','Visitas confirmadas en laboratorio')]:
    y=np.array([100*r[field]/r[total] for r in three],dtype=float);ax.plot(x,y,'o-',color='#176b87',linewidth=2);ax.set(xticks=x,xticklabels=labels,ylim=(-5,110),ylabel='Porcentaje',title=title);ax.grid(axis='y',alpha=.2)
    for i,r in enumerate(three):ax.annotate(f'{r[field]}/{r[total]}',(i,y[i]),xytext=(0,9),textcoords='offset points',ha='center')
fig.suptitle('Mismos tres casos · resultados observados del servidor',y=1.05)
save(fig,'recorrido-compacto.png')
fig,axes=plt.subplots(1,2,figsize=(10,3.6))
axes[0].plot(x,np.array([r['provider_calls'] for r in three]),'o-',color='#176b87');axes[0].set(xticks=x,xticklabels=labels,title='Llamadas al proveedor',ylabel='Llamadas')
cost=np.array([r['cost_usd_recorded'] if r['cost_usd_recorded'] is not None else np.nan for r in three]);bars=axes[1].bar(x,cost,color='#176b87')
for i,r in enumerate(three):
    if not r['cost_complete']:bars[i].set_hatch('//')
    axes[1].annotate(f'USD {cost[i]:.4f}'+(' *' if not r['cost_complete'] else ''),(i,cost[i]),ha='center',xytext=(0,5),textcoords='offset points')
axes[1].set(xticks=x,xticklabels=labels,title='Costo registrado (* incompleto)',ylabel='USD',ylim=(0,float(np.nanmax(cost))*1.3))
fig.suptitle('Un costo incompleto no es un total ni una estimación',y=1.05);save(fig,'llamadas-y-costos.png')
fig,axes=plt.subplots(2,2,figsize=(11,7))
groups=[('booking',6),('compact',16),('compact',8),('compact',3)]
for ax,(suite,count) in zip(axes.flat,groups):
    group=[r for r in rows if r['suite']==suite and r['cases']==count]
    xx=np.arange(len(group));yy=np.array([r['actual_bookings'] for r in group],float)
    ax.plot(xx,yy,'o-',label='Visitas observadas');ax.plot(xx,np.array([r['expected_bookings'] for r in group],float),'--o',label='Visitas esperadas')
    ax.set(title=f'{suite}: {count} casos (sin mezclar conjuntos)',xticks=xx,xticklabels=[r['run'].replace('sales-','').replace('compact-','').replace('booking-','') for r in group],ylabel='Visitas');ax.set_ylim(0,max(r['expected_bookings'] for r in group)+.5);ax.yaxis.set_major_locator(MaxNLocator(integer=True));ax.tick_params(axis='x',rotation=25);ax.grid(axis='y',alpha=.2);ax.legend(fontsize=8)
fig.suptitle('El historial también contiene regresiones; criterios de evaluación evolucionaron',y=1.02);save(fig,'evolucion-por-conjunto.png')

# Adaptive LLM buyers are a separate experimental stage, never pooled with scripts.
early=[r for r in rows if r['suite']=='adaptive']
if early:
    xx=np.arange(len(early));names=[r['run'].replace('sales-synthetic-lab-','Lab ') for r in early]
    fig,axes=plt.subplots(1,3,figsize=(13,3.7))
    for ax,key,title in [(axes[0],'approved_cases','Casos aprobados (de nueve)'),(axes[1],'turns','Mensajes del lead'),(axes[2],'provider_calls','Llamadas: lead + agente')]:
        vals=np.array([r[key] for r in early],dtype=float);ax.plot(xx,vals,'o-',color='#176b87');ax.set(xticks=xx,xticklabels=names,title=title,ylim=(0,max(vals)*1.25));ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        for i,v in enumerate(vals):ax.annotate(str(int(v)),(i,v),ha='center',xytext=(0,6),textcoords='offset points')
    fig.suptitle('Primer laboratorio: cambio del controlador del lead, no mejora causal del agente',y=1.05)
    save(fig,'primer-laboratorio-adaptativo.png')

# Global history: executions and spending, not a pooled quality score.
labels=[r['run'].replace('sales-synthetic-lab-','L').replace('sales-booking-point-','A').replace('sales-commercial-point-','C').replace('sales-closing-point-','D').replace('sales-compact-battery-','B').replace('sales-compact-repair-','R') for r in rows]
xx=np.arange(len(rows));approved=np.array([r['approved_cases'] for r in rows]);failed=np.array([sum(c['status']=='fallido' for c in r['case_results']) for r in rows]);blocked=np.array([sum(c['status']=='incompleto' for c in r['case_results']) for r in rows])
fig,axes=plt.subplots(2,1,figsize=(13,7))
axes[0].bar(xx,approved,label='Aprobadas por sus controles',color='#24775e');axes[0].bar(xx,failed,bottom=approved,label='Fallidas',color='#bd604c');axes[0].bar(xx,blocked,bottom=approved+failed,label='Incompletas',color='#bd933d')
axes[0].set(xticks=xx,xticklabels=labels,ylabel='Conversaciones ejecutadas',title='Estado de los casos por corrida (criterios y tamaños distintos)');axes[0].yaxis.set_major_locator(MaxNLocator(integer=True));axes[0].legend(fontsize=9,ncols=3)
axes[1].plot(xx,np.cumsum(np.array([r['cases'] for r in rows])),'o-',label='Ejecuciones acumuladas (incluye repeticiones)');unique=set();coverage=[]
for r in rows:
    unique.update((r['suite'],c['case']) for c in r['case_results']);coverage.append(len(unique))
axes[1].plot(xx,np.array(coverage),'s--',label='IDs de escenario distintos por suite');axes[1].set(xticks=xx,xticklabels=labels,ylabel='Cantidad acumulada',title='Cobertura e iteraciones; no es una curva única de calidad');axes[1].legend(fontsize=9)
fig.suptitle('L: lead LLM · A: agenda · C: comercial · D: despedidas · B: batería · R: reparación',y=1.02);save(fig,'panorama-global.png')
fig,axes=plt.subplots(1,2,figsize=(13,4))
costs=np.array([r['cost_usd_recorded'] or 0 for r in rows]);bars=axes[0].bar(xx,costs,color='#176b87')
for i,r in enumerate(rows):
    if not r['cost_complete']:bars[i].set_hatch('//')
axes[0].set(xticks=xx,xticklabels=labels,ylabel='USD registrados',title='Consumo por corrida (rayado = incompleto)');axes[0].tick_params(axis='x',rotation=45)
axes[1].plot(xx,np.cumsum(costs),'o-',color='#176b87');axes[1].set(xticks=xx,xticklabels=labels,ylabel='USD registrados acumulados',title=f'Acumulado parcial: {sum(r["provider_calls"]-r["responses_with_cost"] for r in rows)} llamadas sin costo informado');axes[1].tick_params(axis='x',rotation=45)
save(fig,'consumo-global.png')

# A retrospective view of the same IDs, including when they were in larger suites.
common={'first_time_A','move_up_B','unknown_A'};series=[]
for r in rows:
    chosen=[c for c in r['case_results'] if c['case'] in common]
    if r['suite']=='compact' and len(chosen)==3:
        series.append({'run':r['run'],'source_commit':r['commit'],'source_cases':r['cases'],'selected_cases':sorted(common),'approved_cases':sum(c['status']=='aprobado' for c in chosen),'bookings':sum(c['meetings'] for c in chosen)})
(ROOT/'05-resultados-y-mejoras/seguimiento-casos-comunes.json').write_text(json.dumps({'analysis_kind':'retrospective_subset_not_new_execution','note':'Original checks retained; validators evolved. Not equivalent to a controlled current-version reevaluation.','series':series},indent=2)+'\n')
fig,axes=plt.subplots(1,2,figsize=(11,3.6));xx=np.arange(len(series));names=[r['run'].replace('sales-compact-battery-','B').replace('sales-compact-repair-','R') for r in series]
for ax,key,denominator,title in [(axes[0],'approved_cases',3,'Conversaciones aprobadas de los mismos tres IDs'),(axes[1],'bookings',2,'Visitas observadas de esos dos casos de agenda')]:
    values=np.array([r[key] for r in series]);ax.plot(xx,values,'o-',color='#176b87');ax.set(xticks=xx,xticklabels=names,ylim=(-.1,denominator+.5),title=title,ylabel='Cantidad');ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    for i,value in enumerate(values):ax.annotate(f'{value}/{denominator}',(i,value),ha='center',xytext=(0,8),textcoords='offset points')
fig.suptitle('Seguimiento retrospectivo: IDs comunes, checks originales de cada versión',y=1.05);save(fig,'casos-comunes-desde-la-bateria.png')
