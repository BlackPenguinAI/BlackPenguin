"""Retrospective labels; never overwrite historical checks or model messages."""
import json
from pathlib import Path


def classify(document):
    findings=[]
    for t in document.get('turns',[]):
        reply=str(t.get('agent') or t.get('reply') or '')
        if 'Property_details: verified information is not available in this query.' in reply:
            findings.append({'turn':t.get('turn'),'code':'unresolved_details_and_internal_wording','reason':'La respuesta no resuelve los detalles solicitados y muestra una etiqueta interna.'})
        if 'The approved project information highlights:' in reply:
            findings.append({'turn':t.get('turn'),'code':'internal_provenance_wording','reason':'La respuesta usa una fórmula interna en lugar de una explicación comercial natural.'})
    review=document.get('human_review') or {}
    quality='NEEDS_IMPROVEMENT' if findings or review.get('status')=='necesita-mejoras' else 'SCOPED_FAVORABLE_REVIEW' if review.get('status')=='revisado-favorable' else 'NOT_EVALUATED'
    return {'version':'sales-evidence-labels/2.0','recorded_checks':document.get('automatic_result'),
        'dialogue_quality':quality,'integral_dialogue_approval':False,'retrospective_findings':findings,
        'scope':'Los checks originales y nombres de archivo son históricos. Aprobarlos no certifica relevancia, fluidez ni todo el diálogo. Una revisión favorable solo cubre los comportamientos que describe.'}


def update(root):
    root=Path(root);index_path=root/'04-conversaciones/indice.json';index=json.loads(index_path.read_text())
    counts={}
    for item in index:
        path=root/item['file'];document=json.loads(path.read_text());labels=classify(document)
        document['evaluation_labels']=labels;path.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n')
        item['dialogue_quality']=labels['dialogue_quality'];item['integral_dialogue_approval']=False
        counts[labels['dialogue_quality']]=counts.get(labels['dialogue_quality'],0)+1
    index_path.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
    return counts


if __name__=='__main__':
    print(json.dumps(update(Path(__file__).resolve().parents[2]),ensure_ascii=False))
