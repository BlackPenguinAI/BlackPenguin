"""Exact, expiring material proposals and backend-only share issuance for the new cohort."""
from datetime import datetime, timedelta, timezone
import hashlib
import re
from .execution import now as workflow_now
from app.modules.projects import sales_asset_service, asset_share_service, storage_service
from app.modules.projects.models import Project, ProjectPropertyType, ProjectSourceStatus
from .commercial_context import _safe_asset_links
from .dialogue_tasks import restricted
from .turn_configuration import digest

VERSION = 'sales-material-proposal/1.0'
MAX_FILE_BYTES = 50 * 1024 * 1024


def customer_label(value):
    # Resource names are also runtime data; a URL in a name is not a share action.
    return re.sub(r'https?://\S+|\bwww\.\S+','resource',str(value),flags=re.I).strip() or 'Approved material'


def snapshot(asset, *, channel, target_url=None):
    from app.modules.projects.asset_coverage import valid,approved
    from .execution import channel as execution_channel
    channel = execution_channel(channel)
    """Validate actual local bytes, scope and reviewed metadata; never fetch external URLs."""
    source = asset.source
    now = datetime.utcnow()
    if (not valid(asset) or not approved(asset) or
        channel not in (asset.allowed_channels or []) or
        asset.valid_from and asset.valid_from > now or asset.valid_until and asset.valid_until <= now or
        not source or source.project_id != asset.project_id or source.status != ProjectSourceStatus.READY or
        not asset.project or asset.project.company_id != asset.company_id or
        asset.property_type_id and (not asset.property_type or asset.property_type.project_id != asset.project_id or asset.property_type.review_status != 'confirmed')):
        raise ValueError('Material approval or scope is no longer valid.')
    content_sha256 = None
    if target_url:
        if target_url not in {row['url'] for row in _safe_asset_links(asset)}:
            raise ValueError('The approved resource URL changed.')
    else:
        if not source.storage_path:
            raise ValueError('The requested file is missing.')
        path = storage_service.resolve_project_file(source.storage_path)
        # Fernet adds framing and base64 overhead. Keep the decrypted limit
        # authoritative so an allowed 40 MB gallery can still be shared.
        disk_limit=MAX_FILE_BYTES*4//3+1024 if source.is_encrypted else MAX_FILE_BYTES
        if not path.is_file() or not 0 < path.stat().st_size <= disk_limit:
            raise ValueError('The requested file is unavailable or exceeds the read limit.')
        content = storage_service.read_project_file(source.storage_path, encrypted=bool(source.is_encrypted))
        if not content or len(content) > MAX_FILE_BYTES:
            raise ValueError('The requested file is empty or exceeds the read limit.')
        content_sha256 = hashlib.sha256(content).hexdigest()
        if source.content_hash and content_sha256 != source.content_hash:
            raise ValueError('The approved file failed its integrity check.')
    payload = {'asset_id': asset.id, 'version': asset.version, 'source_id': source.id,
        'company_id': asset.company_id, 'project_id': asset.project_id, 'property_type_id': asset.property_type_id,
        'approved_at': asset.approved_at.isoformat(), 'name': asset.display_name,
        'tags': asset.content_tags or [asset.asset_type], 'type': asset.asset_type,
        'description': asset.description, 'allowed_channels': asset.allowed_channels,
        'valid_from': str(asset.valid_from), 'valid_until': str(asset.valid_until),
        'storage_path': source.storage_path if not target_url else None,
        'mime_type': source.mime_type, 'content_sha256': content_sha256, 'target_url': target_url}
    if asset.coverage is not None:payload['coverage']=asset.coverage
    return {**payload, 'sha256': digest(payload)}


def same_snapshot(asset, binding, channel):
    try:
        return snapshot(asset, channel=channel, target_url=binding.get('target_url')) == binding
    except (ValueError, OSError):
        return False


def accepted_proposal(db, conversation, previous_meta, text, outcome):
    from .service import _affirmative_slot_reply
    proposal = previous_meta.get('material_offer')
    if not proposal:
        return None, None
    resolved=[row['value'] for row in outcome.plan.get('references',{}).values()
        if row.get('status')=='resolved' and row.get('value',{}).get('kind')=='material']
    ids={row['id'] for row in resolved}
    offered_ids=set(proposal.get('asset_ids') or [])
    by_reference=bool(ids and ids<=offered_ids)
    if not _affirmative_slot_reply(text) and not by_reference:
        return None, None
    # A yes must answer one complete backend proposal, not a second question.
    if any(previous_meta.get(k) for k in ('appointment_offer', 'location_offer', 'release_offer', 'qualification_offer', 'control_confirmation')):
        return None, 'Please tell me which material you want to receive.'
    from .turn_context import latest_outbound
    from .reference_resolution import accepted, offers_for_turn
    from .dialogue_store import load, Scope
    latest = latest_outbound(db, conversation.id, skip_language_holds=True)
    scope = Scope(conversation.company_id, conversation.project_id, conversation.id, conversation.lead_id)
    current = offers_for_turn(db, conversation, load(db, scope)[1])
    if (not latest or not accepted(latest) or (latest.metadata_json or {}).get('material_offer') != proposal or
        not any(o.kind == 'material' and o.message_id == latest.id and o.status == 'current' for o in current)):
        return None, 'That material offer was not fully sent. Please request the material again.'
    try:
        expiry = datetime.fromisoformat(proposal['expires_at'])
        valid = (proposal['version'] == VERSION and expiry > workflow_now(datetime).replace(tzinfo=timezone.utc) and
            proposal['scope'] == scope.__dict__ and bool(proposal['items']))
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        return None, 'That material offer has expired or changed. Please request the material again.'
    if by_reference:
        proposal={**proposal,'items':[i for i in proposal['items'] if i['binding']['asset_id'] in ids]}
    return proposal, None


def deliver(db, scope, conversation, lead, run, outcome, previous_meta):
    from app.modules.projects.asset_coverage import matches as covered, unrestricted
    from .sales_policy import policy_context,compliance_action_holds
    from .commercial_context import confirmed_profile_facts
    holds=compliance_action_holds(policy_context(db,scope,confirmed_profile_facts(db.get(Project,scope.project_id).profile)))
    from .conversation_scope import scoped_messages_query
    inbound = scoped_messages_query(db, conversation).filter_by(id=run.input_snapshot['message_id'], role='user', direction='inbound').one()
    proposal, error = accepted_proposal(db, conversation, previous_meta, inbound.content, outcome)
    tasks = {t.id: t for t in outcome.state.tasks}
    approved = {a.id: a for a in sales_asset_service.approved_for_turn(db, project_id=scope.project_id,
        company_id=scope.company_id, channel=conversation.channel)}
    selections, pending, unavailable = [], [], []
    gap_subjects=set()
    bindings = []
    if error:
        return [], [], None, error, set(), bindings
    material_tasks = [t for t in tasks.values() if t.source_message_id == inbound.id and t.topic.value == 'materials'
        and t.status not in {'cancelled', 'completed'} and not restricted(outcome.state, t)]
    refs=outcome.plan.get('references') or {}
    def named_assets(task):
        request_ids=set(task.request_ids)
        linked=[refs.get(r.reference_id,{}).get('value',{}) for r in outcome.state.last_understanding.requests
            if r.id in request_ids and r.reference_id]
        return {v['id'] for v in linked if v.get('kind')=='material'}
    from .service import _affirmative_slot_reply
    accepted_ids=set(proposal['asset_ids']) if proposal else set()
    proposal_tasks=[t for t in material_tasks if proposal and (_affirmative_slot_reply(inbound.content) or named_assets(t)&accepted_ids)]
    if proposal:
        if not proposal_tasks:
            return [], [], None, 'I have kept your material restrictions. Please clarify what you want to receive.', set(), bindings
        for item in proposal['items']:
            asset = approved.get(item['binding']['asset_id'])
            targets=item.get('targets') or []
            if not targets or any(restricted(outcome.state, task.model_copy(update={
                    'property_id':target['property_id'],'unit_id':target['unit_id'],'subject':target['subject']}))
                    for target in targets for task in proposal_tasks):
                return [], [], None, 'I have kept your material restrictions. Please clarify what you want to receive.', set(), bindings
            if not asset or not unrestricted(asset,outcome.state,holds=holds) or not same_snapshot(asset, item['binding'], conversation.channel):
                # Atomic acceptance of the exact proposal: no substitution or partial replacement.
                return [], [], None, 'The offered material has changed or is unavailable. No replacement file was selected. Please request the material again.', set(), bindings
            coverage=item.get('coverage') or ''
            selections.append((asset, item['binding'], {t.id for t in proposal_tasks}, 'requested_tag' if coverage.startswith('complement_') else coverage))
    for result in outcome.results:
        task = tasks.get(result.operation_id)
        if task not in material_tasks or task in proposal_tasks:
            continue
        named=named_assets(task)
        for material in result.data.get('materials', []):
            asset = approved.get(material['asset_id'])
            if not asset:
                continue
            if named and asset.id not in named:
                continue
            # A property-bound material never silently becomes material for another property.
            if not unrestricted(asset,outcome.state,subject=task.subject,holds=holds):continue
            if asset.coverage is None and asset.property_type_id and task.property_id != asset.property_type_id:
                continue
            targets = ([None] if asset.source and asset.source.storage_path else [])
            targets += [row['url'] for row in material.get('links', []) if row['kind'] == task.subject]
            usable = False
            for target in dict.fromkeys(targets):
                try:
                    binding = snapshot(asset, channel=conversation.channel, target_url=target)
                except (ValueError, OSError):
                    continue
                usable = True
                item = (asset, binding, {task.id}, material.get('coverage'))
                if material.get('coverage') == 'requested_tag':
                    selections.append(item)
                else:
                    pending.append(item)
            if not usable:
                unavailable.append(task.id)
    # A genuine material gap keeps the conversation open and offers useful,
    # approved alternatives for the same target, never an automatic handoff.
    for task in material_tasks:
        if task in proposal_tasks or task.binding_status=='unresolved':continue
        if any(task.id in item[2] for item in [*selections,*pending]):continue
        gap_subjects.add((task.subject or 'material').replace('_',' '))
        for asset in approved.values():
            if not unrestricted(asset,outcome.state,holds=holds):continue
            rows=covered(asset,property_id=task.property_id,unit_id=task.unit_id)
            if not rows:continue
            allowed={s for row in rows for s in row['content_tags']}
            if not allowed & {'brochure','gallery_image','floor_plan','unit_sheet','virtual_tour','location_map','amenities'}:continue
            targets=([None] if asset.source and asset.source.storage_path else [])
            targets += [row['url'] for row in _safe_asset_links(asset) if row['kind'] in allowed or row['kind']=='photos' and 'gallery_image' in allowed]
            for target in dict.fromkeys(targets):
                try:binding=snapshot(asset,channel=conversation.channel,target_url=target)
                except (ValueError,OSError):continue
                pending.append((asset,binding,{task.id},'alternative_'+str(task.subject or 'material')))
    # De-duplicate exact targets, retaining each fulfilled task. AND/OR already resolved by the planner.
    unique = {}
    for asset, binding, tids, coverage in selections:
        key = binding['sha256']
        if key not in unique:
            unique[key] = [asset, binding, set(), coverage]
        unique[key][2].update(tids)
    links, share_ids, fulfilled = [], [], set()
    for asset, binding, tids, coverage in unique.values():
        # The same immutable binding is rechecked immediately before issue and at dispatch/access.
        if not same_snapshot(asset, binding, conversation.channel):
            unavailable.extend(tids)
            continue
        url, share = asset_share_service.issue(db, company_id=scope.company_id, project_id=scope.project_id,
            lead_id=scope.lead_id, source_id=asset.source_id, sales_asset_id=asset.id,
            channel=conversation.channel, agent_run_id=run.id, target_url=binding['target_url'])
        label = customer_label(asset.display_name)
        if not binding['target_url'] and asset.coverage is not None:
            targets=[{'property_id':tasks[tid].property_id,'unit_id':tasks[tid].unit_id,'subject':tasks[tid].subject} for tid in tids]
            targets += [t for i in (proposal or {}).get('items',[]) if i['binding']==binding for t in i.get('targets',[])]
            pages=sorted({p for target in targets for row in covered(asset,property_id=target['property_id'],unit_id=target['unit_id'],subject=target['subject']) for p in row['pages']})
            if pages:label+=' (reviewed pages '+', '.join(map(str,pages[:8]))+(' and additional pages' if len(pages)>8 else '')+'; opens the whole file)'
        if coverage != 'requested_tag':
            label += ' (related material; requested coverage is not confirmed)'
        links.append(f'{label}: {url}')
        share_ids.append(share.id)
        fulfilled.update(tids)
        replaced=[tid for item in (proposal or {}).get('items',[]) if item['binding']==binding for tid in item.get('task_ids',[])]
        bindings.append({'share_id': share.id, 'binding': binding, 'replaces_task_ids':replaced,
                         'fulfillment':'approved_alternative' if str(coverage).startswith('alternative_') else 'requested_resource'})
    # Offer the complementary resource only AFTER a directly requested resource
    # was issued. The offer is an exact immutable proposal; no extra file is sent.
    if links and not proposal:
        for task in material_tasks:
            companion={'photos':'floor_plan','floor_plan':'photos'}.get(task.subject)
            if not companion or task.id not in fulfilled:continue
            if any(t.subject==companion for t in material_tasks):continue
            for asset in approved.values():
                if not unrestricted(asset,outcome.state,subject=companion,holds=holds):continue
                if restricted(outcome.state,task.model_copy(update={'subject':companion})):continue
                coverage_rows=covered(asset,property_id=task.property_id,unit_id=task.unit_id,subject=companion)
                if not any(r['coverage']=='requested_tag' for r in coverage_rows):continue
                targets=([None] if asset.source and asset.source.storage_path else [])
                targets += [r['url'] for r in _safe_asset_links(asset) if r['kind']==companion]
                for target in targets:
                    try:binding=snapshot(asset,channel=conversation.channel,target_url=target)
                    except (ValueError,OSError):continue
                    if binding['sha256'] in unique:continue
                    pending.append((asset,binding,{task.id},'complement_'+companion))
    # Offered alternatives are exact file/resource snapshots, not a list rediscovered on yes.
    offered = {}
    for asset, binding, tids, coverage in pending:
        if binding['sha256'] not in unique:
            row=offered.setdefault(binding['sha256'],{'binding':binding,'coverage':coverage,
                'property_id':asset.property_type_id,'task_ids':[],'targets':[],'content_types':[]})
            row['task_ids']=sorted(set(row['task_ids']) | (set() if coverage.startswith('complement_') else tids))
            for tid in sorted(tids):
                target={'property_id':tasks[tid].property_id,'unit_id':tasks[tid].unit_id,
                        'subject':coverage.removeprefix('complement_') if coverage.startswith('complement_') else tasks[tid].subject}
                if target not in row['targets']:row['targets'].append(target)
                contents=[tag for covered_row in covered(asset,property_id=target['property_id'],unit_id=target['unit_id']) for tag in covered_row['content_tags']]
                row['content_types']=list(dict.fromkeys([*row['content_types'],*contents]))
    offer, question = None, ''
    if offered:
        items = list(offered.values())
        offer = {'version': VERSION, 'scope': scope.__dict__,
            'expires_at': (workflow_now(datetime).replace(tzinfo=timezone.utc) + timedelta(minutes=30)).isoformat(),
            'items': items, 'asset_ids': list(dict.fromkeys(i['binding']['asset_id'] for i in items))}
        names = ', '.join(customer_label(i['binding']['name'])+(' ('+', '.join('photos' if t=='gallery_image' else t.replace('_',' ') for t in i.get('content_types',[]))+')' if i.get('content_types') else '') for i in items)
        unit = any(i.get('coverage') == 'type_only_unit_unconfirmed' for i in items)
        complementary=all(i.get('coverage','').startswith('complement_') for i in items)
        alternatives=all(i.get('coverage','').startswith('alternative_') for i in items)
        missing=', '.join(dict.fromkeys(i['coverage'].removeprefix('alternative_').replace('_',' ') for i in items))
        kind='floor plans' if all(i.get('coverage')=='complement_floor_plan' for i in items) else 'photos' if all(i.get('coverage')=='complement_photos' for i in items) else 'related materials'
        question = (f'The requested {missing} is not available in an approved resource for this option. I can offer {names} as related material. Would you like me to share it?' if alternatives else
            f'I also have approved {kind} for this option. Would you like me to share them?' if complementary else
            f'I have {names} as related Project or property type material. Coverage for the specific unit is not confirmed. Would you like those materials?'
            if unit else f'I have {names}. It may contain useful related information, but the requested photo coverage is not confirmed. Would you like that file?')
        if gap_subjects and not alternatives:question='I could not confirm the requested '+', '.join(sorted(gap_subjects))+' for this option. '+question
    elif links and gap_subjects:
        question='I could not verify an approved '+', '.join(sorted(gap_subjects))+' resource for this option.'
    elif unavailable or material_tasks and not links:
        subjects=', '.join(dict.fromkeys((t.subject or 'material').replace('_',' ') for t in material_tasks))
        question = f'I could not verify an approved, accessible {subjects} resource for this option. What property detail would help you next?'
    for tid in fulfilled:
        tasks[tid].status = 'awaiting_user'  # Completion follows the durable provider receipt.
    return links, share_ids, offer, question, fulfilled, bindings


def validate_shares(db, scope, shares, metadata, *, subset=False):
    from app.modules.projects.models import ProjectSalesAsset
    expected = {row['share_id']: row['binding'] for row in metadata.get('material_bindings', [])}
    if not subset and len(expected) != len(shares):
        return False
    for share in shares:
        binding = expected.get(share.id)
        asset = db.get(ProjectSalesAsset, share.sales_asset_id)
        if asset:
            db.refresh(asset)
            if asset.source:db.refresh(asset.source)
        if (not binding or not asset or share.company_id != scope.company_id or share.project_id != scope.project_id or
            share.lead_id != scope.lead_id or share.source_id != binding['source_id'] or share.target_url != binding['target_url'] or
            share.revoked or share.expires_at <= datetime.utcnow() or not same_snapshot(asset, binding, share.channel)):
            return False
    return True
