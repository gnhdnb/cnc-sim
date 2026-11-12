"""Checkpoint-based, exact backward seeking, independent of any GUI toolkit."""
import bisect
import numpy as np
from .gcode import Move
from .chunkmesh import cutting_bounds


class Replay:
    def __init__(self,simulator,program,snapshots):
        self.sim=simulator
        self.program=program
        self.snapshots=snapshots
        self.ends=[m.t1 for m in program.moves]
        self.current=-1.
        self.done=0
        self.fraction=0.

    @staticmethod
    def part(m,lo,hi):
        delta=m.end-m.start
        dt=m.t1-m.t0
        return Move(m.start+lo*delta,m.start+hi*delta,m.tool,m.spindle,m.rpm,m.rapid,m.line,
                    m.t0+lo*dt,m.t0+hi*dt,m.kind)

    def seek(self,seconds,cancelled=None):
        seconds=min(self.program.duration,max(0.,float(seconds)))
        complete=bisect.bisect_right(self.ends,seconds)
        reset=self.current<0 or seconds<self.current
        dirty=[]
        if reset:
            self.done=self.snapshots.restore(complete,self.sim.grid,self.sim.stock)
            self.fraction=0.
        while self.done<complete:
            if cancelled and cancelled():raise InterruptedError()
            m=self.program.moves[self.done]
            partial=self.part(m,self.fraction,1.) if self.fraction else m
            if self.sim.apply(partial,check=False):dirty.append(cutting_bounds(partial,self.sim.tools[m.tool]))
            self.done+=1
            self.fraction=0.
        if self.done<len(self.program.moves):
            m=self.program.moves[self.done]
            fraction=(seconds-m.t0)/(m.t1-m.t0) if m.t1>m.t0 else 0.
            fraction=max(0.,min(1.,fraction))
            if fraction>self.fraction:
                partial=self.part(m,self.fraction,fraction)
                if self.sim.apply(partial,check=False):dirty.append(cutting_bounds(partial,self.sim.tools[m.tool]))
            self.fraction=fraction
            tip=m.start+(m.end-m.start)*fraction
        else:
            m=self.program.moves[-1]
            tip=m.end.copy()
        self.current=seconds
        return {"time_s":seconds,"tip":tip,"tool":m.tool,"line":m.line,"rpm":m.rpm,
                "spindle":m.spindle,"rapid":m.rapid,"dirty_bounds":dirty,"reset_stock":reset}
