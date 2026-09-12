"""Official HTTP adapter and independently generated local scenarios.

The controller has no access to scenario truth. Offline outcomes are not official.
"""
import hashlib
import http.client
import json
import math
import time
import http.client
import socket
import time
import uuid
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
import numpy as np

def health_check(url,attempts=3,timeout=3.):
    """Opt-in pre-flight TCP reachability check (sends no protocol request)."""
    parsed=urllib.parse.urlparse(url)
    host=parsed.hostname;port=parsed.port or (443 if parsed.scheme=='https' else 80)
    last=None
    for attempt in range(attempts):
        try:
            with socket.create_connection((host,port),timeout=timeout):
                return True
        except OSError as exc:
            last=exc
            if attempt<attempts-1:time.sleep(min(.25*2**attempt,2.))
    raise ConnectionError(f'simulator unreachable at {host}:{port}: {last}')


class HTTPBackend:
    def __init__(self,robot_id,url,log_path):
        self.robot_id=robot_id
        self.url=url.rstrip('/')
        self.virtual_time=0.
        self.log=Path(log_path).open('a',encoding='utf-8')
        self.deadline=time.monotonic()+60
        self.session=uuid.uuid4().hex[:12]
        self.seq=0
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(self,path,payload):
        self.seq+=1
        body={'arena_id':'default','robot_id':self.robot_id,
              'request_id':f'{self.session}-{self.seq}',**payload}
        data=json.dumps(body,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
        # Retries preserve byte-identical body, request ID and endpoint.
        for attempt in range(6):
            if time.monotonic()>=self.deadline:
                raise TimeoutError('HTTP deadline reached')
            request=urllib.request.Request(self.url+path,data=data,
                         headers={'Content-Type':'application/json; charset=utf-8'},method='POST')
            try:
                with self.opener.open(request,timeout=min(5,max(.1,self.deadline-time.monotonic()))) as response:
                    result=json.load(response)
                self.log.write(json.dumps({'path':path,'request':body,'response':result},ensure_ascii=False)+'\n')
                self.log.flush()
                if result.get('accepted') is not True:
                    raise RuntimeError('Request rejected; check robot_id and simulator state')
                self.virtual_time=float(result['virtual_time_s'])
                return result
            except urllib.error.HTTPError as e:
                # Error replies are not silently turned into new actions.
                self.log.write(json.dumps({'path':path,'request':body,'http_error':e.code})+'\n')
                self.log.flush()
                raise
            except (urllib.error.URLError,TimeoutError,ConnectionError,
                    http.client.IncompleteRead,json.JSONDecodeError) as e:
                self.log.write(json.dumps({'path':path,'request':body,'transport_error':str(e),'attempt':attempt})+'\n')
                self.log.flush()
                if attempt==5:
                    raise
                time.sleep(min(.25*2**attempt,2.))

    def enter(self):
        r=self.post('/enter',{})
        self.deadline=time.monotonic()+r['remaining_real_duration_s']
        return r

    def health(self,attempts=3,timeout=3.):
        return health_check(self.url,attempts=attempts,timeout=timeout)

    def action(self,path,p,c):
        return self.post(path,{'position':{'x':float(p[0]),'y':float(p[1])},'channel':int(c)})

    def exit(self):
        return self.post('/exit',{})

class LocalBackend:
    def __init__(self,seed,problem,error_mode='fixed',radius=None,n=None,all_directional=False):
        rng=np.random.default_rng(seed)
        self.seed=seed
        self.error_mode=error_mode
        count=int(rng.integers(10,17)) if n is None else n
        channels=rng.choice(np.arange(1,21),count,replace=False)
        self.sources={}
        for c in channels:
            r=1800*math.sqrt(float(rng.random())); a=float(rng.uniform(0,2*math.pi))
            self.sources[int(c)]={'p':np.array([r*math.cos(a),r*math.sin(a)]),
                'radius':float(rng.uniform(1000,1500)) if radius is None else radius,
                'direction':float(rng.uniform(0,2*math.pi)) if problem==4 and (all_directional or rng.random()<.5) else None,
                'alive':True}
        self.pos=np.zeros(2); self.channel=1; self.virtual_time=0.; self.trace=[]
        self.parts={'move_s':0.,'switch_s':0.,'measure_s':0.,'optical_s':0.,'laser_s':0.}

    def enter(self):
        return {'accepted':True,'remaining_real_duration_s':1200,'virtual_time_s':0.}

    def error(self,p,c):
        if self.error_mode=='plus':
            return 1.
        if self.error_mode=='minus':
            return -1.
        # Deterministic by position/channel: no fresh noise on repeated readings.
        text=f'{self.seed}:{c}:{p[0]:.8f}:{p[1]:.8f}'.encode()
        h=int.from_bytes(hashlib.sha256(text).digest()[:8],'big')
        return 2*h/(2**64-1)-1

    def action(self,path,p,c):
        p=np.asarray(p,dtype=float)
        move=float(np.linalg.norm(p-self.pos))/5
        self.parts['move_s']+=move
        self.virtual_time+=move
        self.pos=p.copy()
        s=self.sources.get(c)
        distance=float(np.linalg.norm(p-s['p'])) if s else float('inf')
        result={'accepted':True}
        if path=='/measure':
            switch=int(self.channel!=c)
            self.parts['switch_s']+=switch; self.parts['measure_s']+=5
            self.virtual_time+=5+switch
            self.channel=c
            visible=bool(s and s['alive'] and distance<=s['radius'])
            if visible and s['direction'] is not None:
                v=np.array([math.cos(s['direction']),math.sin(s['direction'])])
                visible=float((p-s['p'])@v)>=-1e-9
            if not visible:
                result['measure_result']='no_signal'
            elif distance<=5:
                result['measure_result']='near'
            else:
                result['measure_result']='direction'
                delta=s['p']-p
                angle=(math.degrees(math.atan2(delta[1],delta[0]))+self.error(p,c))%360
                result['svd_deg']=round(angle,2)%360
        else:
            self.parts['optical_s']+=3; self.virtual_time+=3
            success=bool(s and s['alive'] and distance<=20)
            result['clear_result']='success' if success else 'no_target_in_range'
            if success:
                s['alive']=False
                self.parts['laser_s']+=2; self.virtual_time+=2
        result['virtual_time_s']=self.virtual_time
        self.trace.append({'path':path,'p':p.tolist(),'channel':int(c),'result':result.copy()})
        if self.virtual_time>=360000:
            raise TimeoutError('Virtual time limit')
        return result

    def exit(self):
        return {'accepted':True,'virtual_time_s':self.virtual_time,'exit_reason':'user_exit'}
