#!/usr/bin/env python3
import datetime,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import pdfplumber

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'data'/'regional-fme.json'
PDF=BASE/'docs'/'fme'/'Calendario.pdf'
CAL='https://app.skermo.org/calendar/public/FME?setLang=es'
RANK='https://app.skermo.org/ranking/public/FME?setLang=es'
ENG='https://engarde-service.com/index.php?lang=en&Organisme=fme&page=tournois.php'
CATS={'M13':12,'M15':4,'M17':5,'M20':6,'ABS':7}
MONTHS={'SEPTIEMBRE':9,'OCTUBRE':10,'NOVIEMBRE':11,'DICIEMBRE':12,'ENERO':1,'FEBRERO':2,'MARZO':3,'ABRIL':4,'MAYO':5,'JUNIO':6,'JULIO':7}
TERRITORIAL=re.compile(r'\bFASE\b|\bCTO MAD\b|\bCAMPEONATO DE MADRID\b|\bTLM\b',re.I)
SOURCES=[
 {'name':'FME · Competición','url':'https://fmesgrima.es/competicion/','use':'Página índice oficial'},
 {'name':'FME · Calendario PDF','url':'docs/fme/Calendario.pdf','use':'Calendario completo de sable femenino; copia local oficial'},
 {'name':'Skermo FME · Calendario','url':CAL,'use':'Información de torneos, horarios e inscripciones'},
 {'name':'Skermo FME · Ranking','url':RANK,'use':'Ranking regional por categoría y género'},
 {'name':'Engarde Service · FME','url':ENG,'use':'Resultados online'},
 {'name':'FME · Normativa','url':'docs/fme/Competicion.pdf','use':'Escala de puntos y reglas territoriales'}]
SESSION=requests.Session(); SESSION.headers.update({'User-Agent':'Mozilla/5.0 dashboard-sable-femenino/2.0','Accept-Language':'es-ES,es;q=0.9'})

def get_html(url,params=None):
 r=SESSION.get(url,params=params,timeout=45); r.raise_for_status(); return r.text

def browser_html(url):
 from playwright.sync_api import sync_playwright
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True); page=browser.new_page(locale='es-ES')
  page.goto(url,wait_until='networkidle',timeout=90000); html=page.content(); browser.close(); return html

def cells(tr): return [' '.join(x.get_text(' ',strip=True).split()) for x in tr.find_all(['td','th'])]

def parse_rank(html):
 rows=[]
 for tr in BeautifulSoup(html,'html.parser').select('table tr'):
  c=cells(tr)
  if len(c)>=5 and re.fullmatch(r'\d+',c[0]): rows.append({'position':int(c[0]),'name':f'{c[1]} {c[2]}'.strip(),'club':c[3],'points':c[4]})
 return rows

def rankings():
 out={}
 for cat,cid in CATS.items():
  params={'setLang':'es','season':17,'weapon':'S','category':cid,'gender':'W'}
  url=requests.Request('GET',RANK,params=params).prepare().url
  rows=parse_rank(get_html(RANK,params))
  if not rows: rows=parse_rank(browser_html(url))
  out[cat]=rows
 return out

def infer_categories(name):
 u=name.upper(); found=[]
 for c in ['M13','M15','M17','M20']:
  if re.search(rf'(?<!\d){c}(?!\d)',u): found.append(c)
 if re.search(r'\bABS\b|ABSOLUT',u): found.append('ABS')
 if not found and 'VET' in u: found.append('VET')
 return found or ['TODAS']

def event_type(name):
 u=name.upper()
 if 'CTO MAD' in u or 'CAMPEONATO DE MADRID' in u: return 'Campeonato de Madrid'
 if 'FASE' in u: return 'Fase territorial'
 if 'TLM' in u: return 'Torneo Liga Madrileña'
 return 'Territorial'

def pdf_calendar():
 if not PDF.exists(): raise FileNotFoundError(f'No existe {PDF}')
 with pdfplumber.open(PDF) as doc:
  page=doc.pages[0]; words=page.extract_words(x_tolerance=1,y_tolerance=2)
 # Month markers and weekend dates use fixed columns in the official landscape calendar.
 months=sorted([(w['top'],w['text'].upper()) for w in words if w['text'].upper() in MONTHS])
 dates=sorted([(w['top'],w['text']) for w in words if 122<=w['x0']<=136 and re.fullmatch(r'\d{1,2}-\d{1,2}',w['text'])])
 # Sable femenino is the fifth weapon column (approx. x=373..443).
 lines={}
 for w in words:
  if 373<=w['x0']<443 and w['top']>65:
   key=round(w['top'],1); lines.setdefault(key,[]).append(w)
 events=[]
 for top,ws in sorted(lines.items()):
  name=' '.join(x['text'] for x in sorted(ws,key=lambda z:z['x0'])).strip()
  if not name or not TERRITORIAL.search(name): continue
  dtop,dtext=min(dates,key=lambda d:abs(d[0]-top))
  # Associate event with closest weekend row; reject distant accidental matches.
  if abs(dtop-top)>9: continue
  mname=min(months,key=lambda m:abs(m[0]-dtop))[1]
  start_day,end_day=map(int,dtext.split('-')); month=MONTHS[mname]
  year=2026 if month>=9 else 2027
  # Handles weekends crossing month end, e.g. 31-1 or 28-01.
  end_month=month; end_year=year
  if end_day<start_day:
   end_month=1 if month==12 else month+1; end_year=year+1 if month==12 else year
  start=f'{start_day:02d}/{month:02d}/{year}'
  end=f'{end_day:02d}/{end_month:02d}/{end_year}'
  # Ordinary registration closes 23:59 on Wednesday before tournament.
  start_dt=datetime.date(year,month,start_day)
  close_dt=start_dt-datetime.timedelta(days=(start_dt.weekday()-2)%7 or 7)
  events.append({'date':start,'end_date':end,'name':name,'category':' / '.join(infer_categories(name)),
   'categories':infer_categories(name),'weapon':'Sable','gender':'Femenino','location':'Madrid / consultar FME',
   'type':event_type(name),'registration_deadline':close_dt.strftime('%d/%m/%Y 23:59'),
   'url':CAL,'source':'Calendario oficial FME PDF'})
 # Stable deduplication
 return list({(x['date'],x['name']):x for x in events}.values())

def skermo_calendar():
 def parse(html):
  out=[]
  for tr in BeautifulSoup(html,'html.parser').select('table tr'):
   c=cells(tr); txt=' '.join(c).upper()
   if len(c)>=7 and re.match(r'\d{2}/\d{2}/\d{4}',c[0]) and 'SABLE' in txt and ('FEMENINO' in txt or ' FEM ' in f' {txt} '):
    a=tr.find('a',href=True); href=a['href'] if a else ''
    out.append({'date':c[0],'name':c[1],'category':c[4],'location':c[6],'url':urljoin(CAL,href)})
  return out
 rows=parse(get_html(CAL)); return rows or parse(browser_html(CAL))

def merge_calendar():
 events=pdf_calendar()
 try: sk=skermo_calendar()
 except Exception as exc: print('AVISO Skermo calendario:',exc); sk=[]
 for e in events:
  candidates=[s for s in sk if s['date']==e['date'] or (set(re.findall(r'M\d+|ABS',s['name'].upper())) & set(e['categories']))]
  if candidates:
   s=candidates[0]; e['url']=s.get('url') or e['url']; e['location']=s.get('location') or e['location']
 return sorted(events,key=lambda x:datetime.datetime.strptime(x['date'],'%d/%m/%Y'))

def results():
 html=browser_html(ENG); out=[]
 for a in BeautifulSoup(html,'html.parser').find_all('a',href=True):
  text=' '.join(a.get_text(' ',strip=True).split())
  if text and re.search(r'sable|sabre|femen|\bSF\b',text,re.I): out.append({'name':text,'date':'','category':'','url':urljoin(ENG,a['href'])})
 return list({x['url']:x for x in out}.values())[:100]

def main():
 old=json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
 data={'updated_at':datetime.datetime.now().astimezone().strftime('%d/%m/%Y %H:%M %Z'),'sources':SOURCES,
 'points_rules':{'scale':[{'from':1,'to':1,'points':32},{'from':2,'to':2,'points':26},{'from':3,'to':4,'points':20},{'from':5,'to':8,'points':14},{'from':9,'to':16,'points':8},{'from':17,'to':32,'points':4},{'from':33,'to':64,'points':2},{'from':65,'to':128,'points':1}], 'championship_multiplier':2,'source':'Normativa FME 08-09-2026, apartado C.4-C.5'}}
 for key,fn,default in [('rankings',rankings,{}),('calendar',merge_calendar,[]),('results',results,[])]:
  try:
   value=fn()
   if key=='rankings' and not any(value.values()): raise RuntimeError('ranking vacío')
   if key=='calendar' and not value: raise RuntimeError('calendario PDF vacío')
   data[key]=value
  except Exception as exc:
   print(f'AVISO {key}: {exc}'); data[key]=old.get(key,default)
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
