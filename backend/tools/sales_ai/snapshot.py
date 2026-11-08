"""Validate a diagnostic snapshot and extract approved commercial test data.

No application settings, database, network, names or contact data are loaded.
Only the explicit fields below may cross into a checked-in catalog fixture.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

BASE_COMMIT = 'f7e7f055fd0499f2224b43bad8f9128db2eaf434'
CATALOG_VERSION = 'sales-ai-catalog/1.0'
FACT_FIELDS = set('''project_name project_type project_status short_description exact_address
city country timezone location_references phases_and_towers typologies areas bedrooms_and_bathrooms
construction_details amenities parking_and_storage currency starting_price payment_methods
promotions delivery_dates available_inventory sales_authorization target_audience value_proposition
key_differentiators qualification_rules sales_contacts appointment_routing compliance_notes'''.split())
TYPE_FIELDS = '''id project_id name code description bedrooms bathrooms area_min area_max area_unit
total_units available_units starting_price maximum_price currency features inventory_updated_at
images_status review_status sort_order created_at updated_at'''.split()
UNIT_FIELDS = '''id project_id unit_code typology tower_or_phase area bedrooms bathrooms list_price
currency status inventory_updated_at created_at updated_at'''.split()
SOURCE_FIELDS = '''id project_id kind status mime_type size_bytes is_encrypted has_stored_file
sharing_intent'''.split()
ASSET_FIELDS = '''id company_id project_id property_type_id source_id asset_type content_tags
display_name description approval_status version valid_from valid_until allowed_channels approved_at
created_at updated_at'''.split()
USER_FIELDS = 'id company_id role auth_status is_active timezone deleted_at'.split()
ASSIGNMENT_FIELDS = '''id project_id user_id responsibility sales_enabled marketing_enabled
accepts_appointments is_primary routing_weight accepts_new_leads is_active created_at updated_at'''.split()
WINDOW_FIELDS = 'id user_id weekday start_time end_time timezone is_active'.split()
BLOCK_FIELDS = 'id user_id starts_at ends_at timezone'.split()


def pick(row, fields):
    return {key: row.get(key) for key in fields}


def read_snapshot(path: Path):
    """Require every table footer/count and a final completion marker."""
    opener = gzip.open if path.suffix == '.gz' else open
    rows, counts, ends, manifest, complete = defaultdict(list), Counter(), {}, None, None
    with opener(path, 'rt', encoding='utf-8') as stream:
        for index, line in enumerate(stream):
            record = json.loads(line)
            kind = record.get('kind')
            if index == 0:
                if kind != 'manifest':
                    raise ValueError('Snapshot must begin with its manifest.')
                manifest = record
                continue
            if complete is not None:
                raise ValueError('Records follow the completion marker.')
            if kind == 'row':
                table = record['table']
                if table in ends or not isinstance(record.get('data'), dict):
                    raise ValueError('Invalid row or row after table footer.')
                rows[table].append(record['data'])
                counts[table] += 1
            elif kind == 'table_end':
                table = record['table']
                if table in ends or counts[table] != record['row_count'] or record['row_count'] != record['snapshot_count']:
                    raise ValueError('Table count or duplicate footer mismatch.')
                ends[table] = record['row_count']
            elif kind == 'complete':
                complete = record
            else:
                raise ValueError('Unknown snapshot record kind.')
    if not manifest or not complete or ends != complete.get('row_counts'):
        raise ValueError('Incomplete snapshot.')
    expected = {t for t, info in manifest.get('schema', {}).items() if info.get('present')}
    if set(ends) != expected or sum(counts.values()) != complete.get('total_rows'):
        raise ValueError('Snapshot schema/total mismatch.')
    for table, items in rows.items():
        ids = [r['id'] for r in items if r.get('id') is not None]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate source IDs: '+table)
    return manifest, dict(rows), complete


def build_catalog(manifest, rows, *, project_ids=(), snapshot_sha256=None):
    projects = {r['id']: r for r in rows.get('projects', [])}
    selected = set(project_ids) if project_ids else set(projects)
    if not selected or not selected.issubset(projects):
        raise ValueError('Choose existing project IDs.')
    companies = {r['id']: r for r in rows.get('companies', [])}
    profiles = {r['project_id']: r for r in rows.get('project_profiles', [])}
    sources = {r['id']: r for r in rows.get('project_onboarding_sources', [])}
    output = []
    for pid in sorted(selected):
        project = projects[pid]
        if project['company_id'] not in companies:
            raise ValueError('Project company is missing.')
        profile = profiles.get(pid)
        if not profile:
            raise ValueError('Project profile is missing.')
        published = profile.get('published_snapshot')
        if published and (not isinstance(published, dict) or published.get('profile_id') != profile['id']
                          or published.get('company_id') != project['company_id'] or not isinstance(published.get('states'), dict)):
            raise ValueError('Published snapshot scope is invalid.')
        if not published and not profile.get('final_approved'):
            raise ValueError('No approved catalog; a draft is not a test sales fact.')
        data = published.get('data', {}) if published else profile.get('profile_data') or {}
        states = published['states'] if published else profile.get('field_states') or {}
        confirmed = {key: value for key, value in data.items() if key in FACT_FIELDS
                     and states.get(key, {}).get('status') in {'confirmed', 'corrected_by_user'}
                     and states.get(key, {}).get('applicable', True) is not False}
        types = published.get('property_types', []) if published else [r for r in rows.get('project_property_types', []) if r.get('project_id') == pid and r.get('review_status') == 'confirmed']
        units = published.get('units', []) if published else [r for r in rows.get('project_units', []) if r.get('project_id') == pid]
        if any(r.get('project_id') != pid for r in [*types, *units]):
            raise ValueError('Published catalog contains another project.')
        assets = []
        source_map=(published.get('sources') if published else profile.get('field_sources')) or {}
        fact_provenance={}
        for key in confirmed:
            raw_source=source_map.get(key)
            fact_provenance[key]={'approved_revision':published.get('revision') if published else None,
                                  'source':pick(raw_source,['source_id','source_ids','kind','source_kind','page']) if isinstance(raw_source,dict) else None}
        for asset in rows.get('project_sales_assets', []):
            if asset.get('project_id') != pid:
                continue
            if asset.get('company_id') != project['company_id']:
                raise ValueError('Material belongs to another company.')
            if asset.get('property_type_id') and asset['property_type_id'] not in {t['id'] for t in types}:
                raise ValueError('Material does not reference an approved property in this project.')
            source = sources.get(asset.get('source_id'))
            if source and source.get('project_id') != pid:
                raise ValueError('Material source belongs to another project.')
            assets.append({**pick(asset, ASSET_FIELDS), 'source': pick(source, SOURCE_FIELDS) if source else None,
                           'content_verified': False, 'resource_in_sandbox': 'SYNTHETIC_PLACEHOLDER_ONLY'})
        output.append({
            'origin': 'EXPORTED_DEMO' if project.get('is_demo') else 'REAL_APPROVED',
            'project': pick(project, 'id company_id name address city country timezone is_active is_demo onboarding_status'.split()),
            'approval': {'profile_id': profile['id'], 'source': 'published_snapshot' if published else 'legacy_final_approved',
                         'revision': published.get('revision') if published else None,
                         'profile_updated_at': profile.get('updated_at'), 'draft_revision': profile.get('draft_revision'),
                         'approved_for_sales_at': profile.get('approved_for_sales_at'),
                         'sales_authorization_withdrawn': (profile.get('profile_data') or {}).get('sales_authorization') is False},
            'facts': confirmed, 'field_states': {k: pick(states[k], ['status','applicable']) for k in confirmed},
            'fact_provenance':fact_provenance,
            'property_types': [pick(r, TYPE_FIELDS) for r in types], 'units': [pick(r, UNIT_FIELDS) for r in units],
            'materials': assets,
        })
    company_ids = {p['project']['company_id'] for p in output}
    assignments = [pick(r, ASSIGNMENT_FIELDS) for r in rows.get('project_user_assignments', []) if r.get('project_id') in selected]
    assigned_ids={a['user_id'] for a in assignments}
    users = [pick(r, USER_FIELDS) for r in rows.get('users', []) if r.get('company_id') in company_ids and r.get('id') in assigned_ids]
    user_ids = {u['id'] for u in users}
    if any(a['user_id'] not in user_ids for a in assignments):
        raise ValueError('Assignment references an out-of-scope user.')
    configs=[r for r in rows.get('ai_configurations',[]) if r.get('company_id') is None]
    config=configs[0] if len(configs)==1 else None
    published_versions=[r for r in rows.get('prompt_versions',[]) if r.get('company_id') is None and r.get('agent_key')=='sales' and r.get('is_published')]
    published_version=published_versions[0] if len(published_versions)==1 else None
    return {
        'version': CATALOG_VERSION, 'mode': 'OFFLINE_FIXTURE_ONLY',
        'captured_at': manifest.get('generated_at'), 'source_commit': manifest.get('app_commit_sha'),
        'source_snapshot_sha256': snapshot_sha256, 'projects': output, 'specialists': users, 'assignments': assignments,
        'source_configuration':{'id':config.get('id') if config else None,
                                'model':(config.get('agent_ventas') or {}).get('model') if config else None,
                                'updated_at':config.get('updated_at') if config else None,
                                'published_version':published_version.get('version_number') if published_version else None,
                                'published_at':published_version.get('published_at') if published_version else None},
        'weekly_availability': [pick(r, WINDOW_FIELDS) for r in rows.get('sales_availability_windows', []) if r.get('user_id') in user_ids],
        'dated_availability': [pick(r, BLOCK_FIELDS) for r in rows.get('sales_availability_blocks', []) if r.get('user_id') in user_ids],
        'missing': ['Real document contents', 'Meta form commercial answers', 'Existing appointments', 'External Calendar free/busy'],
    }


def from_file(path, *, project_ids=()):
    path = Path(path)
    manifest, rows, _ = read_snapshot(path)
    return build_catalog(manifest, rows, project_ids=project_ids, snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project-id', action='append', default=[])
    args = parser.parse_args()
    catalog = from_file(args.snapshot, project_ids=args.project_id)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+'\n')
    print(f"catalog_fixture: {len(catalog['projects'])} projects; external_actions=0")
