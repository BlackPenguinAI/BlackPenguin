// Local build and mocked API only. Exercises real browser geometry and navigation.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../../dist/frontend/browser');
if(!fs.existsSync(path.join(root,'index.html')))throw Error('Build the frontend first');
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png'};
(async()=>{
 const server=http.createServer((req,res)=>{
  const name=path.resolve(root,'.'+decodeURIComponent(new URL(req.url,'http://localhost').pathname));
  if(!name.startsWith(root+path.sep)&&name!==root){res.writeHead(404);return res.end();}
  const file=fs.existsSync(name)&&fs.statSync(name).isFile()?name:path.join(root,'index.html');
  res.setHeader('Content-Type',types[path.extname(file)]||'application/octet-stream');fs.createReadStream(file).pipe(res);
 });
 let browser;
 try{
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  const origin=`http://127.0.0.1:${server.address().port}`;
  browser=await chromium.launch({headless:true,executablePath:process.env.BP_CHROME||'/usr/bin/chromium'});
  for(const width of [1440,900,390]){
   const ctx=await browser.newContext({viewport:{width,height:900}}),page=await ctx.newPage();
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.addInitScript(()=>{localStorage.setItem('bp_token','offline.'+btoa(JSON.stringify({exp:Math.floor(Date.now()/1000)+3600}))+'.offline');localStorage.setItem('bp_role','admin');});
   const completion={percentage:100,required_fields_complete:true,ready_for_confirmation:false,can_finalize:false,can_complete:true,final_approved:true,completed:0,total:0,remaining:0,sections:[],blockers:[],finalization_blockers:[],sales_activation_status:'not_ready',sales_activation_blockers:[],draft_revision:1,published_revision:1};
   const profile={id:'profile',project_id:'project',project_name:'Navigation QA',data:{country:'US',city:'Miami',timezone:'America/New_York'},fields:[],completion,ui_deferrals:{},updated_at:null};
   const catalog={items:[{id:'type-1',project_id:'project',name:'Residence',code:null,description:'Saved',features:[],media:[],images_status:'deferred',review_status:'confirmed',available_units:2,starting_price:100,currency:'USD',sort_order:0}],confirmed_count:1,candidate_count:0,limit:20,remaining:19,catalog_complete:true};
   const q=task=>({task,field:({catalog:'property_type_catalog',location:'country',delivery:'delivery_dates',parking:'parking_and_storage',team:'sales_contacts',meta_account:'campaigns_defined',meta_assets:'campaigns_defined'})[task]||null,input_type:({catalog:'property_type_catalog',location:'location_editor',delivery:'detail_editor',parking:'detail_editor',team:'project_sales_team',meta_account:'meta_lead_setup',meta_assets:'meta_lead_setup',documents:'documents'})[task]||'boolean',label:task,prompt:'Review this section.',options:[],examples:[],allow_custom:false,minimum_words:null});
   let revision=0;
   const messages=Array.from({length:25},(_,i)=>({id:'history-'+i,sender:'ai',created_at:'2026-11-01T00:00:00Z',content:'Saved conversation history. '.repeat(12),attachments:[],ui_payload:null}));
   let next=q('review');
   await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),p=url.pathname;
    if(p.includes('/api/v1/')){
     let body=[];
     if(p.endsWith('/users/me'))body={id:'user',role:'admin',first_name:'QA',last_name:'Operator',company_name:'QA Company'};
     else if(p.endsWith('/notifications/unread-count'))body={count:0};
     else if(p.endsWith('/chat/state'))body={version:revision+1,messages,sources:[],profile,next_question:next,stage:'conversation'};
     else if(p.includes('/editor/')){
      const task=p.split('/').pop(),data=req.postDataJSON();revision++;next=q(task);
      messages.forEach(m=>{if(m.ui_payload&&!m.response_payload)m.response_payload={status:'superseded',answer:''};});
      const user={id:data.client_message_id,sender:'user',content:data.message,created_at:'2026-11-09T00:00:00Z',attachments:[]};
      const message={id:'task-'+revision,sender:'ai',content:next.prompt,created_at:user.created_at,attachments:[],ui_payload:next};messages.push(user,message);
      profile.ui_deferrals.__editor_focus__={deferred:false,draft:{active_task:task,revision}};
      body={message,user_message:user,profile,sources:[],next_question:next};
     }else if(p.endsWith('/property-types'))body=catalog;
     else if(p.endsWith('/meta/setup-state'))body={project_id:'project',account_status:'not_connected',routing_status:'not_linked',authorizations:[],missing_permissions:[],mappings:[]};
     else if(p.includes('/meta/setup-config'))body={oauth_enabled:false,manual_fallback_enabled:false};
     else if(p.endsWith('/location'))body={country:'US',city:'Miami',timezone:'America/New_York',source:'Saved location',countries:[{code:'US',name:'United States'}],cities:[{country:'US',city:'Miami',timezone:'America/New_York'}]};
     return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    }
    return url.origin===origin?route.continue():route.abort();
   });
   await page.goto(origin+'/app/projects/project/onboarding');
   const chat=page.getByTestId('onboarding-chat-scroll');await chat.waitFor();
   for(const label of ['Property types','Location / timezone','Delivery dates','Parking / storage','Meta account','Campaigns / forms','Assign team','Add documents']){
    if(width<1280)await page.getByRole('button',{name:'Project review',exact:true}).click();
    const switched=page.waitForResponse(r=>r.url().includes('/editor/'));
    await page.locator('nav[aria-label="Project review tasks"]').getByRole('button',{name:label,exact:true}).click();
    await switched;await page.waitForFunction(text=>document.querySelector('[data-testid=active-editor-status]')?.textContent.includes(text),label);
    assert.equal(await page.locator('.active-review-task').count(),1);
    assert.ok(await page.getByTestId('active-editor-status').textContent().then(t=>t.includes(label)));
    await chat.evaluate(el=>{el.scrollTop=el.scrollHeight;});
    const geometry=await page.evaluate(()=>{const footer=document.querySelector('[data-testid="onboarding-composer"]').getBoundingClientRect();return {bottom:footer.bottom,height:innerHeight,outer:document.documentElement.scrollHeight,main:document.querySelector('main').scrollTop};});
    assert.ok(Math.abs(geometry.bottom-geometry.height)<6,JSON.stringify(geometry));
    assert.ok(geometry.outer<=geometry.height+2,JSON.stringify(geometry));assert.equal(geometry.main,0);
   }
   assert.deepEqual(errors,[]);console.log(`PASS ${width}px: eight editors, one active task, stable composer, contained scrolling`);
   await ctx.close();
  }
 }finally{if(browser)await browser.close();await new Promise(ok=>server.close(ok));}
})().catch(error=>{console.error(error);process.exitCode=1;});
