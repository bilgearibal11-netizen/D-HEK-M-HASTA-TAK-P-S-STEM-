from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib, secrets

app = FastAPI(title='Dentist SaaS V6', version='6.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

clinics = {
 'clinic-demo': {'id':'clinic-demo','name':'Demo Diş Kliniği','plan':'Demo / Pilot','active_until': '2027-09-28T23:59:59+03:00'}
}
users = {
 'u-admin': {'id':'u-admin','clinic_id':'clinic-demo','name':'Klinik Yöneticisi','email':'admin@demo.local','role':'admin','password_hash': hashlib.sha256(b'admin123').hexdigest()},
 'u-dentist': {'id':'u-dentist','clinic_id':'clinic-demo','name':'Dr. Ayşe Kaya','email':'hekim@demo.local','role':'dentist','password_hash': hashlib.sha256(b'hekim123').hexdigest()},
 'u-secretary': {'id':'u-secretary','clinic_id':'clinic-demo','name':'Sekreter','email':'sekreter@demo.local','role':'secretary','password_hash': hashlib.sha256(b'sekreter123').hexdigest()},
}
sessions={}
patients={'p1': {'id':'p1','clinic_id':'clinic-demo','name':'Ayşe Yılmaz','phone':'05550000000','birth_date':'1992-05-12'}}
services={'s1': {'id':'s1','clinic_id':'clinic-demo','name':'Muayene','duration_min':30}, 's2': {'id':'s2','clinic_id':'clinic-demo','name':'Kompozit Dolgu','duration_min':60}, 's3': {'id':'s3','clinic_id':'clinic-demo','name':'Diş Taşı Temizliği','duration_min':45}}
appointments=[]
treatments=[]

class Login(BaseModel): email:str; password:str
class AppointmentIn(BaseModel): patient_id:str; dentist_id:str; service_id:str; start_at:datetime
class TreatmentIn(BaseModel): patient_id:str; dentist_id:str; tooth_numbers:list[str]; procedure:str; notes:str=''; status:str='completed'; follow_up_at:datetime|None=None
class PatientIn(BaseModel): name:str; phone:str=''; birth_date:str=''

@app.get('/api/health')
def health(): return {'ok':True,'version':'6.0.0'}

@app.post('/api/auth/login')
def login(data:Login):
    user=next((u for u in users.values() if u['email'].lower()==data.email.lower()),None)
    if not user or hashlib.sha256(data.password.encode()).hexdigest()!=user['password_hash']:
        raise HTTPException(401,'E-posta veya şifre hatalı')
    token=secrets.token_urlsafe(32); sessions[token]=user['id']
    return {'token':token,'user':{k:user[k] for k in ['id','clinic_id','name','email','role']},'clinic':clinics[user['clinic_id']]}

def current_user(authorization:str=Header(default='')):
    if not authorization.startswith('Bearer '): raise HTTPException(401,'Giriş gerekli')
    uid=sessions.get(authorization[7:]); user=users.get(uid or '')
    if not user: raise HTTPException(401,'Oturum geçersiz')
    return user

@app.get('/api/me')
def me(user=Depends(current_user)): return {'user':{k:user[k] for k in ['id','clinic_id','name','email','role']},'clinic':clinics[user['clinic_id']]}

@app.get('/api/patients')
def get_patients(user=Depends(current_user)):
    return [p for p in patients.values() if p['clinic_id']==user['clinic_id']]

@app.post('/api/patients')
def create_patient(data:PatientIn,user=Depends(current_user)):
    if user['role'] not in ('admin','dentist','secretary'): raise HTTPException(403,'Yetkiniz yok')
    pid=f'p{len(patients)+1}'
    item={'id':pid,'clinic_id':user['clinic_id'],'name':data.name,'phone':data.phone,'birth_date':data.birth_date}
    patients[pid]=item; return item

@app.get('/api/dentists')
def list_dentists(user=Depends(current_user)):
    return [{'id':u['id'],'name':u['name']} for u in users.values() if u['clinic_id']==user['clinic_id'] and u['role']=='dentist']

@app.get('/api/patients/{patient_id}')
def get_patient(patient_id:str,user=Depends(current_user)):
    p=patients.get(patient_id)
    if not p or p['clinic_id']!=user['clinic_id']: raise HTTPException(404,'Hasta bulunamadı')
    return {'patient':p,'appointments':[a for a in appointments if a['patient_id']==patient_id and a['clinic_id']==user['clinic_id']], 'treatments':[t for t in treatments if t['patient_id']==patient_id and t['clinic_id']==user['clinic_id']]}

@app.get('/api/odontogram/{patient_id}')
def odontogram(patient_id:str,user=Depends(current_user)):
    result={str(n):[] for n in list(range(11,19))+list(range(21,29))+list(range(31,39))+list(range(41,49))}
    for t in treatments:
        if t['patient_id']==patient_id and t['clinic_id']==user['clinic_id']:
            for tooth in t['tooth_numbers']: result.setdefault(tooth,[]).append(t)
    return result

@app.get('/api/appointments')
def list_appointments(date:str|None=None,user=Depends(current_user)):
    items=[a for a in appointments if a['clinic_id']==user['clinic_id']]
    if date: items=[a for a in items if a['start_at'].date().isoformat()==date]
    out=[]
    for a in sorted(items,key=lambda x:x['start_at']):
        p=patients.get(a['patient_id']); s=services.get(a['service_id']); d=users.get(a['dentist_id'])
        out.append({**a,'patient_name':p['name'] if p else '(silinmiş)','service_name':s['name'] if s else '','dentist_name':d['name'] if d else ''})
    return out

@app.post('/api/appointments')
def create_appointment(data:AppointmentIn,user=Depends(current_user)):
    if user['role'] not in ('admin','dentist','secretary'): raise HTTPException(403,'Yetkiniz yok')
    p=patients.get(data.patient_id); s=services.get(data.service_id)
    if not p or p['clinic_id']!=user['clinic_id'] or not s: raise HTTPException(404,'Hasta/hizmet bulunamadı')
    end=data.start_at + timedelta(minutes=s['duration_min'])
    for a in appointments:
        if a['clinic_id']==user['clinic_id'] and a['dentist_id']==data.dentist_id and a['status']=='active':
            ae=a['start_at']+timedelta(minutes=a['duration_min'])
            if data.start_at < ae and a['start_at'] < end: raise HTTPException(409,'Bu zaman aralığı dolu')
    item={'id':f'a{len(appointments)+1}','clinic_id':user['clinic_id'],'patient_id':data.patient_id,'dentist_id':data.dentist_id,'service_id':data.service_id,'start_at':data.start_at,'duration_min':s['duration_min'],'status':'active'}
    appointments.append(item); return item

@app.delete('/api/appointments/{appointment_id}')
def cancel(appointment_id:str,user=Depends(current_user)):
    a=next((x for x in appointments if x['id']==appointment_id and x['clinic_id']==user['clinic_id']),None)
    if not a: raise HTTPException(404,'Randevu bulunamadı')
    if a['start_at'] - datetime.now(a['start_at'].tzinfo) < timedelta(hours=3): raise HTTPException(400,'Randevu en az 3 saat öncesine kadar iptal edilebilir')
    a['status']='cancelled'; return a

@app.post('/api/treatments')
def create_treatment(data:TreatmentIn,user=Depends(current_user)):
    if user['role'] not in ('admin','dentist'): raise HTTPException(403,'Tedavi kaydı için hekim yetkisi gerekir')
    p=patients.get(data.patient_id)
    if not p or p['clinic_id']!=user['clinic_id']: raise HTTPException(404,'Hasta bulunamadı')
    item={'id':f't{len(treatments)+1}','clinic_id':user['clinic_id'],'patient_id':data.patient_id,'dentist_id':data.dentist_id,'tooth_numbers':data.tooth_numbers,'procedure':data.procedure,'notes':data.notes,'status':data.status,'follow_up_at':data.follow_up_at,'created_at':datetime.now(timezone.utc)}
    treatments.append(item); return item

@app.get('/api/services')
def get_services(user=Depends(current_user)): return [s for s in services.values() if s['clinic_id']==user['clinic_id']]

frontend=Path(__file__).parent/'static'/'index.html'
@app.get('/')
def index(): return frontend.read_text(encoding='utf-8')
