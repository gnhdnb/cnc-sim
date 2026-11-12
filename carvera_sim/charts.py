"""Linked dynamic-metric charts with playback cursors and click/drag seeking."""
import numpy as np
from PySide6 import QtCore
import pyqtgraph as pg
from .metrics import METRIC_DTYPE


class MetricsCharts(pg.GraphicsLayoutWidget):
    seekRequested=QtCore.Signal(float)

    def __init__(self,parent=None):
        super().__init__(parent=parent)
        self.setBackground('#151b24')
        self.setMinimumHeight(165)
        self.setMaximumHeight(260)
        self.rows=np.empty(0,dtype=METRIC_DTYPE)
        self.duration=0.
        self.plots=[];self.curves=[];self.cursor_lines=[]
        self.fields=('removal_rate_mm3_min','approach_speed_mm_min')
        self.labels=('Excavation','Approach ≤20 mm')
        self.units=('mm³/min','mm/min')
        for i,(label,unit,color) in enumerate(zip(self.labels,self.units,('#64c7ff','#ffa766'))):
            plot=self.addPlot(row=i,col=0)
            plot.setLabel('left',units=unit)
            plot.getAxis('left').enableAutoSIPrefix(False)
            plot.getAxis('left').setWidth(90)
            plot.showGrid(x=True,y=True,alpha=.15)
            plot.setMouseEnabled(x=True,y=False)
            plot.setMenuEnabled(False)
            curve=plot.plot(pen=pg.mkPen(color,width=1.5),connect='finite')
            curve.setDownsampling(auto=True,method='peak')
            curve.setClipToView(True)
            cursor=pg.InfiniteLine(pos=0,angle=90,movable=True,pen=pg.mkPen('#e9edf3',width=1))
            cursor.sigPositionChangeFinished.connect(lambda line:self.seekRequested.emit(float(line.value())))
            plot.addItem(cursor)
            if i:plot.setXLink(self.plots[0]);plot.setLabel('bottom','Nominal time',units='s')
            else:plot.hideAxis('bottom')
            self.plots.append(plot);self.curves.append(curve);self.cursor_lines.append(cursor)
        self.scene().sigMouseClicked.connect(self._clicked)

    def _clicked(self,event):
        if event.button()!=QtCore.Qt.MouseButton.LeftButton:return
        for plot in self.plots:
            if plot.vb.sceneBoundingRect().contains(event.scenePos()):
                x=plot.vb.mapSceneToView(event.scenePos()).x()
                self.seekRequested.emit(min(self.duration,max(0.,float(x))))
                return

    def set_metrics(self,rows,duration):
        self.rows=rows
        self.duration=duration
        x=np.column_stack((rows['t_start_s'],rows['t_end_s'])).reshape(-1)
        for i,field in enumerate(self.fields):
            self.curves[i].setData(x,np.repeat(rows[field],2),connect='finite')
            finite=rows[field][np.isfinite(rows[field])]
            peak=float(finite.max()) if len(finite) else 0.
            self.plots[i].setYRange(0,max(1.,peak*1.05),padding=0)
            self.cursor_lines[i].setBounds((0,duration))
        self.plots[0].setXRange(0,max(duration,.01),padding=0)
        self.set_time(0.)

    def set_time(self,seconds):
        index=min(len(self.rows)-1,int(np.searchsorted(self.rows['t_end_s'],seconds,side='right'))) if len(self.rows) else -1
        for i,field in enumerate(self.fields):
            self.cursor_lines[i].setValue(seconds)
            value=float(self.rows[field][index]) if index>=0 else 0.
            number=f'{value:,.1f}' if np.isfinite(value) else 'undefined (zero duration)'
            self.plots[i].setTitle(f'{self.labels[i]}: {number} {self.units[i]}',color='#d6e0eb',size='9pt')
