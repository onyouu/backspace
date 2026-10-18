"""Durable, project-local request budget. Values are ceilings, not provider quotas.

SQLite serializes reservations across processes. No API keys or source text are
stored here. All keys for the same local project share a bucket per model.
"""
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import contextmanager


class BudgetDeferred(ValueError):
    pass


class RequestBudget:
    def __init__(self, folder, model, *, clock=time.time, sleep=time.sleep):
        self.folder=folder; folder.mkdir(parents=True,exist_ok=True)
        self.path=folder/'budget.sqlite3'; self.model=model; self.clock=clock; self.sleep=sleep
        self.rpm=max(1,int(os.environ.get('BACKSPACE_API_RPM','8')))
        self.tpm=max(1,int(os.environ.get('BACKSPACE_API_TPM','24000')))
        self.rpd=max(1,int(os.environ.get('BACKSPACE_API_RPD','200')))
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, model TEXT, at REAL, tokens INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS cooldown (model TEXT PRIMARY KEY, until REAL, reason TEXT)')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        try:
            with db:yield db
        finally:db.close()

    def reserve(self, tokens):
        if tokens>self.tpm:
            raise BudgetDeferred('한 요청의 예상 입력량이 설정한 분당 예산보다 큽니다. 입력 단위를 줄이세요.')
        waited=0
        while True:
            now=self.clock(); delay=0
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                cd=db.execute('SELECT until,reason FROM cooldown WHERE model=?',(self.model,)).fetchone()
                if cd and cd[0]>now:
                    if cd[0]-now>120:raise BudgetDeferred('API 한도 대기 중입니다. 완료 결과는 보존됩니다: '+cd[1])
                    delay=cd[0]-now
                # Pacific daily quota boundary, including daylight saving time.
                local=datetime.fromtimestamp(now,ZoneInfo('America/Los_Angeles'))
                midnight=local.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
                count=db.execute('SELECT count(*) FROM calls WHERE model=? AND at>=?',(self.model,midnight)).fetchone()[0]
                if count>=self.rpd:raise BudgetDeferred('설정한 하루 요청 예산에 도달했습니다. 다음 날 저장 지점부터 재개하세요.')
                rows=db.execute('SELECT at,tokens FROM calls WHERE model=? AND at>? ORDER BY at',(self.model,now-60)).fetchall()
                if len(rows)>=self.rpm:delay=max(delay,rows[-self.rpm][0]+60-now+.1)
                total=sum(r[1] for r in rows)
                for at,size in rows:
                    if total+tokens<=self.tpm:break
                    delay=max(delay,at+60-now+.1);total-=size
                if delay<=0:
                    cur=db.execute('INSERT INTO calls(model,at,tokens) VALUES(?,?,?)',(self.model,now,tokens))
                    return cur.lastrowid,round(waited,2)
            self.sleep(min(delay,5));waited+=min(delay,5)

    def reconcile(self, identity, tokens):
        if isinstance(tokens,int):
            with self.connect() as db:db.execute('UPDATE calls SET tokens=? WHERE id=?',(max(0,tokens),identity))

    def defer(self, seconds, reason):
        with self.connect() as db:
            db.execute('INSERT INTO cooldown VALUES(?,?,?) ON CONFLICT(model) DO UPDATE SET until=max(until,excluded.until),reason=excluded.reason',
                       (self.model,self.clock()+max(1,seconds),reason))

    def status(self):
        with self.connect() as db:
            row=db.execute('SELECT until,reason FROM cooldown WHERE model=?',(self.model,)).fetchone()
            calls=db.execute('SELECT count(*),coalesce(sum(tokens),0) FROM calls WHERE model=? AND at>?',(self.model,self.clock()-60)).fetchone()
        return {'model':self.model,'limits':{'rpm':self.rpm,'input_tpm':self.tpm,'rpd':self.rpd},
                'last_minute':{'requests':calls[0],'input_tokens':calls[1]},
                'cooldown_until':row[0] if row else None,'reason':row[1] if row else None,
                'meaning':'local_scheduling_limits_not_verified_provider_quota'}


def quota_error(body, headers=None):
    """Read only retry/quota metadata, never persist the provider error body."""
    try:value=json.loads(body)
    except (ValueError,TypeError):value={}
    details=value.get('error',{}).get('details',[]); seconds=60.; daily=False
    for item in details:
        if 'RetryInfo' in item.get('@type',''):
            try:seconds=max(1.,float(str(item.get('retryDelay','60s')).rstrip('s')))
            except ValueError:pass
        for v in item.get('violations',[]):
            quota=(v.get('quotaId','')+' '+v.get('quotaMetric','')).lower()
            daily|='perday' in quota or 'per_day' in quota
    if headers:
        try:seconds=max(seconds,float(headers.get('Retry-After',0)))
        except ValueError:pass
    if daily:
        local=datetime.now(ZoneInfo('America/Los_Angeles'))
        seconds=((local+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)-local).total_seconds()+5
    return math.ceil(seconds), 'daily_quota' if daily else 'rate_limit'
