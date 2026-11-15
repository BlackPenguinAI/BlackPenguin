"""NumPy + Matplotlib; original server metrics, no model requests."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
out=Path(__file__).parent
cost=np.array([.15756165,.12972465,.12658365,.08616360,.12500070,.15285525,.14232105,.15659055])
fig,ax=plt.subplots(figsize=(11,4.3),layout='constrained')
x=np.arange(len(cost));y=np.cumsum(cost)
ax.plot(x,y,color='#9b7600',marker='o',linewidth=2.4)
for a,b in zip(x,y):ax.annotate(f'US$ {b:.3f}',(a,b),xytext=(0,10),textcoords='offset points',ha='center',fontsize=9)
ax.set_xticks(x,['Necesidades\n4 corridas','Continuidad 1','Continuidad 2','Retoma 1','Retoma 2','Retoma 3','Retoma 4','Retoma 5'])
ax.set_ylim(0,1.2);ax.set_ylabel('USD acumulados');ax.set_title('Consumo observado desde necesidades',loc='left',weight='bold')
ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
fig.savefig(out/'consumo-observado.png',dpi=160);plt.close(fig)
