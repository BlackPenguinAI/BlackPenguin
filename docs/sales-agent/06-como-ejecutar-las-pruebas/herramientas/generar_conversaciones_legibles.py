"""Readable views of recorded synthetic conversations; no inference or invented reasoning."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TOPICS={'catalog':'opciones de propiedad','property_details':'características de la propiedad','inventory':'disponibilidad','pricing':'precio','financing':'formas de pago/financiación','materials':'materiales','appointment':'visita','location':'ubicación','delivery':'entrega','human':'contacto humano','opt_out':'no recibir contacto','other':'otra consulta'}
VISIT={'request':'solicitar una visita','select':'elegir un horario (todavía no confirmar)','confirm':'confirmar una propuesta','decline':'rechazar por ahora una visita'}
STATUS={'aprobado':'Aprobada por los controles de esa corrida','fallido':'Fallida: revisar los puntos señalados','incompleto':'Incompleta o bloqueada'}

def quote(text):
    return '\n'.join('> '+line for line in str(text or 'No exportado.').splitlines())

def interpretation(u):
    if not u:return 'No se exportó una interpretación válida para este turno. No se infiere a partir de la respuesta.'
    refs={r.get('id'):r for r in u.get('references',[])};parts=[]
    for row in u.get('requests',[]):
        topic=TOPICS.get(row.get('topic'),row.get('topic','consulta'));ref=refs.get(row.get('reference_id'),{});name=ref.get('expression')
        parts.append(('Excluyó ' if row.get('polarity')=='exclude' else 'Solicitó ')+str(topic)+(f' sobre «{name}»' if name else '')+(f" ({row['subject']})" if row.get('subject') else ''))
    fields={'budget':'presupuesto','financing':'forma de pago','property':'propiedad de interés','buyer_type':'motivación','motivation':'motivación','visit_readiness':'disposición a visitar'}
    for pref in u.get('preferences',[]):
        key=pref.get('key')
        if key in fields:parts.append('Declaración registrada de '+fields[key]+': «'+str(pref.get('value',''))+'» ('+str(pref.get('status',''))+')')
    visit=u.get('visit')
    if visit:parts.append('Visita: '+VISIT.get(visit.get('action'),str(visit.get('action'))))
    if u.get('constraints'):parts.append('Restricciones registradas: '+', '.join(TOPICS.get(c.get('topic'),str(c.get('topic'))) for c in u['constraints']))
    if u.get('requires_clarification'):parts.append('Marcó necesidad de aclaración')
    if u.get('confidence') is not None:parts.append('Confianza registrada: '+str(u['confidence'])+' (no es una probabilidad calibrada)')
    return '; '.join(parts)+'.' if parts else 'No registró una nueva solicitud independiente; consultar el diálogo y el resultado.'


def render(path):
    d=json.loads(path.read_text());title=d['description'].replace('-',' ').capitalize();turns=d.get('turns',[])
    lines=[f'# {title}', '', '[Volver a la guía del agente](../../README.md) · [Abrir evidencia técnica JSON]('+path.name+')', '', '**Conversación sintética ejecutada en el servidor.** Los mensajes se conservan en su idioma original. La explicación resume campos estructurados y controles exportados; no representa razonamiento privado del modelo ni una explicación generada posteriormente por otro LLM.', '', '| Dato | Evidencia |','|---|---|',f"| Caso / corrida | `{d['case']}` / `{d['source_archive'].removesuffix('.zip')}` |",f"| Resultado automático original | {STATUS.get(d.get('automatic_result'),d.get('automatic_result'))} |",f"| Modelo / configuración | `{d.get('sales_model') or 'No exportado'}` / {d.get('configuration_version') or 'No exportada'} |",f"| Visitas registradas / turnos | {len(d.get('meetings',[]))} / {len(turns)} |", '| Costo | El reporte lo agrega por corrida; no se inventa un importe por conversación. |', '', '**Cómo repetirla:** usar una company y un project de prueba con información aprobada coherente; sustituir nombres, recursos y horarios por los vigentes. Una aprobación histórica no garantiza estabilidad con nuevos mensajes o entrega por WhatsApp/SMS. Las fechas y recursos de este laboratorio no son una oferta real.', '']
    failures=d.get('failures',[])
    if failures:
        lines+=['**Qué falló en esta corrida:** '+', '.join(sorted({f.get('check','control sin nombre') for f in failures}))+'. El estado original se conserva, incluso si se corrigió después.', '']
    if (d.get('human_review') or {}).get('status') not in (None,'pending'):
        lines+=['**Revisión posterior:** '+str(d['human_review'].get('note') or d['human_review'].get('status')), '']
    for t in turns:
        lines += [f"## Turno {t.get('turn')}",'','**Lead sintético**','',quote(t.get('lead')),'','**Qué interpretó el agente — registro estructurado**','',interpretation(t.get('understanding')),'','**Cómo procedió — evidencia disponible**','']
        checks={c.get('check'):c.get('status') for c in t.get('checks',[])};actions=[]
        if checks.get('material_request_delivered_this_turn')=='PASS':actions.append('El control de este turno verificó la entrega del material solicitado.')
        if checks.get('selection_advances_to_confirmation')=='PASS':actions.append('Preparó el resumen de visita para confirmación; elegir horario no equivale a agendar.')
        comp=t.get('composition') or {}
        if comp.get('status')=='backend_rendered':actions.append('El backend presentó el comprobante registrado directamente, sin inferencia adicional de composición.')
        elif comp.get('status')=='accepted':actions.append('La composición fue aceptada dentro de las opciones de evidencia autorizadas.')
        elif comp.get('status')=='safe_fallback':actions.append('Se usó una respuesta de respaldo; no se considera composición aceptada por el modelo.')
        attempts=t.get('interpretation_attempts',[])
        if len(attempts)>1:
            actions.append('La interpretación necesitó '+str(len(attempts))+' intentos; '+('el último fue aceptado.' if attempts[-1].get('outcome')=='accepted' else 'el último no fue aceptado.'))
        if t.get('error_code'):actions.append('El turno registró un error de procesamiento: '+str(t['error_code'])+'.')
        bad=[c.get('check','control') for c in t.get('checks',[]) if c.get('status')!='PASS']
        if bad:actions.append('Controles sin aprobar: '+', '.join(bad)+'.')
        lines+=actions or ['No se exportó un detalle de ejecución suficiente para describir más acciones de este turno. La respuesta original y el estado final se conservan.']
        lines+=['','**Respuesta del agente**','',quote(t.get('agent')),'']
    lines+=['## Resultado y respaldo','','Visitas registradas en el laboratorio: **'+str(len(d.get('meetings',[])))+'**. Consultar el JSON para recursos, equipo, interpretación completa, controles e identificadores. No confundir la cita del laboratorio con un evento confirmado en Calendar externo.', '', '[Abrir JSON de esta conversación]('+path.name+')', '']
    path.with_suffix('.md').write_text('\n'.join(lines))

if __name__=='__main__':
    index=json.loads((ROOT/'04-conversaciones/indice.json').read_text())
    for item in index:render(ROOT/item['file'])
    print(f'{len(index)} readable conversations generated from recorded evidence; no model calls.')
