"""Observed reported amounts; final point is incomplete, not an exact total."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
labels=['Necesidades','Continuidad','Retoma 1','Retoma 2','Retoma 3','Retoma 4','Retoma 5','Classic previo','Grafo previo','Classic*','Observaciones']
cost=np.array([.15756165,.25630830,.08616360,.12500070,.15285525,.14232105,.15659055,.13637820,.13746525,.10905435,.11234655])
y=np.cumsum(cost);x=np.arange(len(cost))
fig,ax=plt.subplots(figsize=(11,4.2),layout='constrained')
ax.plot(x[:9],y[:9],'o-',color='#16736a');ax.plot(x[8:],y[8:],'o--',color='#b26b00')
ax.set(xticks=x,xticklabels=labels,ylabel='USD acumulados reportados',title='Importes informados: USD 1.57204545; último tramo parcial')
ax.tick_params(axis='x',rotation=30);ax.grid(axis='y',alpha=.2);ax.set_ylim(0,1.8)
ax.text(.02,.95,'* Falta el costo de una llamada de Classic. No es el total definitivo.',transform=ax.transAxes,va='top',fontsize=10)
fig.savefig(Path(__file__).with_name('consumo-reportado.png'),dpi=160)
