import { Component,Input,Output,EventEmitter,OnChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ConfigureLaterComponent,DeferredCards,restoreDraft } from './configure-later/configure-later';

export interface DeliveryRow {scope:string;reference:string;timing:string;precision:'month'|'date';}
@Component({selector:'app-onboarding-detail-editor',standalone:true,imports:[CommonModule,FormsModule,ConfigureLaterComponent],
styles:[`:host{display:block;max-width:48rem;margin:1rem 0}section{border:1px solid #ffffff26;background:#101010;border-radius:1rem;padding:1.25rem}h2{font-size:1rem;font-weight:600}p,label{font-size:.8rem;color:#d1d5db;line-height:1.5}label{display:block;margin:.7rem 0}input,select,textarea{display:block;box-sizing:border-box;width:100%;margin-top:.4rem;border:1px solid #ffffff26;border-radius:.6rem;background:#080808;color:white;padding:.65rem}button{border:1px solid #ffffff26;border-radius:.6rem;padding:.65rem .8rem;margin:.5rem .5rem 0 0;font-size:.8rem}button.primary{background:#e5aa00;color:black;font-weight:600}button:disabled{opacity:.4}.row{border-top:1px solid #ffffff26;margin-top:1rem;padding-top:.5rem}.grid{display:grid;gap:.5rem}@media(min-width:640px){.grid{grid-template-columns:1fr 1fr}}`],
template:`<section><h2>{{field==='delivery_dates'?'Delivery dates and scope':'Parking and storage'}}</h2>
<p *ngIf="previousText">Previously recorded: {{previousText}}</p>
<p>Enter confirmed details only. Leave unknown facts blank or complete this review later.</p>
<ng-container *ngIf="field==='delivery_dates';else parkingForm"><p>A date may apply to the whole Project, a phase, a property type or a specific unit. A month does not imply an exact day.</p>
<div class="row" *ngFor="let row of deliveries;let index=index"><div class="grid">
<label>Applies to<select [(ngModel)]="row.scope" [disabled]="busy"><option value="">Choose scope</option><option value="project">Whole Project</option><option value="phase">Phase / building</option><option value="property_type">Property type</option><option value="unit">Individual unit</option></select></label>
<label *ngIf="row.scope && row.scope!=='project'">Exact name or code<input [(ngModel)]="row.reference" [disabled]="busy" maxlength="150" placeholder="Identify the phase, type or unit"></label>
<label>Precision<select [(ngModel)]="row.precision" (ngModelChange)="row.timing=''" [disabled]="busy"><option value="month">Month and year</option><option value="date">Exact date</option></select></label>
<label>Delivery<input [type]="row.precision==='date'?'date':'month'" [(ngModel)]="row.timing" [disabled]="busy"></label></div>
<button type="button" *ngIf="deliveries.length>1" (click)="deliveries.splice(index,1)" [disabled]="busy">Remove date</button></div>
<button type="button" (click)="addDate()" [disabled]="busy || deliveries.length>=100">Add another delivery date</button></ng-container>
<ng-template #parkingForm><label>Applies to<input [(ngModel)]="parking['applies_to']" [disabled]="busy" maxlength="150" placeholder="Project, phase or exact property type"></label>
<div class="grid"><label *ngFor="let item of parkingFields">{{item.label}}<textarea [(ngModel)]="parking[item.key]" [disabled]="busy" rows="2" [maxlength]="item.key==='conditions'?2000:1000" placeholder="Confirmed quantity, inclusion or conditions"></textarea></label></div>
<button type="button" (click)="notApplicable.emit()" [disabled]="busy">Not applicable</button></ng-template>
<div class="row"><p *ngIf="error" role="alert">{{error}}</p><button type="button" class="primary" (click)="submit()" [disabled]="busy || !valid">{{busy?'Saving…':'Save details and continue'}}</button>
<app-configure-later scope="project" [entityId]="entityId" [card]="'field:'+field" [label]="field==='delivery_dates'?'Delivery dates':'Parking and storage'" [draft]="{deliveries:deliveries,parking:parking}" [blocked]="busy" [records]="records" (saved)="deferred.emit($event)"></app-configure-later></div>
</section>`})
export class OnboardingDetailEditor implements OnChanges {
 @Input() field='';@Input() entityId='';@Input() currentValue:unknown=null;@Input() busy=false;@Input() error='';@Input() records:DeferredCards={};
 @Output() saved=new EventEmitter<Record<string,unknown>>();@Output() deferred=new EventEmitter<DeferredCards>();@Output() notApplicable=new EventEmitter<void>();
 deliveries:DeliveryRow[]=[];parking:Record<string,string>={applies_to:'',garage:'',assigned_spaces:'',visitor_parking:'',storage:'',conditions:''};
 readonly parkingFields=[{key:'garage',label:'Garage'},{key:'assigned_spaces',label:'Assigned parking'},{key:'visitor_parking',label:'Visitor parking'},{key:'storage',label:'Storage'},{key:'conditions',label:'Included / optional, pricing and other conditions'}];
 private loaded='';
 ngOnChanges(){const key=JSON.stringify([this.field,this.currentValue,this.records['field:'+this.field]?.updated_at]);if(key===this.loaded)return;this.loaded=key;this.deliveries=[];
   const draft=this.records['field:'+this.field]?.draft;
   if(this.field==='delivery_dates'){
     if(Array.isArray(draft?.['deliveries']))this.deliveries=draft!['deliveries'].map((row:any)=>({...row}));
     else if(typeof this.currentValue==='string')this.deliveries=this.parseDates(this.currentValue);
     if(!this.deliveries.length)this.addDate();
   }else if(draft?.['parking'])restoreDraft(this.parking,draft['parking']);
   else if(typeof this.currentValue==='string'){
     const labels:Record<string,string>={'Applies to':'applies_to','Garage':'garage','Assigned spaces':'assigned_spaces','Visitor parking':'visitor_parking','Storage':'storage','Inclusion, pricing and conditions':'conditions'};
     for(const line of this.currentValue.split('\n')){const index=line.indexOf(':');const field=labels[line.slice(0,index)];if(field)this.parking[field]=line.slice(index+1).trim();}
   }
 }
 get previousText():string {
   const format=(value:unknown):string=>{
     if(value==null)return '';
     if(Array.isArray(value))return value.map(format).filter(Boolean).join('; ');
     if(typeof value==='object')return Object.entries(value).map(([key,item])=>key.replace(/_/g,' ')+': '+format(item)).join('; ');
     if(typeof value==='string' && /^[\[{]/.test(value.trim())){try{return format(JSON.parse(value));}catch{/* Keep legacy text readable. */}}
     return String(value);
   };return format(this.currentValue);
 }
 addDate(){this.deliveries.push({scope:'',reference:'',timing:'',precision:'month'});}
 parseDates(text:string):DeliveryRow[]{
   const months=['January','February','March','April','May','June','July','August','September','October','November','December'];const rows:DeliveryRow[]=[];
   for(const line of text.split('\n')){const m=/^(Project|Phase|Property type|Unit)(?:: (.+))? — ([A-Za-z]+) (?:(\d{2}), )?(\d{4})$/.exec(line);if(!m)continue;
     const month=months.indexOf(m[3])+1;if(!month)continue;const scope=({'Project':'project','Phase':'phase','Property type':'property_type','Unit':'unit'} as Record<string,string>)[m[1]];
     rows.push({scope,reference:m[2]||'',timing:m[5]+'-'+String(month).padStart(2,'0')+(m[4]?'-'+m[4]:''),precision:m[4]?'date':'month'});
   }return rows;
 }
 get valid(){return this.field==='delivery_dates'?this.deliveries.length>0&&this.deliveries.every(row=>!!row.scope&&!!row.timing&&(row.scope==='project'||!!row.reference.trim())):!!this.parking['applies_to'].trim()&&this.parkingFields.some(item=>!!this.parking[item.key].trim());}
 submit(){if(!this.valid||this.busy)return;this.saved.emit(this.field==='delivery_dates'?{field:this.field,deliveries:this.deliveries.map(({scope,reference,timing})=>({scope,reference:scope==='project'?'':reference,timing}))}:{field:this.field,parking:{...this.parking}});}
}
