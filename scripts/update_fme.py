#!/usr/bin/env python3
import datetime,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
BASE=Path(__file__).resolve().parents[1]; OUT=BASE/'data'/'regional-fme.json'
CAL='https://app.skermo.org/calendar/public/FME?setLang=es'; RANK='https://app.skermo.org/ranking/public/FME?setLang=es'; ENG='https://engarde-service.com/index.php?lang=en&Organisme=fme&page=tournois.php'
CATS={'M13':12,'M15':4,'M17':5,'M20':6,'ABS':7}
SOURCES=[{'name':'FME · Competición','url':'https://fmesgrima.es/competicion/','use':'Página índice oficial'},{'name':'Skermo FME · Calendario e información de torneos','url':CAL,'use':'Fechas, categorías, modalidad, sede, horario, cierre e inscripciones'},{'name':'Skermo FME · Ranking','url':RANK,'use':'Ranking regional por temporada, arma, categoría y género'},{'name':'FME · Calendario PDF','url':'https://fmesgrima.es/wp-content/uploads/2026/06/Calendario.pdf','use':'Documento oficial de contraste'},{'name':'Engarde Service · FME','url':ENG,'use':'Resultados online y clasificaciones'},{'name':'FME · Normativa de competición','url':'https://fmesgrima.es/wp-content/uploads/2026/02/Competicion.pdf','use':'Reglas, coeficientes y criterios regionales'}]
SESSION=requests.Session(); SESSION.headers.update({'User-Agent':'Mozilla/5.0 dashboard-sable-femenino/1.1','Accept-Language':'es-ES,es;q=0.9'})
def get_html(url,params=None):
 r=SESSION.get(url,params=params,timeout=45); r.raise_for_status(); return r.text
def browser_html(url):
 from playwright.sync_api import sync_playwright
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True); page=browser.new_page(locale='es-ES'); page.goto(url,wait_until='networkidle',timeout=90000); html=page.content(); browser.close(); return html
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
def parse_calendar(html):
 out=[]
 for tr in BeautifulSoup(html,'html.parser').select('table tr'):
  c=cells(tr); txt=' '.join(c).upper()
  if len(c)>=7 and re.match(r'\d{2}/\d{2}/\d{4}',c[0]) and 'SABLE' in txt and ('FEMENINO' in txt or ' FEM ' in f' {txt} '):
   a=tr.find('a',href=True); href=a['href'] if a else ''
   out.append({'date':c[0],'name':c[1],'weapon':c[2],'gender':c[3],'category':c[4],'modality':c[5],'location':c[6],'url':urljoin(CAL,href)})
 return out
def calendar():
 rows=parse_calendar(get_html(CAL))
 return rows or parse_calendar(browser_html(CAL))
def results():
 html=browser_html(ENG); out=[]
 for a in BeautifulSoup(html,'html.parser').find_all('a',href=True):
  text=' '.join(a.get_text(' ',strip=True).split())
  if text and re.search(r'sable|sabre|femen|\bSF\b',text,re.I): out.append({'name':text,'date':'','category':'','url':urljoin(ENG,a['href'])})
 return list({x['url']:x for x in out}.values())[:100]
def main():
 old=json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
 data={'updated_at':datetime.datetime.now().astimezone().strftime('%d/%m/%Y %H:%M %Z'),'sources':SOURCES}
 for key,fn,default in [('rankings',rankings,{}),('calendar',calendar,[]),('results',results,[])]:
  try:
   value=fn()
   if key=='rankings' and not any(value.values()): raise RuntimeError('ranking vacío')
   if key=='calendar' and not value: raise RuntimeError('calendario vacío')
   data[key]=value
  except Exception as exc:
   print(f'AVISO {key}: {exc}'); data[key]=old.get(key,default)
 OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
