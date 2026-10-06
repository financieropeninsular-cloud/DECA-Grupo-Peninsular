import os,json,uuid,threading,io
import urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime
from flask import Flask,request,jsonify,send_file,abort,render_template_string
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
import qrcode
from pypdf import PdfReader,PdfWriter

app=Flask(__name__)
ROOT=Path(__file__).resolve().parent; DATA=ROOT/'data'; PDF=DATA/'pdfs'; DB=DATA/'db.json'; LOCK=threading.Lock()
BASE=os.getenv('PUBLIC_BASE_URL','').rstrip('/')
SB_URL=os.getenv('SUPABASE_URL','').rstrip('/')
SB_KEY=os.getenv('SUPABASE_KEY','')
SB_SECRET=os.getenv('DECA_STORAGE_SECRET','')
ISSUERS=[
 {'id':'autogruas','name':'AUTOGRÚAS DEL MEDITERRÁNEO, S.L.','nif':'B87289278','address':'C/ Félix Rodríguez de la Fuente, 42 · 03203 Torrellano-Elche (Alicante)','prefix':'ADM'},
 {'id':'gruas','name':'GRÚAS PENINSULAR, S.L.','nif':'B82726282','address':'Ctra. M-115, km 0,25 · 28830 San Fernando de Henares (Madrid)','prefix':'GP'},
 {'id':'montajes','name':'MONTAJES ELÉCTRICOS PENINSULAR, S.L.','nif':'B87567210','address':'Ctra. M-115, km 0,25 · 28830 San Fernando de Henares (Madrid)','prefix':'MEP'},
 {'id':'trincajes','name':'TRINCAJES VALENCIA, S.L.','nif':'B21721642','address':'Zona Turia · Puerto de València','prefix':'TV'}]

def now(): return datetime.now().astimezone().isoformat(timespec='seconds')
def empty(): return {'documents':[],'companies':[],'transporters':[],'vehicles':[],'issuers':ISSUERS,'sequence':{},'settings':{'public_base_url':BASE or 'http://localhost:8080'}}
def sb_enabled(): return bool(SB_URL and SB_KEY and SB_SECRET)
def sb_headers(content_type='application/json'):
 return {'apikey':SB_KEY,'Authorization':'Bearer '+SB_KEY,'x-deca-secret':SB_SECRET,'Content-Type':content_type}
def sb_request(path,method='GET',body=None,headers=None):
 h=sb_headers(); h.update(headers or {})
 data=None if body is None else (body if isinstance(body,(bytes,bytearray)) else json.dumps(body,ensure_ascii=False).encode('utf-8'))
 req=urllib.request.Request(SB_URL+path,data=data,headers=h,method=method)
 with urllib.request.urlopen(req,timeout=20) as r:return r.read()
def load():
 DATA.mkdir(exist_ok=True); PDF.mkdir(exist_ok=True)
 if sb_enabled():
  try:
   raw=sb_request('/rest/v1/deca_app_state?id=eq.main&select=data')
   rows=json.loads(raw.decode('utf-8'))
   d=rows[0]['data'] if rows else empty()
   for k,v in empty().items(): d.setdefault(k,v)
   d['issuers']=ISSUERS
   return d
  except Exception:
   pass
 if not DB.exists():
  t=DB.with_suffix('.tmp'); t.write_text(json.dumps(empty(),ensure_ascii=False,indent=2),encoding='utf-8'); t.replace(DB)
 try:
  d=json.loads(DB.read_text(encoding='utf-8'))
  for k,v in empty().items(): d.setdefault(k,v)
  d['issuers']=ISSUERS
  return d
 except: return empty()
def save(d):
 DATA.mkdir(exist_ok=True); PDF.mkdir(exist_ok=True)
 d['issuers']=ISSUERS
 if sb_enabled():
  sb_request('/rest/v1/deca_app_state?on_conflict=id','POST',[{'id':'main','data':d,'updated_at':now()}],{'Prefer':'resolution=merge-duplicates,return=minimal'})
  return
 t=DB.with_suffix('.tmp'); t.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8'); t.replace(DB)
def storage_upload(name,data):
 if not sb_enabled(): return
 sb_request('/storage/v1/object/deca-pdfs/'+urllib.parse.quote(name),'POST',data,{'Content-Type':'application/pdf','x-upsert':'true'})
def storage_download(name):
 if sb_enabled():
  return sb_request('/storage/v1/object/authenticated/deca-pdfs/'+urllib.parse.quote(name),'GET')
 p=PDF/name
 if not p.exists(): raise FileNotFoundError(name)
 return p.read_bytes()
def base(d=None): return BASE or (d or load()).get('settings',{}).get('public_base_url') or 'http://localhost:8080'
def issuer(d,i): return next((x for x in d['issuers'] if x['id']==i),None)
def num(d,i):
 y=str(datetime.now().year); k=i+':'+y; d['sequence'][k]=int(d['sequence'].get(k,0))+1; x=issuer(d,i); return f"{x['prefix']}-{y}/{d['sequence'][k]:06d}"
def valid(p):
 e=[]
 for k,n in [('issuer_id','empresa emisora'),('shipper_name','cargador'),('shipper_nif','NIF cargador'),('shipper_address','domicilio cargador'),('carrier_name','transportista'),('carrier_nif','NIF transportista'),('transport_date','fecha'),('vehicle_plate','matrícula')]:
  if not str(p.get(k,'')).strip(): e.append(n)
 ss=p.get('shipments') or []
 if not ss:e.append('al menos un envío')
 for j,s in enumerate(ss,1):
  if not s.get('origin') or not s.get('destination') or not s.get('goods'):e.append(f'envío {j} incompleto')
  if not s.get('weight') and not s.get('other_measure'):e.append(f'envío {j}: peso o magnitud')
 return e

def wrap(c,text,x,y,w,size=8.5,lead=10):
 c.setFont('Helvetica',size); line=''
 for word in str(text or '—').split():
  t=(line+' '+word).strip()
  if c.stringWidth(t,'Helvetica',size)<=w: line=t
  else: c.drawString(x,y,line); y-=lead; line=word
 if line:c.drawString(x,y,line);y-=lead
 return y

def make_pdf(doc,d):
 token=doc['token']; tmp=PDF/f'{token}.tmp.pdf'; out=PDF/f'{token}.pdf'; qr=PDF/f'{token}.png'; url=f"{base(d)}/d/{token}.pdf"; x=issuer(d,doc['issuer_id'])
 q=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=6,border=2);q.add_data(url);q.make(fit=True);q.make_image().save(qr)
 c=canvas.Canvas(str(tmp),pagesize=A4);W,H=A4;m=16*mm;y=H-m
 def sec(t,y): c.setFont('Helvetica-Bold',9);c.drawString(m,y,t.upper());c.line(m,y-3,W-m,y-3);return y-17
 def row(k,v,y): c.setFont('Helvetica-Bold',7.5);c.drawString(m,y,k);return wrap(c,v,m+49*mm,y,W-2*m-49*mm)
 c.setFont('Helvetica-Bold',14);c.drawString(m,y,'DOCUMENTO ELECTRÓNICO DE CONTROL ADMINISTRATIVO (DeCA)');y-=18
 c.setFont('Helvetica-Bold',9);c.drawString(m,y,x['name']);c.drawRightString(W-m,y,doc['number']);y-=13;c.setFont('Helvetica',7.5);c.drawString(m,y,f"NIF {x['nif']} · {x['address']}");y-=24
 y=sec('Cargador contractual',y);y=row('Razón social',doc['shipper_name'],y);y=row('NIF',doc['shipper_nif'],y);y=row('Domicilio',doc['shipper_address'],y);y-=6
 y=sec('Transportista efectivo',y);y=row('Razón social',doc['carrier_name'],y);y=row('NIF',doc['carrier_nif'],y);y-=6
 y=sec('Vehículo y servicio',y);y=row('Fecha transporte',doc['transport_date'],y);y=row('Matrícula',doc['vehicle_plate'],y)
 if doc.get('trailer_plate'):y=row('Remolque',doc['trailer_plate'],y)
 if doc.get('special_authorization'):y=row('Autorización especial',doc['special_authorization'],y)
 for i,s in enumerate(doc['shipments'],1):
  if y<75*mm:c.showPage();y=H-m
  y-=5;y=sec(f'Envío {i}',y);y=row('Origen',s.get('origin'),y);y=row('Destino',s.get('destination'),y);y=row('Mercancía',s.get('goods'),y);y=row('Peso / magnitud',s.get('weight') or s.get('other_measure'),y)
 if doc.get('observations'):
  y-=5;y=sec('Observaciones / reservas',y);y=wrap(c,doc['observations'],m,y,W-2*m)
 if doc.get('version',1)>1:
  y-=5;y=sec('Trazabilidad de modificación',y);y=row('Versión',doc['version'],y);y=row('Motivo',doc.get('change_reason'),y);y=row('Sustituye a',doc.get('previous_number'),y)
 if y<55*mm:c.showPage()
 c.drawImage(ImageReader(str(qr)),W-m-35*mm,18*mm,33*mm,33*mm);c.setFont('Helvetica',7);c.drawString(m,40*mm,'URL de descarga directa:');wrap(c,url,m,35*mm,W-2*m-40*mm,7,8);c.drawString(m,20*mm,f"Creado: {doc['created_at']}");c.save()
 r=PdfReader(str(tmp));w=PdfWriter();[w.add_page(p) for p in r.pages];w.add_metadata({'/Title':f"DeCA {doc['number']}",'/Creator':'DECA Grupo Peninsular'})
 with open(out,'wb') as f:w.write(f)
 tmp.unlink(missing_ok=True);qr.unlink(missing_ok=True)
 if out.stat().st_size>5*1024*1024:raise ValueError('PDF > 5 MB')
 storage_upload(out.name,out.read_bytes())
 return out,url

HTML=r'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DECA Grupo Peninsular</title><style>
*{box-sizing:border-box}body{margin:0;font:14px Arial;background:#f4f6f9;color:#172033}header{background:#10223d;color:white;padding:18px}main{max-width:1200px;margin:18px auto;padding:0 14px}.tabs{display:flex;gap:8px;margin-bottom:12px}.tabs button,.btn{border:0;border-radius:8px;padding:10px 13px;font-weight:700;cursor:pointer}.tabs button.on,.primary{background:#155eef;color:#fff}.card{background:white;border:1px solid #dde2ea;border-radius:12px;padding:16px;margin-bottom:14px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}label{display:block;font-size:11px;font-weight:700;margin:8px 0 4px;color:#526071;text-transform:uppercase}input,select,textarea{width:100%;padding:10px;border:1px solid #cfd6df;border-radius:7px}textarea{min-height:80px}.issuer{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.issuer button{padding:12px;border:2px solid #dde2ea;border-radius:10px;background:#fff;text-align:left}.issuer button.on{border-color:#155eef;background:#eef4ff}.ship{border:1px solid #e1e5eb;border-radius:9px;padding:11px;margin:10px 0}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.soft{background:#eef4ff;color:#1849a9}.danger{background:#fee4e2;color:#b42318}.ok{background:#ecfdf3;color:#067647;padding:10px;border-radius:8px}.warn{background:#fffaeb;color:#7a2e0e;padding:10px;border-radius:8px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:8px;border-bottom:1px solid #e4e7ec;text-align:left}.hide{display:none}@media(max-width:800px){.grid,.row,.issuer{grid-template-columns:1fr}}</style></head><body>
<header><h1 style="margin:0">DECA · Grupo Peninsular</h1><div style="opacity:.8">Emisión, PDF, QR, histórico y versionado</div></header><main>
<div class="tabs"><button class="on" onclick="tab('new',this)">Nuevo DeCA</button><button onclick="tab('hist',this)">Histórico</button><button onclick="tab('cfg',this)">Configuración</button></div>
<section id="new"><div id="msg" class="warn">Seleccione empresa y complete los datos.</div><div class="card"><h3>Empresa emisora</h3><div id="issuers" class="issuer"></div><div class="actions"><button class="btn soft" onclick="asCarrier()">Usar emisora como transportista</button><button class="btn soft" onclick="asShipper()">Usar emisora como cargador</button></div></div>
<div class="grid"><div class="card"><h3>Cargador contractual</h3><label>Razón social</label><input id="shipper_name"><div class="row"><div><label>NIF</label><input id="shipper_nif"></div><div><label>Domicilio</label><input id="shipper_address"></div></div></div><div class="card"><h3>Transportista efectivo</h3><label>Razón social</label><input id="carrier_name"><label>NIF</label><input id="carrier_nif"></div><div class="card"><h3>Vehículo y fecha</h3><div class="row"><div><label>Fecha</label><input id="transport_date" type="date"></div><div><label>Matrícula</label><input id="vehicle_plate"></div></div><div class="row"><div><label>Remolque</label><input id="trailer_plate"></div><div><label>Autorización especial</label><input id="special_authorization"></div></div></div><div class="card"><h3>Observaciones</h3><textarea id="observations"></textarea><div id="changebox" class="hide"><label>Motivo modificación</label><input id="change_reason"></div></div></div>
<div class="card"><div style="display:flex;justify-content:space-between"><h3>Envíos</h3><button class="btn soft" onclick="addShip()">+ Añadir</button></div><div id="ships"></div></div><div class="actions"><button id="emit" class="btn primary" onclick="issue()">Emitir DeCA + PDF + QR</button><button class="btn" onclick="reset()">Limpiar</button></div></section>
<section id="hist" class="hide"><div class="card"><label>Buscar</label><input id="q" oninput="history()" placeholder="número, cargador, matrícula..."><div style="overflow:auto"><table><thead><tr><th>Nº</th><th>Empresa</th><th>Fecha</th><th>Cargador</th><th>Transportista</th><th>Vehículo</th><th>Estado</th><th>Acciones</th></tr></thead><tbody id="docs"></tbody></table></div></div></section>
<section id="cfg" class="hide"><div class="card"><h3>URL pública</h3><p>Se utiliza en el QR. En producción debe ser HTTPS.</p><input id="public_url" placeholder="https://deca-grupo-peninsular.onrender.com"><button class="btn primary" style="margin-top:8px" onclick="saveCfg()">Guardar</button><p id="cfgmsg"></p></div></section>
</main><script>
let S={},issuerId='',editing=null;const $=x=>document.getElementById(x),esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function tab(id,b){['new','hist','cfg'].forEach(x=>$(x).classList.add('hide'));$(id).classList.remove('hide');document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('on'));b.classList.add('on');if(id==='hist')history()}
async function load(){S=await fetch('/api/state').then(r=>r.json());$('public_url').value=S.settings.public_base_url||'';renderIssuers();history()}
function renderIssuers(){$('issuers').innerHTML=S.issuers.map(x=>`<button class="${x.id===issuerId?'on':''}" onclick="issuerId='${x.id}';renderIssuers()"><b>${esc(x.name)}</b><br><small>NIF ${esc(x.nif)}</small></button>`).join('')}
function I(){return S.issuers.find(x=>x.id===issuerId)}function asCarrier(){let x=I();if(!x)return alert('Seleccione empresa');$('carrier_name').value=x.name;$('carrier_nif').value=x.nif}function asShipper(){let x=I();if(!x)return alert('Seleccione empresa');$('shipper_name').value=x.name;$('shipper_nif').value=x.nif;$('shipper_address').value=x.address}
function addShip(v={}){let d=document.createElement('div');d.className='ship';d.innerHTML=`<div class="row"><div><label>Origen</label><input class="origin" value="${esc(v.origin||'')}"></div><div><label>Destino</label><input class="destination" value="${esc(v.destination||'')}"></div></div><label>Mercancía</label><input class="goods" value="${esc(v.goods||'')}"><div class="row"><div><label>Peso</label><input class="weight" value="${esc(v.weight||'')}"></div><div><label>Magnitud alternativa</label><input class="other_measure" value="${esc(v.other_measure||'')}"></div></div><button class="btn danger" onclick="this.parentElement.remove()">Eliminar</button>`;$('ships').appendChild(d)}
function payload(){return {issuer_id:issuerId,shipper_name:$('shipper_name').value,shipper_nif:$('shipper_nif').value,shipper_address:$('shipper_address').value,carrier_name:$('carrier_name').value,carrier_nif:$('carrier_nif').value,transport_date:$('transport_date').value,vehicle_plate:$('vehicle_plate').value,trailer_plate:$('trailer_plate').value,special_authorization:$('special_authorization').value,observations:$('observations').value,change_reason:$('change_reason').value,shipments:[...document.querySelectorAll('.ship')].map(x=>({origin:x.querySelector('.origin').value,destination:x.querySelector('.destination').value,goods:x.querySelector('.goods').value,weight:x.querySelector('.weight').value,other_measure:x.querySelector('.other_measure').value}))}}
async function issue(){let r=await fetch(editing?'/api/deca/'+editing+'/reissue':'/api/deca',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});let j=await r.json();if(!r.ok){$('msg').className='warn';$('msg').textContent='Revisar: '+(j.errors||[j.error]).join(' · ');return}$('msg').className='ok';$('msg').innerHTML=`Emitido <b>${esc(j.document.number)}</b> · <a href="/api/deca/${j.document.id}/pdf">Descargar PDF</a>`;await load();reset(false)}
function reset(msg=true){editing=null;issuerId='';renderIssuers();['shipper_name','shipper_nif','shipper_address','carrier_name','carrier_nif','vehicle_plate','trailer_plate','special_authorization','observations','change_reason'].forEach(k=>$(k).value='');$('transport_date').value=new Date().toISOString().slice(0,10);$('ships').innerHTML='';addShip();$('changebox').classList.add('hide');$('emit').textContent='Emitir DeCA + PDF + QR';if(msg){$('msg').className='warn';$('msg').textContent='Seleccione empresa y complete los datos.'}}
function history(){if(!S.documents)return;let q=($('q')?.value||'').toLowerCase();let a=S.documents.slice().reverse().filter(d=>JSON.stringify(d).toLowerCase().includes(q));$('docs').innerHTML=a.map(d=>`<tr><td><b>${esc(d.number)}</b></td><td>${esc((S.issuers.find(x=>x.id===d.issuer_id)||{}).name)}</td><td>${esc(d.transport_date)}</td><td>${esc(d.shipper_name)}</td><td>${esc(d.carrier_name)}</td><td>${esc(d.vehicle_plate)}</td><td>${esc(d.status)}</td><td><a href="/api/deca/${d.id}/pdf">PDF</a>${d.status==='EMITIDO'?` · <a href="#" onclick="edit('${d.id}');return false">Modificar</a>`:''}</td></tr>`).join('')}
function edit(id){let d=S.documents.find(x=>x.id===id);editing=id;issuerId=d.issuer_id;renderIssuers();['shipper_name','shipper_nif','shipper_address','carrier_name','carrier_nif','transport_date','vehicle_plate','trailer_plate','special_authorization','observations'].forEach(k=>$(k).value=d[k]||'');$('ships').innerHTML='';d.shipments.forEach(addShip);$('changebox').classList.remove('hide');$('emit').textContent='Emitir nueva versión';document.querySelector('.tabs button').click()}
async function saveCfg(){let r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({public_base_url:$('public_url').value})});let j=await r.json();$('cfgmsg').textContent=r.ok?'Guardado: '+j.public_base_url:j.error;await load()}
reset(false);load();
</script></body></html>'''

@app.get('/')
def home():return render_template_string(HTML)
@app.get('/health')
def health():return jsonify(ok=True,time=now(),persistent_backend='supabase' if sb_enabled() else 'local')
@app.get('/api/state')
def state():return jsonify(load())
@app.post('/api/settings')
def settings():
 b=request.get_json(force=True);u=str(b.get('public_base_url','')).strip().rstrip('/')
 if u and not (u.startswith('https://') or u.startswith('http://localhost')):return jsonify(error='La URL pública debe usar HTTPS'),400
 with LOCK:d=load();d['settings']['public_base_url']=u or 'http://localhost:8080';save(d)
 return jsonify(ok=True,public_base_url=base(d))
@app.post('/api/deca')
def issue():
 p=request.get_json(force=True);e=valid(p)
 if e:return jsonify(errors=e),400
 with LOCK:
  d=load();ts=now();doc={'id':uuid.uuid4().hex,'number':num(d,p['issuer_id']),'token':uuid.uuid4().hex,'status':'EMITIDO','version':1,'created_at':ts,'modified_at':ts,**p};f,u=make_pdf(doc,d);doc['pdf_file']=f.name;doc['url']=u;d['documents'].append(doc);save(d)
 return jsonify(ok=True,document=doc)
@app.post('/api/deca/<docid>/reissue')
def reissue(docid):
 p=request.get_json(force=True);e=valid(p)
 if e:return jsonify(errors=e),400
 if not p.get('change_reason'):return jsonify(errors=['motivo de modificación']),400
 with LOCK:
  d=load();old=next((x for x in d['documents'] if x['id']==docid),None)
  if not old:abort(404)
  old['status']='SUSTITUIDO';ts=now();v=int(old.get('version',1))+1;bn=old['number'].split('-V')[0];doc={'id':uuid.uuid4().hex,'number':f'{bn}-V{v}','token':uuid.uuid4().hex,'status':'EMITIDO','version':v,'previous_id':old['id'],'previous_number':old['number'],'created_at':ts,'modified_at':ts,**p};f,u=make_pdf(doc,d);doc['pdf_file']=f.name;doc['url']=u;d['documents'].append(doc);save(d)
 return jsonify(ok=True,document=doc)
def send_doc(doc):
 try: data=storage_download(doc['pdf_file'])
 except Exception: abort(404)
 return send_file(io.BytesIO(data),mimetype='application/pdf',as_attachment=True,download_name='DECA_'+doc['number'].replace('/','-')+'.pdf')
@app.get('/d/<token>.pdf')
def direct(token):
 d=load();doc=next((x for x in d['documents'] if x.get('token')==token),None)
 if not doc:abort(404)
 return send_doc(doc)
@app.get('/api/deca/<docid>/pdf')
def pdf(docid):
 d=load();doc=next((x for x in d['documents'] if x['id']==docid),None)
 if not doc:abort(404)
 return send_doc(doc)

if __name__=='__main__':
 DATA.mkdir(exist_ok=True);PDF.mkdir(exist_ok=True);app.run(host='0.0.0.0',port=int(os.getenv('PORT','8080')))
