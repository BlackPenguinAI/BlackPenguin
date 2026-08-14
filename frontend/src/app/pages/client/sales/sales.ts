import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { RouterModule } from '@angular/router';
import { forkJoin } from 'rxjs';
import { API_V1_URL } from '../../../core/config/api.config';
@Component({selector:'app-sales',standalone:true,imports:[CommonModule,FormsModule,RouterModule],templateUrl:'./sales.html',styleUrls:['./sales.scss']})
export class SalesComponent implements OnInit{
 projects:any[]=[];meetings:any[]=[];leads:any[]=[];brokers:any[]=[];projectId='';loading=true;saving=false;selected:any=null;month=new Date();
 constructor(private http:HttpClient,private cdr:ChangeDetectorRef){}
 ngOnInit():void{this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe(rows=>{this.projects=rows;this.projectId=rows.find(p=>p.is_demo)?.id||rows[0]?.id||'';this.reload();});}
 reload():void{if(!this.projectId){this.loading=false;return}this.loading=true;forkJoin({meetings:this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/meetings`),leads:this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/leads-report`),brokers:this.http.get<any[]>(`${API_V1_URL}/brokers/${this.projectId}/brokers`)}).subscribe({next:data=>{this.meetings=data.meetings;this.leads=data.leads;this.brokers=data.brokers;this.selected=this.meetings[0]||null;this.loading=false;this.cdr.markForCheck();},error:()=>{this.loading=false;this.cdr.markForCheck();}});}
 get days():Date[]{const start=new Date(this.month.getFullYear(),this.month.getMonth(),1);const grid=new Date(start);grid.setDate(1-start.getDay());return Array.from({length:42},(_,i)=>new Date(grid.getFullYear(),grid.getMonth(),grid.getDate()+i));}
 meetingsFor(day:Date):any[]{return this.meetings.filter(m=>new Date(m.meeting_time).toDateString()===day.toDateString());}
 move(delta:number):void{this.month=new Date(this.month.getFullYear(),this.month.getMonth()+delta,1);}
 save():void{if(!this.selected)return;this.saving=true;this.http.put<any>(`${API_V1_URL}/sales/meetings/${this.selected.id}`,{broker_id:this.selected.broker_id,status:this.selected.status,confirmation_status:this.selected.confirmation_status}).subscribe({next:row=>{Object.assign(this.selected,row);this.saving=false;this.cdr.markForCheck();},error:()=>{this.saving=false;this.cdr.markForCheck();}});}
 count(status:string):number{return this.meetings.filter(m=>m.status===status).length;}
}
