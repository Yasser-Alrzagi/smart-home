'use strict';
(() => {
  const apiBase = document.body.dataset.api;
  let token = null;
  let generation = 0;
  let viewEpoch = 0;
  const state = { me: null, profile: null, policy: null, page: 'dashboard', offset: 0, current: null };
  const $ = id => document.getElementById(id);
  const roles = {'Student':'طالب','Student Affairs':'شؤون الطلاب','Housing Administration':'إدارة السكن','System Administrator':'مسؤول النظام','Maintenance Officer':'مسؤول الصيانة','Activity Officer':'مسؤول الأنشطة','Cleaning Officer':'مسؤول النظافة','Food Officer':'مسؤول التغذية','Sports Officer':'مسؤول الرياضة'};
  const statuses = {'Draft':'مسودة','Submitted':'تم التقديم','Under Review':'قيد المراجعة','Pending Documents':'بانتظار الاستكمال','Ready for Decision':'جاهز للقرار','Accepted':'مقبول','Rejected':'مرفوض'};
  const documents = {'National ID':'الهوية الوطنية','Enrollment Certificate':'إفادة القيد','University ID':'البطاقة الجامعية','Academic Transcript':'السجل الأكاديمي','Medical Certificate':'الشهادة الطبية','Other':'مستند إضافي'};
  const eventNames = {'application.created':'إنشاء الطلب','application.submitted':'تقديم الطلب','profile.updated':'تحديث الملف','document.uploaded':'رفع مستند','document.removed':'إزالة مستند','review.start':'بدء المراجعة','review.request_documents':'طلب استكمال مستندات','review.complete':'اكتمال مراجعة شؤون الطلاب','review.return_to_review':'إعادة إلى شؤون الطلاب','review.accept':'قبول الطلب','review.reject':'رفض الطلب'};
  const tr = value => statuses[value] || roles[value] || documents[value] || value || '—';
  const date = value => value ? new Date(value.endsWith('Z') ? value : value+'Z').toLocaleString('ar-YE', {dateStyle:'medium',timeStyle:'short'}) : '—';
  function h(tag, attrs={}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'checked' || key === 'disabled' || key === 'required') node[key] = value;
      else if (value !== undefined && value !== null) node.setAttribute(key, value);
    }
    for (const child of children.flat(Infinity)) if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return node;
  }
  function notify(text, failure=false) { const node=$('message'); node.hidden=false; node.className=failure?'failure':''; node.textContent=text; }
  function localLogout(message='') { generation++; viewEpoch++; token=null; state.me=null; state.current=null; state.profile=null; state.policy=null; state.filter=''; $('detailContent').replaceChildren(); if ($('detailDialog').open) $('detailDialog').close(); $('portal').hidden=true; $('loginView').hidden=false; $('page').replaceChildren(); $('loginError').textContent=message; }
  async function api(path, {method='GET', body, blob=false}={}) {
    const requestGeneration=generation;
    const headers={}; if(token) headers.Authorization='Bearer '+token;
    if(body && !(body instanceof FormData)) { headers['Content-Type']='application/json'; body=JSON.stringify(body); }
    const response=await fetch(apiBase+path,{method,headers,body,cache:'no-store',credentials:'omit'});
    if(requestGeneration!==generation) throw new Error('تغيرت الجلسة؛ تجاهلنا الاستجابة القديمة.');
    if(!response.ok) {
      let payload; try {payload=await response.json();} catch {payload={};}
      if(requestGeneration!==generation) throw new Error('تغيرت الجلسة.');
      let message=Array.isArray(payload.detail)?payload.detail.map(x=>x.msg).join(' · '):(payload.detail||'تعذر إكمال الطلب');
      if(response.status===401 && token) {localLogout('انتهت الجلسة أو أُبطلت. سجّل الدخول مجدداً.'); throw new Error('انتهت الجلسة');}
      if(response.status===429) message='محاولات كثيرة. انتظر '+(response.headers.get('Retry-After')||'قليلاً')+' ثانية ثم أعد المحاولة.';
      if(response.status===409) message='تغيّرت الحالة أو تعارضت العملية. حدّث البيانات قبل المحاولة. '+message;
      const error=new Error(message); error.status=response.status; throw error;
    }
    const result=blob?{data:await response.blob(), type:response.headers.get('Content-Type')}:response.status===204?null:await response.json();
    if(requestGeneration!==generation) throw new Error('تغيرت الجلسة.');
    return result;
  }
  function task(fn) {return async event=>{const button=event?.currentTarget; if(button?.tagName==='BUTTON') button.disabled=true; try {await fn(event);} catch(error){notify(error.message,true);} finally{if(button?.tagName==='BUTTON')button.disabled=false;}};}
  const button=(label,fn,kind='secondary')=>h('button',{type:'button',class:kind,onclick:task(fn)},label);
  const badge=status=>h('span',{class:'badge '+(status==='Accepted'?'accepted':status==='Rejected'?'rejected':['Pending Documents','Ready for Decision','Submitted','Under Review'].includes(status)?'waiting':'')},tr(status));
  const panel=(title,...content)=>h('section',{class:'panel'},h('div',{class:'panel-title'},h('h3',{},title)),...content);
  const field=(label,name,value='',type='text',attrs={})=>h('label',{},label,h('input',{name,type,value,required:true,...attrs}));
  const heading=(title,sub,action=null)=>h('div',{class:'page-head'},h('div',{},h('h1',{},title),h('p',{},sub)),action || h('span',{class:'date-label'},new Date().toLocaleDateString('ar-YE',{weekday:'long',day:'numeric',month:'long'})));
  function nav() {
    const items=state.me.must_change_password?[['security','◈','تغيير كلمة المرور']]:[['dashboard','⌂','لوحة المتابعة'],...(state.me.role==='Student'?[['profile','♙','ملفي الطلابي']]:[]),...(['Student','Student Affairs','Housing Administration'].includes(state.me.role)?[['applications','▤',state.me.role==='Student'?'طلبات السكن':'مراجعة الطلبات']]:[]),...(state.me.role==='System Administrator'?[['accounts','♧','إدارة الحسابات']]:[]),['security','◈','الأمان والجلسات']];
    $('navigation').replaceChildren(...items.map(([key,icon,label])=>buttonNav(key,icon,label)));
    $('identityName').textContent=state.me.username; $('identityRole').textContent=tr(state.me.role); $('avatar').textContent=state.me.username.slice(0,1);
  }
  function buttonNav(key,icon,label){return h('button',{type:'button',class:'nav-button'+(state.page===key?' active':''),onclick:()=>go(key)},h('span',{class:'nav-icon','aria-hidden':'true'},icon),label);}
  async function go(page) {
    const epoch=++viewEpoch;
    state.page=state.me.must_change_password?'security':page; state.offset=0; $('message').hidden=true; nav();
    $('pageLabel').textContent={dashboard:'لوحة المتابعة',profile:'الملف الطلابي',applications:'طلبات السكن',accounts:'إدارة الحسابات',security:'الأمان والجلسات'}[state.page];
    $('page').replaceChildren(h('div',{class:'empty'},'جارٍ تحميل البيانات…'));
    try { await ({dashboard,profile:profilePage,applications:applicationsPage,accounts:accountsPage,security:securityPage}[state.page])(); } catch(error){if(state.me && epoch===viewEpoch) $('page').replaceChildren(h('p',{class:'error'},error.message));}
  }
  $('loginForm').addEventListener('submit',async e=>{e.preventDefault(); const submit=e.target.querySelector('button');submit.disabled=true;$('loginError').textContent=''; const form=new FormData(e.target); try{const data=await api('/auth/login/access-token',{method:'POST',body:form});token=data.access_token;generation++;state.me=await api('/auth/users/me');e.target.reset();$('loginView').hidden=true;$('portal').hidden=false;state.policy=null;await go('dashboard');}catch(error){localLogout(error.message);}finally{submit.disabled=false;}});
  $('logoutButton').addEventListener('click',async()=>{const current=generation;try{await api('/auth/logout',{method:'POST'});}catch{}if(generation===current)localLogout();});
  $('closeDialog').addEventListener('click',()=>$('detailDialog').close());
  $('detailDialog').addEventListener('close',()=>{if(!state.me)return; const refresh=state.page==='applications'?applicationsPage:state.page==='dashboard'?dashboard:null; if(refresh)refresh().catch(e=>{if(state.me)notify(e.message,true);});});
  async function policy(){return state.policy || (state.policy=await api('/admissions/policy'));}
  async function fetchProfile(){try {state.profile=await api('/students/me');}catch(error){if(error.status===404)state.profile=null;else throw error;}return state.profile;}
  function stat(label,value,foot){return h('div',{class:'stat'},h('span',{class:'stat-label'},label),h('div',{class:'stat-value'},value),h('small',{},foot));}
  function renderPage(name, epoch, ...nodes) { if(state.me && state.page===name && viewEpoch===epoch) $('page').replaceChildren(...nodes); }
  async function dashboard(){const epoch=viewEpoch;if(state.page!=='dashboard'||!state.me)return;
    const user=state.me;
    if(!['Student','Student Affairs','Housing Administration'].includes(user.role)){
      renderPage('dashboard',epoch,heading('مرحباً، '+user.username,'حسابك ومساحة العمل المتاحة لدورك'),panel('مساحة العمل',h('p',{class:'muted'},user.role==='System Administrator'?'أنشئ حسابات الطلاب والموظفين من إدارة الحسابات. قرارات السكن خاصة بشؤون الطلاب وإدارة السكن.':'خدمات هذا الدور ستُضاف في دفعات لاحقة. يمكنك الآن إدارة حسابك وجلساتك.'),button(user.role==='System Administrator'?'إدارة الحسابات':'الأمان والجلسات',()=>go(user.role==='System Administrator'?'accounts':'security'),'primary')));return;
    }
    const p=await policy(); const list=await api('/applications?limit=5');
    const profile=user.role==='Student'?await fetchProfile():null;
    const latest=list.items[0]?await api('/applications/'+list.items[0].application_id):null;
    const requiredNow=[...new Set([...p.required_documents,...(latest?.requested_documents||[])])];
    const count=latest?.documents.filter(d=>d.available && requiredNow.includes(d.document_type)).length||0;
    const studentBanner=latest?.status==='Accepted'?['طلبك مقبول، والتسكين هو الخطوة التالية','اكتملت المراجعة والقرار. لا توجد غرفة مخصصة بعد في هذه الدفعة.']:latest?.status==='Ready for Decision'?['طلبك لدى إدارة السكن','اكتملت مراجعة شؤون الطلاب، وطلبك جاهز للقرار النهائي.']:latest?.status==='Pending Documents'?['طلبك يحتاج إلى استكمال','افتح التفاصيل لقراءة الملاحظات ورفع المستندات المطلوبة.']:latest?.status==='Rejected'?['صدر قرار على طلبك','افتح الطلب لقراءة السبب. يمكنك إنشاء طلب جديد بعد التصحيح.']:latest&&['Submitted','Under Review'].includes(latest.status)?['طلبك قيد المراجعة','ستظهر ملاحظات شؤون الطلاب والقرار النهائي في سجل الطلب.']:['خطوتك الأولى نحو سكنك الجامعي','أكمل ملفك وارفع الهوية الوطنية وإفادة القيد. البطاقة الجامعية اختيارية.'];
    const intro=heading('مرحباً، '+(profile?.full_name||user.username),'كل ما تحتاجه لمتابعة طلب السكن، في مكان واحد.');
    const welcome=h('div',{class:'banner'},h('div',{},h('h3',{},user.role==='Student'?studentBanner[0]:'طلبات واضحة، وقرارات موثّقة'),h('p',{},user.role==='Student'?studentBanner[1]:user.role==='Student Affairs'?'راجع المستندات، واطلب الاستكمال عند الحاجة، ثم أحل الطلب إلى إدارة السكن.':'تصدر القرارات بعد اكتمال مراجعة شؤون الطلاب فقط.')),button(user.role==='Student'?(profile?'متابعة طلباتي':'إكمال ملفي'):'فتح قائمة الطلبات',()=>go(user.role==='Student'&&!profile?'profile':'applications'),'primary'));
    const stats=h('div',{class:'cards'},stat('إجمالي الطلبات',list.total,'الطلبات التي يمكنك الوصول إليها'),stat(user.role==='Student'?'المستندات الإلزامية':'المعروضة الآن',user.role==='Student'?count+' / '+requiredNow.length:list.items.length,user.role==='Student'?'وفق الطلب الأحدث':'أحدث خمسة طلبات'),stat('حالة الطلب الأحدث',latest?tr(latest.status):'لم يبدأ','القبول والتسكين مرحلتان منفصلتان'));
    const stages=['الملف الطلابي','المستندات','شؤون الطلاب','إدارة السكن'];
    const step=['Accepted','Rejected'].includes(latest?.status)?4:latest?.status==='Ready for Decision'?3:latest&& !['Draft','Pending Documents'].includes(latest.status)?2:profile?1:0;
    const progress=panel('رحلة الطلب',h('p',{class:'hint'},'التقدم يعتمد على الحالة الفعلية للطلب؛ لا يتم تخصيص غرفة في هذه الدفعة.'),h('div',{class:'steps'},stages.map((s,i)=>h('div',{class:'step '+(i<step?'done':i===step?'current':'')},h('b',{},i<step?'✓':String(i+1)),s))),latest?button('عرض تفاصيل الطلب',()=>openApplication(latest.application_id)):h('p',{class:'muted'},'سيظهر تقدمك هنا بعد إنشاء أول طلب.'));
    const required=panel('قبل تقديم الطلب',...requiredNow.map(type=>h('div',{class:'document-row'},h('div',{},h('strong',{},tr(type)),h('small',{},'PDF أو صورة واضحة · حتى '+Math.floor(p.max_document_bytes/1024/1024)+' MB')),h('span',{class:latest?.documents.some(d=>d.document_type===type&&d.available)?'doc-status':'doc-missing'},latest?.documents.some(d=>d.document_type===type&&d.available)?'✓ مرفق':'مطلوب'))),h('p',{class:'hint'},'المستندات خاصة، ولا تُنشر عبر روابط عامة.'));
    renderPage('dashboard',epoch,intro,welcome,stats,h('div',{class:'grid-two'},progress,required),panel('أحدث الطلبات',list.items.length?applicationTable(list.items):empty('لا توجد طلبات بعد','سيظهر طلبك هنا بعد استكمال الملف وإنشاء مسودة.')));
  }
  function empty(title,description){return h('div',{class:'empty'},h('span',{class:'empty-symbol','aria-hidden':'true'},'▤'),h('h3',{},title),h('p',{},description));}
  async function profilePage(){const epoch=viewEpoch;if(state.page!=='profile'||!state.me)return;const data=await fetchProfile();const form=h('form',{},h('div',{class:'form-grid'},field('الاسم الكامل','full_name',data?.full_name||'','text',{minlength:2,maxlength:200}),field('الجامعة','university',data?.university||'','text',{minlength:2,maxlength:200}),field('التخصص','major',data?.major||'','text',{minlength:2,maxlength:200})),h('div',{class:'actions'},h('button',{type:'submit',class:'primary'},data?'حفظ التعديلات':'إنشاء الملف'),h('span',{class:'hint'},'لا يمكن تغيير الحالات الأكاديمية أو السكنية من هذا النموذج.')));
    form.addEventListener('submit',async e=>{e.preventDefault();const b=form.querySelector('button');b.disabled=true;try{const body=Object.fromEntries(new FormData(form));if(data)body.expected_version=data.profile_version;await api('/students/me',{method:data?'PATCH':'POST',body});await profilePage();notify('تم حفظ الملف بنجاح.');}catch(err){notify(err.message,true);}finally{b.disabled=false;}});
    renderPage('profile',epoch,heading('ملفي الطلابي','بيانات أساسية تُحفظ ضمن طلبك عند التقديم.'),panel('البيانات الأساسية',form),h('p',{class:'hint'},'عند دخول الطلب مرحلة المراجعة يُقفل تعديل الملف. يمكن تعديله في المسودة أو عندما يُطلب استكمال المستندات.'));
  }
  function applicationTable(items){return h('div',{class:'table-scroll'},h('table',{},h('thead',{},h('tr',{},['الطالب','الجامعة','تاريخ الإنشاء','الحالة',''].map(x=>h('th',{},x)))),h('tbody',{},items.map(a=>h('tr',{},h('td',{},a.student_name),h('td',{},a.university),h('td',{},date(a.application_date)),h('td',{},badge(a.status)),h('td',{},button('التفاصيل',()=>openApplication(a.application_id))))))));}
  async function applicationsPage(){const epoch=viewEpoch;if(state.page!=='applications'||!state.me)return;await policy();const filter=state.filter||''; const list=await api('/applications?limit=10&offset='+state.offset+(filter?'&status='+encodeURIComponent(filter):''));const select=h('select',{'aria-label':'تصفية حالة الطلب'},h('option',{value:''},'كل الحالات'),Object.entries(statuses).map(([v,label])=>h('option',{value:v},label)));select.value=filter;select.addEventListener('change',()=>{state.filter=select.value;state.offset=0;applicationsPage().catch(e=>notify(e.message,true));});
    const create=state.me.role==='Student'?button('＋ إنشاء طلب',async()=>{const a=await api('/applications',{method:'POST'});await applicationsPage();await openApplication(a.application_id);},'primary'):null;
    renderPage('applications',epoch,heading(state.me.role==='Student'?'طلبات السكن':'مراجعة طلبات السكن','من المسودة إلى القرار النهائي، بخطوات موثقة.',create),panel('قائمة الطلبات',select,list.items.length?applicationTable(list.items):empty('لا توجد طلبات بهذه الحالة','يمكنك تغيير التصفية أو إنشاء طلب إذا كنت طالباً.'),h('div',{class:'pager'},button('السابق',async()=>{state.offset=Math.max(0,state.offset-10);await applicationsPage();}),h('span',{},'عرض '+list.items.length+' من '+list.total),button('التالي',async()=>{if(state.offset+10<list.total){state.offset+=10;await applicationsPage();}}))));
  }
  async function openApplication(id){state.current=await api('/applications/'+id);await policy();renderDetail();if(!$('detailDialog').open)$('detailDialog').showModal();}
  function renderDetail(){const a=state.current; const editable=state.me.role==='Student'&&['Draft','Pending Documents'].includes(a.status); const snap=a.profile_snapshot;
    const nodes=[h('h2',{id:'detailHeading'},'تفاصيل طلب السكن'),h('p',{class:'hint'},'نسخة الطلب: '+a.version+' · '+date(a.application_date)),badge(a.status),panel('بيانات الطلب',h('h3',{},a.student_name),h('p',{class:'muted'},a.university+(snap?' · '+snap.major:'')),h('p',{class:'hint'},snap?'هذه نسخة البيانات المحفوظة عند التقديم.':'تُحفظ نسخة البيانات عند تقديم الطلب.'))];
    if(a.review_notes)nodes.push(panel('ملاحظات المراجعة',h('p',{},a.review_notes)));
    if(a.decision_notes)nodes.push(panel('ملاحظات القرار',h('p',{},a.decision_notes)));
    const types=[...state.policy.required_documents,...state.policy.document_types.filter(x=>!state.policy.required_documents.includes(x))];
    const docRows=types.map(type=>{const doc=a.documents.find(d=>d.document_type===type);const required=state.policy.required_documents.includes(type)||a.requested_documents.includes(type);const actions=[];
      if(doc?.available)actions.push(button('تنزيل',async()=>{const file=await api('/applications/'+a.application_id+'/documents/'+doc.document_id,{blob:true});const url=URL.createObjectURL(file.data);const link=h('a',{href:url,download:type.toLowerCase().replaceAll(' ','-')+(file.type.includes('pdf')?'.pdf':file.type.includes('png')?'.png':'.jpg')});document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
      if(editable){const input=h('input',{type:'file',accept:'.pdf,.jpg,.jpeg,.png',hidden:true,'aria-label':'رفع '+tr(type)});input.addEventListener('change',async()=>{if(!input.files[0])return;const selected=input.files[0];if(selected.size>state.policy.max_document_bytes){notify('الملف أكبر من الحد المسموح.',true);return;}const data=new FormData();data.append('file',selected);data.append('document_type',type);data.append('expected_version',a.version);try{input.disabled=true;state.current=await api('/applications/'+a.application_id+'/documents',{method:'POST',body:data});renderDetail();}catch(e){notify(e.message,true);window.alert(e.message);}finally{input.disabled=false;}});actions.push(input,button(doc?'استبدال':'رفع مستند',()=>input.click()));if(doc)actions.push(button('إزالة',async()=>{state.current=await api('/applications/'+a.application_id+'/documents/'+doc.document_id+'?expected_version='+a.version,{method:'DELETE'});renderDetail();},'danger'));}
      return h('div',{class:'document-row'},h('div',{},h('strong',{},tr(type)),h('small',{},required?'إلزامي':'اختياري'),doc?h('small',{},doc.available?Math.ceil(doc.size_bytes/1024)+' KB · '+date(doc.uploaded_at):'ملف قديم: يجب إعادة رفعه'):null),h('div',{class:'file-actions'},h('span',{class:doc?.available?'doc-status':'doc-missing'},doc?.available?'✓ مرفق':'غير مرفق'),actions));});
    nodes.push(panel('المستندات',h('p',{class:'hint'},'PDF، JPEG أو PNG · حتى '+Math.floor(state.policy.max_document_bytes/1024/1024)+' MB لكل مستند · دون ملفات مشفرة أو تفاعلية.'),docRows));
    if(editable)nodes.push(button(a.status==='Pending Documents'?'إعادة تقديم الطلب':'تقديم الطلب للمراجعة',async()=>{state.current=await api('/applications/'+a.application_id+'/submit',{method:'POST',body:{expected_version:a.version}});renderDetail();},'primary'));
    if(state.me.role==='Student Affairs'&&['Submitted','Under Review'].includes(a.status)){
      const note=h('textarea',{placeholder:'ملاحظات واضحة للطالب أو لإدارة السكن',maxlength:2000,'aria-label':'ملاحظات المراجعة'});
      const checkboxes=h('div',{class:'checkboxes'},types.map(type=>h('label',{},h('input',{type:'checkbox',value:type}),tr(type))));
      const actions=[];if(a.status==='Submitted')actions.push(button('بدء المراجعة',()=>reviewAction('start',note.value), 'primary'));if(a.status==='Under Review')actions.push(button('اكتمال المراجعة والإحالة لإدارة السكن',()=>reviewAction('complete',note.value),'primary'));
      actions.push(button('طلب استكمال المستندات',()=>reviewAction('request_documents',note.value,[...checkboxes.querySelectorAll('input:checked')].map(n=>n.value))));
      nodes.push(panel('إجراء شؤون الطلاب',note,h('p',{class:'hint'},'لطلب الاستكمال: اختر المستندات المطلوبة وأضف سبباً واضحاً.'),checkboxes,h('div',{class:'actions'},actions)));
    }
    if(state.me.role==='Housing Administration'&&a.status==='Ready for Decision'){
      const note=h('textarea',{placeholder:'سبب القرار (إلزامي عند الرفض أو الإعادة)',maxlength:2000,'aria-label':'ملاحظات القرار'});
      nodes.push(panel('قرار إدارة السكن',note,h('div',{class:'actions'},button('قبول الطلب',()=>reviewAction('accept',note.value),'primary'),button('رفض الطلب',()=>reviewAction('reject',note.value),'danger'),button('إعادة إلى شؤون الطلاب',()=>reviewAction('return_to_review',note.value)))));
    }
    if(a.status==='Accepted')nodes.push(h('div',{class:'banner'},h('p',{},'تم قبول طلبك. لا يعني ذلك تخصيص غرفة؛ التوزيع يُنفّذ ضمن المرحلة التالية.')));
    nodes.push(panel('سجل الطلب',h('div',{class:'timeline'},a.history.map(e=>h('div',{class:'timeline-item'},h('strong',{},eventNames[e.action]||e.action),h('small',{},tr(e.actor_role)+' · '+date(e.created_at)),e.note?h('p',{},tr(e.note)):null)))));
    $('detailContent').replaceChildren(...nodes);
  }
  async function reviewAction(action,note,document_types=[]){try {state.current=await api('/applications/'+state.current.application_id+'/review',{method:'POST',body:{action,note,document_types,expected_version:state.current.version}});renderDetail();}catch(error){window.alert(error.message);}}
  async function securityPage(){const epoch=viewEpoch;if(state.page!=='security'||!state.me)return;const sessions=await api('/auth/sessions');const form=h('form',{},field('كلمة المرور الحالية','current_password','','password',{autocomplete:'current-password',maxlength:256}),field('كلمة المرور الجديدة','new_password','','password',{autocomplete:'new-password',minlength:12,maxlength:256}),h('button',{class:'primary',type:'submit'},'تغيير الكلمة والخروج من جميع الجلسات'));
    form.addEventListener('submit',async e=>{e.preventDefault();const b=form.querySelector('button');b.disabled=true;try{await api('/auth/change-password',{method:'POST',body:Object.fromEntries(new FormData(form))});localLogout('تم تغيير كلمة المرور. سجّل الدخول بكلمتك الجديدة.');}catch(err){notify(err.message,true);}finally{b.disabled=false;}});
    renderPage('security',epoch,heading('الأمان والجلسات','أوقات الجلسات تُعرض بحسب توقيت جهازك.'),state.me.must_change_password?h('div',{class:'banner'},h('p',{},'يجب تغيير كلمة المرور التي وضعها المدير قبل متابعة العمل.')):h('span',{hidden:true}),panel('تغيير كلمة المرور',h('p',{class:'hint'},'اختر كلمة جديدة مختلفة من 12 إلى 256 محرفاً.'),form),panel('جلساتي النشطة',...sessions.map(s=>h('div',{class:'document-row'},h('div',{},h('strong',{},'بدأت: '+date(s.created_at)),h('small',{},'تنتهي: '+date(s.expires_at))),button('إبطال هذه الجلسة',async()=>{await api('/auth/sessions/'+s.session_id,{method:'DELETE'});try{await api('/auth/users/me');await securityPage();}catch{}},'danger'))),button('خروج من جميع الجلسات',async()=>{await api('/auth/logout-all',{method:'POST'});localLogout();},'danger')));
  }
  async function accountsPage(){const epoch=viewEpoch;if(state.page!=='accounts'||!state.me)return;const list=await api('/users?limit=50');const role=h('select',{name:'role'},Object.entries(roles).map(([v,label])=>h('option',{value:v},label)));const form=h('form',{},h('div',{class:'form-grid'},field('اسم المستخدم','username','','text',{minlength:3,maxlength:80,autocomplete:'off'}),field('البريد الإلكتروني','email','','email',{maxlength:255}),field('كلمة المرور الأولية','password','','password',{minlength:12,maxlength:256,autocomplete:'new-password'}),h('label',{},'الدور',role)),h('button',{type:'submit',class:'primary'},'إنشاء الحساب'));
    form.addEventListener('submit',async e=>{e.preventDefault();const b=form.querySelector('button');b.disabled=true;try{await api('/users',{method:'POST',body:Object.fromEntries(new FormData(form))});form.reset();await accountsPage();notify('تم إنشاء الحساب. يجب على صاحبه تغيير الكلمة عند الدخول.');}catch(err){notify(err.message,true);}finally{b.disabled=false;}});
    const table=h('div',{class:'table-scroll'},h('table',{},h('thead',{},h('tr',{},['المستخدم','البريد','الدور','النشاط',''].map(x=>h('th',{},x)))),h('tbody',{},list.items.map(u=>h('tr',{},h('td',{},u.username),h('td',{},u.email),h('td',{},tr(u.role)),h('td',{},u.is_active?'نشط':'معطل'),h('td',{},u.user_id!==state.me.user_id?button(u.is_active?'تعطيل':'تفعيل',async()=>{if(!window.confirm('تأكيد تغيير نشاط الحساب وإبطال جلساته؟'))return;await api('/users/'+u.user_id,{method:'PATCH',body:{is_active:!u.is_active}});await accountsPage();}):h('span',{class:'hint'},'حسابك')))))));
    renderPage('accounts',epoch,heading('إدارة الحسابات','إنشاء الحسابات لمسؤول النظام فقط؛ لا يوجد تسجيل عام.'),panel('إنشاء حساب',form,h('p',{class:'hint'},'شارك الكلمة الأولية عبر قناة آمنة. سيُطلب تغييرها عند الدخول.')),panel('الحسابات',h('p',{class:'hint'},'يعرض حتى 50 حساباً من إجمالي '+list.total+'. الإدارة الموسعة متاحة في API.'),table));
  }
})();
