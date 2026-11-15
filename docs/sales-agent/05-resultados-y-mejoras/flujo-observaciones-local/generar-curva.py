"""Reproduce the observed cost curve; no modeled quality/success trend inferred."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
labels=['Necesidades','Continuidad','Retoma 1','Retoma 2','Retoma 3','Retoma 4','Retoma 5','Classic','Graph previo']
cost=np.array([.15756165,.25630830,.08616360,.12500070,.15285525,.14232105,.15659055,.13637820,.13746525])
fig,ax=plt.subplots(figsize=(10,4.2),layout='constrained')
x=np.arange(len(cost));y=np.cumsum(cost)
ax.plot(x,y,'o-',color='#16736a',lw=2);ax.fill_between(x,y,alpha=.10,color='#16736a')
ax.set(xticks=x,xticklabels=labels,ylabel='USD acumulados observados',title='Consumo rastreado desde necesidades: USD 1.35064455')
ax.tick_params(axis='x',rotation=25);ax.grid(axis='y',alpha=.2);ax.set_ylim(0,1.55)
ax.annotate(f'{y[-1]:.8f}',(x[-1],y[-1]),xytext=(-60,12),textcoords='offset points')
fig.savefig(Path(__file__).with_name('consumo-acumulado.png'),dpi=160)
