#!/usr/bin/env python3
import datetime,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
BASE=Path(__file__).resolve().parents[1];OUT=BASE/'data'/'nacional-rfee.json'
RANK='https://app.skermo.org/ranking-rfee/public/RFEE';CAL='https://app.skermo.org/calendar/public/RFEE?setLang=es';CATS={'M13':12,'M15':4,'M17':5,'M20':6,'ABS':7}
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 dashboard-sable-femenino/2.0','Accept-Language':'es-ES,es;q=0.9'})
def get(url,params=None):r=S.get(url,params=params,timeout=45);r.raise_for_status();return r.text
def browser(url):
 from playwright.sync_api import sync_playwright
 with sync_playwright() as p:
  b=p.chromium.launch(headless=True);page=b.new_page(locale='es-ES');page.goto(url,wait_until='networkidle',timeout=90000);html=page.content();b.close();return html
def cells(tr):return [' '.join(x.get_text(' ',strip=True).split()) for x in tr.find_all(['td','th'])]
def parse_rank(html):
 out=[]
 for tr in BeautifulSoup(html,'html.parser').select('table tr'):
  c=cells(tr)
  if not c or not re.fullmatch(r'\d+',c[0]):continue
  if len(c)>=6:out.append({'position':int(c[0]),'first_name':c[1],'last_name':c[2],'birth_year':c[3] if re.fullmatch(r'\d{4}',c[3]) else '', 'club':c[4], 'points':c[5].replace('.','').replace(',','.')})
  elif len(c)>=5:
   parts=c[1].split(' ',1);out.append({'position':int(c[0]),'first_name':parts[0],'last_name':parts[1] if len(parts)>1 else '','birth_year':'','club':c[2],'points':c[-1].replace('.','').replace(',','.')})
 return out
def rankings():
 out={}
 for cat,cid in CATS.items():
  params={'setLang':'es','season':17,'weapon':'S','category':cid,'gender':'W'};url=requests.Request('GET',RANK,params=params).prepare().url;rows=parse_rank(get(RANK,params));out[cat]=rows or parse_rank(browser(url))
 return out
def parse_calendar(html):
 out=[]
 for tr in BeautifulSoup(html,'html.parser').select('table tr'):
  c=cells(tr);txt=' '.join(c).upper()
  if len(c)<6 or not re.match(r'\d{2}/\d{2}/\d{4}',c[0]) or 'SABLE' not in txt or not ('FEMENINO' in txt or ' FEM ' in f' {txt} '):continue
  a=tr.find('a',href=True);href=urljoin(CAL,a['href']) if a else CAL;category=next((x for x in ['M13','M15','M17','M20','M23','ABS'] if x in txt),'ABS');scope='I' if any(x in txt for x in ['FIE','COPA DEL MUNDO','GRAND PRIX','EUROPEO','MUNDIAL','SATÉLITE','SATELITE']) else 'N'
  out.append({'date':c[0],'name':c[1],'category':category,'modality':'E' if 'EQUIP' in txt else 'I','location':c[6] if len(c)>6 else '','type':c[5] if len(c)>5 else '','scope':scope,'registration_deadline':'','entries':0,'venue':'','links':[['Skermo',href]],'internal_points':[]})
 return out
def calendar():
 rows=parse_calendar(get(CAL));return rows or parse_calendar(browser(CAL))
def main():
 old=json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {};data={'updated_at':datetime.datetime.now().astimezone().strftime('%d/%m/%Y %H:%M %Z'),'sources':[{'name':'Skermo RFEE · Ranking Nacional','url':RANK},{'name':'Skermo RFEE · Calendario','url':CAL}]}
 for key,fn,default in [('rankings',rankings,{}),('calendar',calendar,[])]:
  try:
   value=fn()
   if key=='rankings' and not any(value.values()):raise RuntimeError('rankings vacíos')
   if key=='calendar' and not value:raise RuntimeError('calendario vacío')
   data[key]=value
  except Exception as e:print('AVISO',key,e);data[key]=old.get(key,default)
 data['results']=old.get('results',[]);OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
