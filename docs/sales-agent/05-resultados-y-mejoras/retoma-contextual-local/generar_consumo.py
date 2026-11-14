"""Reproduce the observed OpenRouter cost curve; no model calls."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

cost=np.array([0.15756165,0.12972465,0.12658365,0.08616360])
y=np.cumsum(cost)
x=np.arange(len(y))
fig,ax=plt.subplots(figsize=(9,4.1),layout='constrained')
ax.plot(x,y,color='#b38a00',marker='o',linewidth=2.5,markersize=7)
for a,b in zip(x,y):ax.annotate(f'US$ {b:.3f}',(a,b),xytext=(0,10),textcoords='offset points',ha='center',fontsize=10)
ax.set_xticks(x,['Necesidades\n(4 corridas)','Continuidad 1','Continuidad 2','Retoma 1'])
ax.set_ylim(0,.58);ax.set_ylabel('USD acumulados');ax.set_title('Consumo rastreado desde las pruebas de necesidades',loc='left',weight='bold')
ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.2)
fig.savefig(Path(__file__).with_name('consumo-observado.png'),dpi=160)
plt.close(fig)
