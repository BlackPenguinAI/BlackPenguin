"""Validate local release evidence references. Never deploy or send a message.

This checks document completeness/integrity, not the truth of a provider receipt
or a person's authorization. Final independent operator review is always required.
"""
import argparse,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID

REQUIRED=('real_model_evaluation','postgres_parallel','desktop_mobile','configuration_review',
    'backup_restore_check','rollback_plan_review','live_sms','live_whatsapp','lead_delivery_receipts',
    'current_64_case_registry','sales_queue_progress','inactivity_episode',
    'calendar_booking','calendar_replacement','calendar_cancellation','sales_notification','manual_control_and_resume')
SHA=re.compile(r'^[0-9a-f]{40}$');DIGEST=re.compile(r'^[0-9a-f]{64}$')


def template():
    return {'version':'sales-release-checklist/1.0','candidate_commit':None,'authorization':{'approved':False,'operator':None,'environment':None,'company_id':None,'project_id':None,'test_contact_reference':None,'channels':[],'expires_at':None},
        'components':{key:None for key in ['api_commit','worker_commit','frontend_commit','alembic_head','configuration_sha256']},
        'checks':{key:{'status':'pending','candidate_commit':None,'reviewed_by':None,'reviewed_at':None,'evidence':[]} for key in REQUIRED}}


def file_digest(root,reference):
    if not isinstance(reference,dict) or set(reference)!={'path','sha256'}:return False
    if not isinstance(reference['path'],str) or Path(reference['path']).is_absolute() or not isinstance(reference['sha256'],str) or not DIGEST.fullmatch(reference['sha256']):return False
    file=(root/reference['path']).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file() or file.stat().st_size>50*1024*1024:return False
    digest=hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()==reference['sha256']


def assess(value,evidence_root,now=None):
    now=now or datetime.now(timezone.utc);blockers=[]
    if value.get('version')!='sales-release-checklist/1.0':blockers.append('unsupported_checklist_version')
    candidate=value.get('candidate_commit')
    if not isinstance(candidate,str) or not SHA.fullmatch(candidate):blockers.append('candidate_commit_missing_or_invalid')
    auth=value.get('authorization') or {}
    if auth.get('approved') is not True or not auth.get('operator') or not auth.get('environment'):blockers.append('explicit_environment_authorization_missing')
    for field in ['company_id','project_id']:
        try:
            if str(UUID(auth[field]))!=auth[field]:raise ValueError()
        except (KeyError,ValueError,TypeError,AttributeError):blockers.append('authorization_'+field+'_missing_or_invalid')
    if set(auth.get('channels') or [])!={'sms','whatsapp'}:blockers.append('both_channels_not_authorized')
    if not file_digest(evidence_root,auth.get('test_contact_reference')):blockers.append('authorized_test_contact_record_missing_or_changed')
    try:
        expiry=datetime.fromisoformat(auth['expires_at'].replace('Z','+00:00'))
        if expiry.tzinfo is None or expiry<=now:raise ValueError()
    except (KeyError,ValueError,TypeError,AttributeError):blockers.append('authorization_expired_or_missing')
    components=value.get('components') or {}
    for field in ['api_commit','worker_commit','frontend_commit']:
        if components.get(field)!=candidate or not isinstance(candidate,str) or not SHA.fullmatch(candidate):blockers.append(field+'_does_not_match_candidate')
    if components.get('alembic_head')!='20261109_sales_worker_progress':blockers.append('migration_head_unverified')
    if not isinstance(components.get('configuration_sha256'),str) or not DIGEST.fullmatch(components['configuration_sha256']):blockers.append('published_configuration_unverified')
    for key in REQUIRED:
        check=(value.get('checks') or {}).get(key) or {}
        if check.get('status')!='passed':blockers.append(key+':not_passed');continue
        if check.get('candidate_commit')!=candidate:blockers.append(key+':evidence_for_another_commit')
        try:
            reviewed=datetime.fromisoformat(check['reviewed_at'].replace('Z','+00:00'))
            if reviewed.tzinfo is None or reviewed>now:raise ValueError()
        except (KeyError,ValueError,TypeError,AttributeError):blockers.append(key+':review_time_missing_or_invalid')
        if not check.get('reviewed_by'):blockers.append(key+':reviewer_missing')
        refs=check.get('evidence') or []
        if not isinstance(refs,list) or not 1<=len(refs)<=10 or not all(file_digest(evidence_root,r) for r in refs):blockers.append(key+':evidence_missing_or_changed')
    return {'version':'sales-release-checklist-result/1.0','status':'BLOCKED' if blockers else 'DOCUMENTS_COMPLETE_OPERATOR_REVIEW_REQUIRED',
        'blockers':sorted(set(blockers)),'external_actions':0,'deployment_authorized':False,'independent_provider_verification':False,
        'limitation':'Hashes prove referenced local bytes only. An operator must independently verify recipient authorization, actual receipts, database/Calendar effects and deployment scope.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path);parser.add_argument('--evidence-root',type=Path,default=Path('.'));parser.add_argument('--output',type=Path,required=True);parser.add_argument('--template',action='store_true');args=parser.parse_args(argv)
    if args.input and args.input.resolve()==args.output.resolve():parser.error('Keep evidence input unchanged')
    if args.template:result=template()
    else:
        if not args.input:parser.error('Provide --input or --template')
        result=assess(json.loads(args.input.read_text()),args.evidence_root)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('template_created' if args.template else result['status'])
    return 0 if args.template or result['status']!='BLOCKED' else 2


if __name__=='__main__':raise SystemExit(main())
