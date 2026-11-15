"""Observed case checks in two six-case server pairs; not integral quality."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
x=np.arange(2);width=.32
fig,ax=plt.subplots(figsize=(7.6,4.0),layout='constrained')
for delta,values,label,color in [(-width/2,[4,3],'Classic','#6b7280'),(width/2,[4,5],'Graph-observe','#16736a')]:
 bars=ax.bar(x+delta,values,width,label=label,color=color);ax.bar_label(bars,labels=[f'{v}/6' for v in values],padding=4)
ax.set(xticks=x,xticklabels=['Primera pareja','Repair 1 recibido'],ylim=(0,6.5),ylabel='Casos sin controles fallidos',title='Evidencia del servidor: seis casos por recorrido')
ax.legend(loc='upper left');ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
fig.savefig(Path(__file__).with_name('evolucion-casos.png'),dpi=160)
