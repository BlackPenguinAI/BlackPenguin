"""Review-only inventory; proposals do not change the live question catalog."""
from .onboarding_questions import QUESTION_CATALOG, build_next_question
from .company_onboarding.completion import ALL_FIELDS as COMPANY_FIELDS
from .projects.completion import FIELDS as PROJECT_FIELDS

PROPOSED_MULTIPLE = {
    'corporate_differentiators':'Separar diferenciadores corporativos en elementos; confirmar alternativas y contrato con Mau.',
    'corporate_values':'Permitir varios valores corporativos; confirmar si conviene lista libre o chips.',
    'secondary_business_activities':'Permitir actividades secundarias múltiples sin cambiar el modelo principal único.',
    'secondary_asset_classes':'Clases de activos secundarias múltiples; confirmar alternativas.',
    'historical_asset_classes':'Clases históricas múltiples; no confundirlas con oferta actual.',
    'amenities':'Varias amenidades pueden coexistir; confirmar opciones y alternativa libre.',
    'parking_and_storage':'Estacionamientos y depósitos pueden coexistir; no aplica debe ser exclusivo.',
    'key_differentiators':'Varios diferenciadores del Project; confirmar contrato de lista y longitud mínima.',
}

# Review-only examples of UI choices, not extracted or approved Company facts.
PROPOSED_OPTIONS = {
    'corporate_values':['Integrity','Transparency','Customer focus','Sustainability','Other (free text)'],
    'secondary_business_activities':QUESTION_CATALOG['primary_business_model']['options'] + ['Other (free text)'],
    'secondary_asset_classes':QUESTION_CATALOG['core_asset_classes']['options'] + ['Other (free text)'],
    'historical_asset_classes':QUESTION_CATALOG['core_asset_classes']['options'] + ['Other (free text)'],
    'amenities':['Gym','Pool','Shared outdoor space','Coworking','Other (free text)'],
    'parking_and_storage':['Parking spaces','Storage units','Bike parking','Other (free text)'],
    'corporate_differentiators':['Free-text list, retaining the current examples'],
    'key_differentiators':['Free-text list, retaining the current examples and reviewing minimum length'],
}


def question_inventory():
    rows=[]
    for scope,fields in [('Company',COMPANY_FIELDS),('Project',PROJECT_FIELDS)]:
        for field in fields:
            question=build_next_question([{'field':field.key,'label':field.label,'requirement':field.requirement,'status':'missing'}],final_prompt='Review profile')
            current=question['input_type']
            proposed='multi_select' if field.key in PROPOSED_MULTIPLE else current
            rows.append({'scope':scope,'field':field.key,'label':field.label,'requirement':field.requirement,
                         'current_input_type':current,'current_options':question['options'],'current_examples':question['examples'],
                         'current_cardinality':'multiple' if current=='multi_select' else 'single_or_text' if current in {'text','long_text','url','single_select','conditional_text'} else 'structured',
                         'suggested_input_type':proposed,'suggested_options':PROPOSED_OPTIONS.get(field.key,question['options'] or question['examples']),
                         'reason':PROPOSED_MULTIPLE.get(field.key,'Mantener el contrato actual; Mau puede confirmar o proponer otro.'),
                         'mau_decision':'','review_status':'pending_mau_approval','runtime_changed_by_proposal':False})
    return rows


def inventory_markdown():
    lines=['# Inventario de preguntas · revisión con Mau', '',
           'Propuestas pendientes: este documento no activa cambios de cardinalidad. Completar Decisión Mau (mantener / única / múltiple / texto) y observaciones antes de implementar nuevas conversiones.', '',
           'Las alternativas propuestas son ejemplos para decidir la interfaz, no información extraída ni características confirmadas de ninguna Company o Project.', '',
           'Las opciones «Provide later» y «Not applicable» son acciones exclusivas, no datos comerciales. Los editores de catálogo, ubicación, equipo y Meta conservan sus formularios estructurados.', '']
    for scope in ('Company','Project'):
        lines += ['## '+scope,'','| Campo / pregunta | Tipo actual | Opciones y ejemplos actuales | Tipo sugerido | Alternativas sugeridas (no activas) | Motivo | Decisión Mau |','|---|---|---|---|---|---|---|']
        for row in question_inventory():
            if row['scope']!=scope:continue
            choices=' · '.join(row['current_options'] + row['current_examples']) or 'Respuesta libre / editor estructurado'
            suggested=' · '.join(row['suggested_options']) or 'Conservar respuesta libre / editor'
            values=[row['field']+' — '+row['label'],row['current_input_type'],choices,row['suggested_input_type'],suggested,row['reason'],'Pendiente']
            lines.append('| '+' | '.join(value.replace('|','\\|').replace('\n',' ') for value in values)+' |')
        lines.append('')
    return '\n'.join(lines)+'\n'
