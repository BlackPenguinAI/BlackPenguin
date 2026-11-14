"""Observed server runs only. Different criteria are not a controlled quality curve."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parents[2]
names=['Descubrimiento','Filtro reparado','Redacción','Aceptación']
passed=np.array([0,12,13,14]);total=np.array([12,12,14,14])
cost=np.array([.0336537,.0345396,.04519425,.0441741]);x=np.arange(4)
fig,axes=plt.subplots(1,2,figsize=(11,3.8))
axes[0].plot(x,100*passed/total,'o-',color='#176b87');axes[0].set(xticks=x,xticklabels=names,ylim=(-5,112),ylabel='% de escenarios sin checks fallidos',title='Checks de cada ejecución (criterios evolucionaron)')
for i,(a,b) in enumerate(zip(passed,total)):axes[0].annotate(f'{a}/{b}',(i,100*a/b),ha='center',xytext=(0,7),textcoords='offset points')
axes[1].bar(x,cost,color='#176b87');axes[1].set(xticks=x,xticklabels=names,ylabel='USD totales por corrida',title=f'Total observado: USD {np.sum(cost):.8f}',ylim=(0,.057))
for i,c in enumerate(cost):axes[1].annotate(f'{c:.5f}',(i,c),ha='center',xytext=(0,5),textcoords='offset points')
for ax in axes:ax.grid(axis='y',alpha=.2);ax.tick_params(axis='x',labelsize=8)
fig.suptitle('Servidor · gpt-4o-mini · búsqueda y aceptación; no certifica diálogos completos',fontsize=11)
fig.tight_layout();fig.savefig(root/'05-resultados-y-mejoras/figuras/necesidades-observadas.png',dpi=160,bbox_inches='tight');plt.close(fig)
