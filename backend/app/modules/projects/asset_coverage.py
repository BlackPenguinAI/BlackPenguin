"""Reviewed content/target associations. Never derive coverage from filenames/text."""
from fastapi import HTTPException
from .models import ProjectPropertyType, ProjectUnit

TAGS={'brochure','floor_plan','unit_sheet','price_list','amenities','location_map','virtual_tour','legal_disclaimer','gallery_image','other'}
SUBJECT_TAG={'photos':'gallery_image'}
CONTENT_TOPICS={'price_list':'pricing','amenities':'amenities','location_map':'location'}


def approved(asset):
    # Older runtimes select only 'approved'; they must not ignore new targeting.
    return bool(asset.approved_at and asset.approval_status == ('approved_targeted' if asset.coverage is not None else 'approved'))


def validate(db,project,coverage,tags,*,source=None,approved=False,verify_pages=True):
    if coverage is None:return None
    if not isinstance(coverage,list) or len(coverage)>100:
        raise HTTPException(422,'Review at most 100 material coverage entries.')
    if approved and not coverage:raise HTTPException(409,'Choose at least one reviewed material target before approval.')
    rows=[];seen={}
    for raw in coverage:
        if not isinstance(raw,dict) or set(raw)-{'property_type_id','unit_id','content_tags','pages','summary'}:
            raise HTTPException(422,'Invalid material coverage entry.')
        pid,uid=raw.get('property_type_id'),raw.get('unit_id')
        if any(v is not None and (not isinstance(v,str) or not v or len(v)>36) for v in (pid,uid)):raise HTTPException(422,'Use a valid material target identifier.')
        if pid and uid:raise HTTPException(422,'Choose either a property type or an individual unit per entry.')
        signature=(pid,uid)
        target=db.query(ProjectPropertyType).filter_by(id=pid,project_id=project.id).first() if pid else db.query(ProjectUnit).filter_by(id=uid,project_id=project.id).first() if uid else None
        if (pid or uid) and not target:raise HTTPException(404,'A material target does not belong to this Project.')
        if approved and pid and target.review_status!='confirmed':raise HTTPException(409,'Confirm every covered property type before approval.')
        contents=raw.get('content_tags') or []
        if not isinstance(contents,list) or not contents or any(not isinstance(t,str) or t not in TAGS or t not in tags for t in contents):
            raise HTTPException(422,'Coverage content must be a reviewed content type of this material.')
        if set(contents) & seen.get(signature,set()):raise HTTPException(422,'Combine repeated content for this target in one entry.')
        seen.setdefault(signature,set()).update(contents)
        pages=raw.get('pages') or []
        if not isinstance(pages,list) or len(pages)>100 or any(type(p) is not int or p<1 or p>5000 for p in pages):
            raise HTTPException(422,'Use positive PDF page numbers (up to 100 per entry).')
        if pages and (not source or source.mime_type!='application/pdf'):raise HTTPException(422,'Page references require a PDF source.')
        summary=raw.get('summary') or ''
        if not isinstance(summary,str) or len(summary)>500 or '://' in summary or '?' in summary:
            raise HTTPException(422,'Use a short factual coverage description without links or questions.')
        rows.append({'property_type_id':pid or None,'unit_id':uid or None,'content_tags':list(dict.fromkeys(contents)),
                     'pages':sorted(set(pages)),'summary':summary.strip()})
    if any(not r['property_type_id'] and not r['unit_id'] for r in rows) and any(r['property_type_id'] or r['unit_id'] for r in rows):
        raise HTTPException(422,'Use either Project-wide coverage or named targets, not both.')
    if approved and verify_pages and any(r['pages'] for r in rows):
        from io import BytesIO
        from pypdf import PdfReader
        from .storage_service import read_project_file
        try:
            count=len(PdfReader(BytesIO(read_project_file(source.storage_path,encrypted=bool(source.is_encrypted)))).pages)
        except Exception as exc:raise HTTPException(422,'The PDF page references could not be verified.') from exc
        if any(p>count for r in rows for p in r['pages']):raise HTTPException(422,'A page reference exceeds the PDF page count.')
    return rows


def valid(asset):
    """Late scope validation, including deleted targets: never broaden NULL FKs."""
    from sqlalchemy.orm import object_session
    if asset.coverage is None:return True
    db=object_session(asset)
    if not db or not asset.project:return False
    try:
        validate(db,asset.project,asset.coverage,asset.content_tags or [asset.asset_type],source=asset.source,approved=True,verify_pages=False)
        return True
    except (HTTPException,TypeError,ValueError,AttributeError):return False


def entries(asset):
    return asset.coverage if asset.coverage is not None else [dict(property_type_id=asset.property_type_id,unit_id=None,
        content_tags=asset.content_tags or [asset.asset_type],pages=[],summary='')]


def matches(asset,*,property_id=None,unit_id=None,subject=None):
    rows=entries(asset);tag=SUBJECT_TAG.get(subject,subject)
    selected=[]
    for row in rows:
        pid,uid=row.get('property_type_id'),row.get('unit_id')
        if uid and uid!=unit_id or pid and pid!=property_id:continue
        if not pid and not uid and asset.coverage is not None and (property_id or unit_id):
            pass  # An explicit Project-wide review may cover any option in this Project.
        tags=row.get('content_tags') or []
        direct=subject is None or tag in tags
        related=subject=='photos' and 'brochure' in tags
        if not direct and not related:continue
        coverage='requested_tag' if direct else 'possible_embedded_photos'
        if unit_id and not uid:coverage='type_only_unit_unconfirmed'
        selected.append({**row,'coverage':coverage})
    return selected


def unrestricted(asset,state,*,subject=None,holds=()):
    """An indivisible file must not smuggle an explicitly excluded covered target."""
    from app.modules.sales_agent.understanding_contract import Task
    from app.modules.sales_agent.dialogue_tasks import restricted
    for row in entries(asset):
        for tag in row.get('content_tags',[]):
            topic=CONTENT_TOPICS.get(tag)
            if not topic:continue
            if topic in holds:return False
            if restricted(state,Task(id='content-policy',topic=topic,status='pending',property_id=row.get('property_type_id'),unit_id=row.get('unit_id'))):return False
            if not row.get('property_type_id') and any(c.topic.value==topic for c in state.property_constraints):return False
        subjects=[{'gallery_image':'photos'}.get(t,t) for t in row.get('content_tags',[]) if t in {'gallery_image','floor_plan','brochure','unit_sheet','price_list','virtual_tour','location_map'}]
        if subject and subject not in subjects:subjects.append(subject)
        for s in subjects or [None]:
            task=Task(id='coverage',topic='materials',subject=s,status='pending',property_id=row.get('property_type_id'),unit_id=row.get('unit_id'))
            if restricted(state,task):return False
            if not row.get('property_type_id') and not row.get('unit_id') and any(c.topic.value=='materials' and (c.subject is None or s is None or c.subject==s) for c in state.property_constraints):return False
    return True
