"""Protocol-only port with independent action/time accounting.

Controllers receive this surface, which exposes no source coordinates or counts.
"""
import math
import time


class AuditPort:
    def __init__(self,backend):
        self.__backend=backend
        self.virtual_time=0.
        self.position=(0.,0.)
        self.channel=1
        self.entered=False
        self.exited=False
        self.success_channels=set()
        self.parts={'move_s':0.,'switch_s':0.,'measure_s':0.,'optical_s':0.,'laser_s':0.}
        self.max_step_error_s=0.
        self.actions=0
        self.deadline=None

    def enter(self):
        if self.entered:raise RuntimeError('Duplicate enter')
        r=self.__backend.enter()
        if r.get('accepted') is not True:raise RuntimeError('Enter rejected')
        self.entered=True
        self.virtual_time=float(r['virtual_time_s'])
        self.deadline=time.monotonic()+float(r['remaining_real_duration_s'])
        return r

    def action(self,path,p,c):
        if not self.entered or self.exited:raise RuntimeError('Action outside session')
        if time.monotonic()>=self.deadline:raise TimeoutError('Real deadline reached')
        if path not in ('/measure','/clear'):raise ValueError('Unknown action')
        if not isinstance(c,int) or not 1<=c<=20:raise ValueError('Invalid channel')
        p=tuple(float(x) for x in p)
        if len(p)!=2 or not all(math.isfinite(x) and abs(x)<=2000000 for x in p):
            raise ValueError('Invalid coordinates')
        r=self.__backend.action(path,p,c)
        if r.get('accepted') is not True:raise RuntimeError('Action rejected')
        delta=dict.fromkeys(self.parts,0.)
        delta['move_s']=math.dist(p,self.position)/5
        if path=='/measure':
            kind=r.get('measure_result')
            if kind not in ('direction','near','no_signal'):raise RuntimeError('Invalid measure result')
            if kind=='direction' and not (math.isfinite(r['svd_deg']) and 0<=r['svd_deg']<360):
                raise RuntimeError('Invalid bearing')
            delta['measure_s']=5
            delta['switch_s']=int(self.channel!=c)
            self.channel=c
        else:
            kind=r.get('clear_result')
            if kind not in ('success','no_target_in_range'):raise RuntimeError('Invalid clear result')
            delta['optical_s']=3
            if kind=='success':
                if c in self.success_channels:raise RuntimeError('Duplicate source clearance')
                self.success_channels.add(c);delta['laser_s']=2
        error=abs(float(r['virtual_time_s'])-(self.virtual_time+sum(delta.values())))
        self.max_step_error_s=max(self.max_step_error_s,error)
        # Protocol uses rounded cumulative microseconds.
        if error>1e-4:raise RuntimeError('Simulator timing differs from attachment rules')
        for k,v in delta.items():self.parts[k]+=v
        self.position=p;self.virtual_time=float(r['virtual_time_s']);self.actions+=1
        return r

    def exit(self):
        if not self.entered or self.exited:raise RuntimeError('Invalid exit')
        r=self.__backend.exit()
        if r.get('accepted') is not True or r.get('exit_reason')!='user_exit':
            raise RuntimeError('Normal exit not acknowledged')
        if abs(float(r['virtual_time_s'])-self.virtual_time)>1e-6:
            raise RuntimeError('Exit changed virtual time')
        self.exited=True
        return r
