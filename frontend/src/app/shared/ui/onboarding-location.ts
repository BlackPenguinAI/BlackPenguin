import { Component, Input, OnInit, Output, EventEmitter, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { API_V1_URL } from '../../core/config/api.config';
import { ConfigureLaterComponent, DeferredCards } from './configure-later/configure-later';

@Component({selector:'app-onboarding-location',standalone:true,imports:[CommonModule,FormsModule,ConfigureLaterComponent],styles:[`:host{display:block;max-width:48rem;margin:1rem 0}section{background:#101010;border-radius:1rem;padding:1.25rem}h3{font-size:1rem;font-weight:600}label{font-size:.8rem;color:#d1d5db}input,select{display:block;width:100%;margin-top:.4rem;border:1px solid #ffffff26;border-radius:.65rem;background:#080808;color:#fff;padding:.7rem}.structured-primary{background:#e5aa00;color:#050505;border-radius:.65rem;padding:.7rem 1rem;font-weight:600;margin-top:.8rem}.structured-primary:disabled{opacity:.4}p{line-height:1.6}`],template:
`<section class="rounded-xl border border-white/20 p-4 space-y-3" data-testid="location-editor">
<h3>Country, city and timezone</h3><p class="text-xs text-gray-400">{{options?.source}}. Suggestions are not approved automatically.</p>
<label class="block">Country<select class="secure-input w-full" [(ngModel)]="country" (ngModelChange)="countryChanged()"><option value="">Choose country</option><option *ngFor="let item of options?.countries" [value]="item.code">{{item.name}}</option></select></label>
<label class="block">City<input class="secure-input w-full" [(ngModel)]="city" (ngModelChange)="cityChanged()" [attr.list]="'location-cities-'+entityId" placeholder="Choose a suggested city or enter another city"><datalist [id]="'location-cities-'+entityId"><option *ngFor="let item of cities" [value]="item.city"></option></datalist></label>
<label class="block">IANA timezone<select class="secure-input w-full" [(ngModel)]="timezone"><option value="">Choose timezone (required if the city is ambiguous)</option><option *ngFor="let zone of zones" [value]="zone">{{zoneLabel(zone)}}</option></select></label>
<button type="button" (click)="showAllZones=!showAllZones">Choose another timezone</button><p class="text-xs text-gray-400">Offsets reflect today and may change seasonally. Other cities are supported: enter the city and explicitly choose its timezone. Existing appointments will not move. Project changes require profile approval.</p>
<button type="button" class="structured-primary" (click)="save()" [disabled]="busy || !country || !city.trim() || !timezone">Confirm location</button>
<app-configure-later [scope]="scope" [entityId]="entityId" card="field:country" label="Country, city and timezone" [draft]="{country:country,city:city,timezone:timezone}" [blocked]="busy" [records]="records" (saved)="deferred.emit($event)"></app-configure-later>
<p role="status">{{message}}</p></section>`})
export class OnboardingLocationComponent implements OnInit {
 @Input() scope:'company'|'project'='project'; @Input() entityId='';
 @Input() records:DeferredCards={};
 @Output() deferred=new EventEmitter<DeferredCards>();
 @Output() saved=new EventEmitter<void>();
 options:any=null;country='';city='';timezone='';busy=false;message='';
 constructor(private http:HttpClient,private cdr:ChangeDetectorRef){}
 get url(){return API_V1_URL+'/onboarding-editor/'+this.scope+'/'+encodeURIComponent(this.entityId)+'/location';}
 ngOnInit(){if(this.entityId)this.http.get<any>(this.url).subscribe({next:v=>{this.options=v;const draft=this.records['field:country']?.draft;for(const key of ['country','city','timezone'] as const)this[key]=typeof draft?.[key]==='string' ? draft[key] : String(v[key] || '');this.cdr.markForCheck();},error:()=>{this.message='Could not load location suggestions. Retry by reopening this review.';this.cdr.markForCheck();}});}
 get cities():Array<any>{return (this.options?.cities || []).filter((i:any)=>i.country===this.country);}
 showAllZones=false;
 get zones():string[]{
   const all=[...new Set<string>(this.cities.map(i=>i.timezone))].sort();
   const matches=[...new Set<string>(this.cities.filter(i=>this.normalizeCity(i.city)===this.normalizeCity(this.city)).map(i=>i.timezone))];
   return !this.showAllZones && matches.length ? matches : all;
 }
 normalizeCity(value:string):string {return value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase().trim().replace(/,.*$/,'');}
 zoneLabel(zone:string):string {
   try {const parts=new Intl.DateTimeFormat('en',{timeZone:zone,timeZoneName:'long'}).formatToParts(new Date());
     const offset=new Intl.DateTimeFormat('en',{timeZone:zone,timeZoneName:'longOffset'}).formatToParts(new Date()).find(p=>p.type==='timeZoneName')?.value || '';
     return (parts.find(p=>p.type==='timeZoneName')?.value || zone)+' · '+zone+' · '+offset.replace('GMT','UTC');
   }catch{return zone;}
 }
 countryChanged(){this.showAllZones=false;this.city='';this.timezone='';}
 cityChanged(){const match=[...new Set<string>(this.cities.filter(i=>this.normalizeCity(i.city)===this.normalizeCity(this.city)).map(i=>i.timezone))];this.timezone=match.length===1?match[0]:'';this.showAllZones=false;}
 save(){if(this.busy)return;this.busy=true;this.message='';this.http.post<any>(this.url,{country:this.country,city:this.city.trim(),timezone:this.timezone}).subscribe({next:v=>{this.busy=false;this.message=v.message;this.saved.emit();this.cdr.markForCheck();},error:e=>{this.busy=false;this.message=typeof e.error?.detail==='string'?e.error.detail:'Location was not saved. Please retry; your selection remains.';this.cdr.markForCheck();}});}
}

