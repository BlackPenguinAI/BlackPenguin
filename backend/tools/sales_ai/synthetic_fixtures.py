"""Synthetic-only commercial fixtures. Never seed an application/production database."""
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

VERSION = 'sales-synthetic-company/1.0'
COMPANY_NAME = 'SYNTHETIC - Penguin Sales Laboratory'
PROJECTS = [
    {'key':'harbor', 'name':'SYNTHETIC Harbor Gardens', 'timezone':'America/New_York',
     'properties':[
         {'key':'bay','name':'Bay Residence','bedrooms':4,'bathrooms':3,'area':240,
          'price':780000,'available':3,'gallery':True,'pdf':True,'features':['Two covered parking spaces','Private garden']}]},
    {'key':'cedar','name':'SYNTHETIC Cedar Heights','timezone':'America/Chicago',
     'properties':[
         {'key':'loft','name':'Cedar Loft','bedrooms':2,'bathrooms':2,'area':110,
          'price':325000,'available':5,'gallery':True,'pdf':False,'features':['One parking space','Balcony']},
         {'key':'studio','name':'Cedar Studio','bedrooms':1,'bathrooms':1,'area':52,
          'price':210000,'available':2,'gallery':False,'pdf':True,'features':['Shared rooftop terrace']}]},
    {'key':'sierra','name':'SYNTHETIC Sierra Commons','timezone':'America/Denver',
     'properties':[
         {'key':'ridge','name':'Ridge Townhome','bedrooms':3,'bathrooms':2.5,'area':165,
          'price':460000,'available':4,'gallery':False,'pdf':False,'features':['Private patio']},
         {'key':'summit','name':'Summit Villa','bedrooms':4,'bathrooms':3,'area':220,
          'price':620000,'available':0,'gallery':True,'pdf':True,'features':['Two-car garage']},
         {'key':'valley','name':'Valley Apartment','bedrooms':2,'bathrooms':2,'area':95,
          'price':None,'available':None,'gallery':False,'pdf':False,'features':[]}]},
]


def identifier(name):
    return str(uuid5(NAMESPACE_URL, VERSION + ':' + name))


def brochure(project, item):
    """A small real PDF, generated without new runtime dependencies."""
    lines = ['SYNTHETIC TEST MATERIAL - NOT A REAL OFFER', project['name'], item['name'],
             f"Bedrooms: {item['bedrooms']} / Bathrooms: {item['bathrooms']} / Area: {item['area']} m2",
             f"Starting price: {item['price']} USD" if item['price'] is not None else 'Price not confirmed',
             'Features: ' + ', '.join(item['features']),
             'This brochure is not approved as photo or floor-plan coverage.']
    def esc(v):return v.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    content=('BT /F1 12 Tf 45 760 Td ' + ' 0 -24 Td '.join('('+esc(v)+') Tj' for v in lines) + ' ET').encode('ascii')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream']
    result=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(result));result+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(result);result+=b'xref\n0 6\n0000000000 65535 f \n'
    result+=b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets[1:])
    return result+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def illustration(project, item, index):
    from PIL import Image, ImageDraw
    image=Image.new('RGB',(640,360),(225,235,240));draw=ImageDraw.Draw(image)
    draw.text((24,20),'SYNTHETIC TEST IMAGE - NOT A REAL PROPERTY',fill='black')
    draw.text((24,45),project['name']+' / '+item['name'],fill='black')
    draw.rectangle((80,110,550,290),outline=(30,65,95),width=5)
    draw.polygon([(60,110),(315,65),(570,110)],fill=(45,90,120))
    for x in (120,230,410):draw.rectangle((x,155,x+55,215),fill=(120,175,205),outline='black')
    draw.rectangle((310,200,365,290),fill=(130,100,75))
    draw.text((24,325),f'Illustration {index}. No visual feature assertions are approved.',fill='black')
    output=BytesIO();image.save(output,format='PNG');return output.getvalue()


def seed(db, export_root):
    """Private worker only. Explicitly reject any non-SQLite bind."""
    if db.get_bind().dialect.name != 'sqlite':
        raise PermissionError('Synthetic fixtures require a private SQLite database.')
    from app.modules.companies.models import Company
    from app.modules.users.models import User, UserRole
    from app.modules.projects.models import (Project, ProjectProfile, ProjectPropertyType,
        ProjectOnboardingSource, ProjectPropertyTypeMedia, ProjectSalesAsset, ProjectSourceKind, ProjectSourceStatus)
    from app.modules.projects.completion import FIELDS
    from app.modules.projects.services import complete_onboarding
    from app.modules.projects.storage_service import store_project_file
    from app.modules.projects.property_resource_service import save_gallery, read_resource
    from app.modules.projects.sales_asset_service import approve
    company=Company(id=identifier('company'),name=COMPANY_NAME,country_code='US',timezone='UTC',is_active=True)
    if db.query(Company).count():raise PermissionError('Synthetic seed requires an empty private database.')
    db.add(company);db.flush()
    user=User(id=identifier('reviewer'),company_id=company.id,email='reviewer@synthetic.invalid',
        hashed_password='DISABLED-SYNTHETIC-NOT-A-LOGIN',role=UserRole.ADMIN,is_active=False)
    db.add(user);db.flush()
    manifest={'version':VERSION,'synthetic_only':True,'company_id':company.id,'company_name':COMPANY_NAME,'projects':[]}
    root=Path(export_root);root.mkdir(parents=True,exist_ok=True)
    def source(project,name,content,mime,kind):
        sid=identifier(project.id+name)
        stored=store_project_file(company_id=company.id,project_id=project.id,source_id=sid,original_filename=name,content=content)
        row=ProjectOnboardingSource(id=sid,project_id=project.id,kind=kind,status=ProjectSourceStatus.READY,
            name=name,original_filename=name,mime_type=mime,size_bytes=len(content),storage_path=stored.relative_path,
            content_hash=stored.content_hash,is_encrypted=True,encryption_key_id=stored.encryption_key_id)
        db.add(row);db.flush();return row
    for number,spec in enumerate(PROJECTS,1):
        project=Project(id=identifier(spec['key']),company_id=company.id,name=spec['name'],is_demo=True,
            demo_template_version="sales-lab-v1:"+spec["key"],timezone=spec['timezone'],country='US',city='Synthetic City',
            address=f'{number} Synthetic Avenue',onboarding_status='in_progress')
        db.add(project);db.flush()
        facts={'project_name':spec['name'],'project_type':'Synthetic residential development',
            'short_description':'Fictional residential catalog for isolated sales-agent evaluation.',
            'country':'US','city':'Synthetic City','timezone':spec['timezone'],'exact_address':project.address,
            'sales_authorization':True,'payment_methods':['Cash','Bank financing'],
            'amenities':['Shared garden','Residents lounge'],'delivery_dates':'December 2027'}
        states={f.key:{'status':'not_applicable' if f.requirement=='conditionally_required' else 'confirmed',
            'applicable':f.requirement!='conditionally_required'} for f in FIELDS if f.requirement in {'required','conditionally_required'}}
        states.update({k:{'status':'confirmed','applicable':True} for k in facts})
        profile=ProjectProfile(id=identifier(spec['key']+':profile'),project=project,profile_data=facts,field_states=states)
        db.add(profile)
        entry={k:spec[k] for k in ('key','name','timezone')};entry.update(id=project.id,properties=[])
        for order,item in enumerate(spec['properties']):
            prop=ProjectPropertyType(id=identifier(spec['key']+':'+item['key']),project=project,name=item['name'],
                bedrooms=item['bedrooms'],bathrooms=item['bathrooms'],area_min=item['area'],area_max=item['area'],area_unit='m²',
                starting_price=item['price'],currency='USD' if item['price'] is not None else None,
                available_units=item['available'],features=item['features'],review_status='confirmed',sort_order=order,
                inventory_updated_at=datetime.utcnow(),images_status='provided' if item['gallery'] else 'not_available',
                description='Synthetic property for testing. Only the listed features are confirmed.')
            db.add(prop);db.flush();resources=[]
            if item['gallery']:
                for index in (1,2):
                    image=source(project,item['key']+f'-{index}.png',illustration(spec,item,index),'image/png',ProjectSourceKind.IMAGE)
                    db.add(ProjectPropertyTypeMedia(property_type_id=prop.id,source_id=image.id,sort_order=index,
                        caption=f'Synthetic illustration {index} - not a real property'))
                db.flush();db.expire(prop,['media'])
                gallery=save_gallery(db,project,prop,accessible=True,channels=['sms','whatsapp'],user_id=user.id)
                resources.append(('gallery',gallery))
            if item['pdf']:
                pdf=source(project,item['key']+'.pdf',brochure(spec,item),'application/pdf',ProjectSourceKind.UPLOADED_FILE)
                asset=ProjectSalesAsset(company_id=company.id,project_id=project.id,property_type_id=prop.id,
                    source_id=pdf.id,asset_type='brochure',content_tags=['brochure'],display_name=item['name']+' synthetic brochure',
                    allowed_channels=['sms','whatsapp'],approval_status='draft')
                db.add(asset);db.flush();approve(db,asset,user_id=user.id);resources.append(('pdf',asset))
            card={**item,'id':prop.id,'resources':[]}
            for kind,asset in resources:
                content,mime,_=read_resource(asset.source)
                relative=f"{spec['key']}/{item['key']}."+('html' if kind=='gallery' else 'pdf')
                destination=root/relative;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(content)
                card['resources'].append({'kind':kind,'asset_id':asset.id,'path':relative,'mime_type':mime,'sha256':sha256(content).hexdigest()})
            entry['properties'].append(card)
        db.commit();complete_onboarding(db,project,user.id);db.commit()
        entry['approved_revision']=project.profile.published_snapshot['revision']
        manifest['projects'].append(entry)
    return manifest
