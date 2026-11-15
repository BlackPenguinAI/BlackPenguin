"""NumPy + Matplotlib; original server metrics, no model requests."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
out=Path(__file__).parent
cost=np.array([.15756165,.12972465,.12658365,.08616360,.12500070,.15285525,.14232105])
fig,ax=plt.subplots(figsize=(10,4.3),layout='constrained')
x=np.arange(len(cost));y=np.cumsum(cost)
ax.plot(x,y,color='#9b7600',marker='o',linewidth=2.4)
for a,b in zip(x,y):ax.annotate(f'US$ {b:.3f}',(a,b),xytext=(0,10),textcoords='offset points',ha='center',fontsize=9)
ax.set_xticks(x,['Necesidades\n4 corridas','Continuidad 1','Continuidad 2','Retoma 1','Retoma 2','Retoma 3','Retoma 4'])
ax.set_ylim(0,1.05);ax.set_ylabel('USD acumulados');ax.set_title('Consumo observado desde necesidades',loc='left',weight='bold')
ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
fig.savefig(out/'consumo-observado.png',dpi=160);plt.close(fig)
fig,ax=plt.subplots(figsize=(9,4.3),layout='constrained')
x=np.arange(3)
ax.plot(x,np.array([2,3,2]),marker='o',color='#8556ab',label='Conversaciones sin checks fallidos')
ax.plot(x,np.array([2,4,4]),marker='s',color='#268577',label='Visitas simuladas')
for series,offset in [(np.array([2,3,2]),-17),(np.array([2,4,4]),9)]:
 for a,b in zip(x,series):ax.annotate(f'{b}/5',(a,b),xytext=(0,offset),textcoords='offset points',ha='center')
ax.set_xticks(x,['Retoma 2 / 1569573','Retoma 3 / c087cf7','Retoma 4 / b9e3ceb'])
ax.set_ylim(.5,5.5);ax.set_yticks(np.arange(0,6));ax.set_ylabel('De cinco conversaciones por corrida')
ax.set_title('Los mismos cinco objetivos: agendar no basta',loc='left',weight='bold')
ax.legend(loc='upper left');ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
fig.savefig(out/'evolucion-casos.png',dpi=160);plt.close(fig)
