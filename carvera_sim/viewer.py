"""Optional Qt/OpenGL UI. Simulation and seeking run on one dedicated worker."""
from __future__ import annotations
import sys
import threading
import time
import traceback
from collections import deque
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph.opengl as gl

from .engine import SnapshotCache, save_result, warmup
from .replay import Replay
from .mesh import stock_mesh, frusta_mesh, boxes_mesh
from .chunkmesh import ChunkMesher
from .charts import MetricsCharts


# Keep recessed surfaces legible when their normal faces away from a light.
gl.shaders.ShaderProgram("carvera_material", [
    gl.shaders.VertexShader("""
        uniform mat4 u_mvp;
        uniform mat3 u_normal;
        attribute vec4 a_position;
        attribute vec3 a_normal;
        attribute vec4 a_color;
        varying vec3 normal_direction;
        varying vec4 material_color;
        void main() {
            normal_direction = normalize(u_normal * a_normal);
            material_color = a_color;
            gl_Position = u_mvp * a_position;
        }
    """),
    gl.shaders.FragmentShader("""
        #ifdef GL_ES
        precision mediump float;
        #endif
        varying vec3 normal_direction;
        varying vec4 material_color;
        void main() {
            vec3 n = normalize(normal_direction);
            float key = max(0.0, dot(n, normalize(vec3(0.4, 0.7, 1.0))));
            float fill = max(0.0, dot(n, normalize(vec3(-0.7, -0.2, 0.5))));
            float illumination = 0.42 + 0.40 * key + 0.18 * fill;
            gl_FragColor = vec4(material_color.rgb * illumination, material_color.a);
        }
    """)
])


class Signals(QtCore.QObject):
    progress=QtCore.Signal(float,int)
    ready=QtCore.Signal(object)
    frame=QtCore.Signal(object)
    error=QtCore.Signal(str)


class SeekSlider(QtWidgets.QSlider):
    def _seek_at(self,event):
        fraction=min(1.,max(0.,event.position().x()/max(1,self.width()-1)))
        self.setValue(round(self.minimum()+fraction*(self.maximum()-self.minimum())))

    def mousePressEvent(self,event):
        if event.button()==QtCore.Qt.MouseButton.LeftButton:
            self.setSliderDown(True);self._seek_at(event);event.accept()
        else:super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.isSliderDown():self._seek_at(event);event.accept()
        else:super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==QtCore.Qt.MouseButton.LeftButton:
            self._seek_at(event);self.setSliderDown(False);event.accept()
        else:super().mouseReleaseEvent(event)


class Worker(threading.Thread):
    def __init__(self,sim,program,output,report_extra):
        super().__init__(daemon=True,name="carvera-simulation")
        self.sim,self.program,self.output=sim,program,output
        self.extra=report_extra
        self.signals=Signals()
        self.condition=threading.Condition()
        self.pending=None
        self.stopping=threading.Event()
        self.exit_code=1

    def request(self,seconds,stride,generation):
        with self.condition:
            self.pending=(seconds,stride,generation)
            self.condition.notify()

    def stop(self):
        self.stopping.set()
        with self.condition:self.condition.notify()

    def run(self):
        try:
            began=time.perf_counter();warmup();jit=time.perf_counter()-began
            snapshots=SnapshotCache(len(self.program.moves))
            report=self.sim.run(self.program,progress=self.signals.progress.emit,
                                snapshots=snapshots,cancelled=self.stopping.is_set)
            report.update(self.extra,jit_warmup_s=jit)
            report,path,report_path=save_result(self.output,self.sim.grid,report)
            self.exit_code=report["exit_code"]
            self.signals.ready.emit(report)
            replay=Replay(self.sim,self.program,snapshots)
            chunks=ChunkMesher(self.sim.grid,self.sim.stock)
            previous_generation=None
            previous_stride=None
            self.request(0.,1,0)
            while not self.stopping.is_set():
                with self.condition:
                    while self.pending is None and not self.stopping.is_set():self.condition.wait()
                    if self.stopping.is_set():break
                    seconds,stride,generation=self.pending
                    self.pending=None
                frame_start=time.perf_counter()
                state=replay.seek(seconds,self.stopping.is_set)
                reset=state['reset_stock'] or generation!=previous_generation or stride!=previous_stride
                if stride==1:
                    updates=chunks.update(state['dirty_bounds'],reset=reset,cancelled=self.stopping.is_set)
                    # One GPU draw avoids hundreds of per-chunk state changes.
                    # Only surface arrays are packed; dirty chunks alone read voxels.
                    updates=[((0,0,0),*chunks.combined())] if updates else []
                    actual_stride=1
                else:
                    vertices,faces,actual_stride=stock_mesh(self.sim.grid,self.sim.stock,stride)
                    updates=[((-1,-1,-1),vertices,faces)];reset=True
                previous_generation,previous_stride=generation,stride
                state.update(mesh_updates=updates,reset_mesh=reset,stride=actual_stride,generation=generation,
                             frame_compute_ms=(time.perf_counter()-frame_start)*1000)
                self.signals.frame.emit(state)
        except InterruptedError:
            pass
        except Exception:
            self.exit_code=1
            self.signals.error.emit(traceback.format_exc())


class View(gl.GLViewWidget):
    """Explicit mouse mapping, consistent on Windows/Linux/macOS."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.paint_times=deque(maxlen=61)
        self.frameSwapped.connect(self.record_swap)

    def record_swap(self):
        now=time.perf_counter()
        if self.paint_times and now-self.paint_times[-1]>.5:self.paint_times.clear()
        self.paint_times.append(now)

    @property
    def fps(self):
        if len(self.paint_times)<2:return 0.
        span=self.paint_times[-1]-self.paint_times[0]
        return (len(self.paint_times)-1)/span if span>0 else 0.

    def mouseMoveEvent(self,event):
        delta=event.position()-self.mousePos
        self.mousePos=event.position()
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            if event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
                self.pan(delta.x(),delta.y(),0,relative="view-upright")
            else:self.orbit(-delta.x(),delta.y())
        elif event.buttons() & (QtCore.Qt.MouseButton.RightButton|QtCore.Qt.MouseButton.MiddleButton):
            self.pan(delta.x(),delta.y(),0,relative="view-upright")


class Window(QtWidgets.QMainWindow):
    def __init__(self,sim,program,output,report_extra=None):
        super().__init__()
        self.sim,self.program=sim,program
        self.report=None
        self.playing=False
        self.target=0.
        self.generation=0
        self.rendered_tool=None
        self.tool_items=[]
        self.last_tick=time.perf_counter()
        self.setWindowTitle("Carvera • Voxel verification")
        self.resize(1260,820)
        self.setStyleSheet("""
            QWidget {background:#151b24;color:#e4eaf2;font-size:13px;}
            QPushButton,QComboBox,QDoubleSpinBox {background:#293546;border:1px solid #405069;border-radius:4px;padding:7px;}
            QPushButton:hover {background:#38516e;} QPushButton:disabled {color:#768191;}
            QSlider::groove:horizontal {height:6px;background:#364357;}
            QSlider::handle:horizontal {background:#5bb8ed;width:15px;margin:-5px 0;border-radius:5px;}
            QListWidget {background:#111720;border:1px solid #364357;}
            QLabel#title {font-size:22px;font-weight:600;} QLabel#muted {color:#aab6c7;}
        """)
        root=QtWidgets.QWidget();self.setCentralWidget(root)
        layout=QtWidgets.QVBoxLayout(root)
        header=QtWidgets.QHBoxLayout()
        title=QtWidgets.QLabel("CARVERA  /  VOXEL SIMULATOR");title.setObjectName("title")
        header.addWidget(title);header.addStretch()
        self.badge=QtWidgets.QLabel("Preparing simulation…")
        header.addWidget(self.badge);layout.addLayout(header)
        self.summary=QtWidgets.QLabel(f"{sim.stock.pitch:g} mm voxels   •   {sim.stock.shape[0]} × {sim.stock.shape[1]} × {sim.stock.shape[2]}   •   {len(program.moves):,} path segments")
        self.summary.setObjectName("muted");layout.addWidget(self.summary)
        splitter=QtWidgets.QSplitter()
        layout.addWidget(splitter,1)
        side=QtWidgets.QWidget();side_layout=QtWidgets.QVBoxLayout(side)
        side_layout.setContentsMargins(0,8,8,0)
        side_layout.addWidget(QtWidgets.QLabel("VERIFICATION"))
        self.details=QtWidgets.QLabel("Computing the final stock and checking collisions.\nThe result file will be saved before playback.")
        self.details.setWordWrap(True)
        self.details.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        detail_scroll=QtWidgets.QScrollArea();detail_scroll.setWidgetResizable(True)
        detail_scroll.setWidget(self.details);detail_scroll.setMinimumHeight(110)
        side_layout.addWidget(detail_scroll,2)
        side_layout.addWidget(QtWidgets.QLabel("COLLISIONS  ·  CLICK TO SEEK"))
        self.collisions=QtWidgets.QListWidget();side_layout.addWidget(self.collisions,1)
        self.collisions.itemClicked.connect(self.collision_clicked)
        help_label=QtWidgets.QLabel("Mouse\nLeft drag: orbit\nRight / middle drag: pan\nWheel: zoom\nShift + left drag: pan\n\nKeyboard\nSpace: start / pause\nHome: stop and rewind")
        help_label.setObjectName("muted");side_layout.addWidget(help_label)
        splitter.addWidget(side)
        self.view=View();self.view.setBackgroundColor((20,26,35,255));splitter.addWidget(self.view)
        splitter.setSizes([270,950])
        self.stock_items={}
        self.fixture_items=[]
        for name,box in sim.machine.fixtures:
            vertices,faces=boxes_mesh([box])
            item=gl.GLMeshItem(vertexes=vertices,faces=faces,smooth=False,color=(.67,.25,.19,.8),shader="shaded",glOptions="translucent")
            self.view.addItem(item);self.fixture_items.append(item)
        paths=np.array([[m.start,m.end] for m in program.moves],dtype=np.float32).reshape(-1,3)
        # Display path may be decimated; cutting geometry is never decimated.
        if len(paths)>400000:paths=paths.reshape(-1,2,3)[::int(np.ceil(len(paths)/400000))].reshape(-1,3)
        self.path_item=gl.GLLinePlotItem(pos=paths,color=(.30,.60,.82,.22),mode="lines",width=1,antialias=False)
        self.view.addItem(self.path_item)
        axes=gl.GLAxisItem();axes.setSize(10,10,10);self.view.addItem(axes)
        self.reset_view()
        self.charts=MetricsCharts()
        self.charts.seekRequested.connect(self.chart_seek)
        layout.addWidget(self.charts)
        self.timeline=SeekSlider(QtCore.Qt.Orientation.Horizontal)
        self.timeline.setPageStep(10000);self.timeline.setSingleStep(1000)
        self.timeline.setRange(0,1000000);self.timeline.setEnabled(False)
        self.timeline.valueChanged.connect(self.timeline_changed);layout.addWidget(self.timeline)
        bar=QtWidgets.QHBoxLayout();layout.addLayout(bar)
        self.start_button=QtWidgets.QPushButton("Start");self.pause_button=QtWidgets.QPushButton("Pause")
        self.stop_button=QtWidgets.QPushButton("Stop")
        for button,callback in ((self.start_button,self.start_playback),(self.pause_button,self.pause),(self.stop_button,self.stop)):
            bar.addWidget(button);button.clicked.connect(callback);button.setEnabled(False)
        bar.addWidget(QtWidgets.QLabel("Speed"))
        self.speed=QtWidgets.QComboBox()
        for v in (.1,.25,.5,1,2,5,10,25,50,100,250):self.speed.addItem(f"{v:g}×",v)
        self.speed.setCurrentIndex(6);bar.addWidget(self.speed)
        self.seconds=QtWidgets.QDoubleSpinBox();self.seconds.setDecimals(2)
        self.seconds.setRange(0,program.duration);self.seconds.setSuffix(" s")
        self.seconds.setKeyboardTracking(False);self.seconds.editingFinished.connect(lambda:self.seek(self.seconds.value()))
        bar.addWidget(self.seconds)
        bar.addWidget(QtWidgets.QLabel("Display"))
        self.detail=QtWidgets.QComboBox()
        for label,stride in (("Full resolution",1),("2× voxels",2),("4× voxels",4)):self.detail.addItem(label,stride)
        self.detail.currentIndexChanged.connect(lambda:self.seek(self.target));bar.addWidget(self.detail)
        self.show_head=QtWidgets.QCheckBox("Head");self.show_head.setChecked(True)
        self.show_head.toggled.connect(self.toggle_head);bar.addWidget(self.show_head)
        show_path=QtWidgets.QCheckBox("Path");show_path.setChecked(True)
        show_path.toggled.connect(self.path_item.setVisible);bar.addWidget(show_path)
        reset=QtWidgets.QPushButton("Reset view");reset.clicked.connect(self.reset_view);bar.addWidget(reset)
        self.position=QtWidgets.QLabel("Compiling geometry kernels on first use…")
        self.position.setObjectName("muted");layout.addWidget(self.position)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self.tick);self.timer.start()
        QtGui.QShortcut(QtGui.QKeySequence("Space"),self,activated=self.toggle_play)
        QtGui.QShortcut(QtGui.QKeySequence("Home"),self,activated=self.stop)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Q"),self,activated=self.close)
        self.worker=Worker(sim,program,output,report_extra or {})
        self.worker.signals.progress.connect(self.progress)
        self.worker.signals.ready.connect(self.ready)
        self.worker.signals.frame.connect(self.frame)
        self.worker.signals.error.connect(self.error)
        self.worker.start()

    def reset_view(self):
        center=self.sim.stock.origin+self.sim.stock.dimensions/2
        self.view.setCameraPosition(pos=QtGui.QVector3D(*map(float,center)),distance=float(max(self.sim.stock.dimensions)*1.9),elevation=32,azimuth=-55)

    def progress(self,fraction,line):
        self.badge.setText(f"Verifying {fraction:.0%}")
        self.position.setText(f"Checking NC line {line:,} · final result is being computed")

    def ready(self,report):
        self.report=report
        self.charts.set_metrics(self.sim.metrics,self.program.duration)
        status=report["status"]
        self.badge.setText(status.replace("_"," ").upper())
        self.badge.setStyleSheet("color:"+("#f0957d" if status=="collisions" else "#edc56a" if status=="incomplete" else "#7ad4b1"))
        text=f"{report['collision_count']} collision records\n{report['removed_volume_mm3']:,.1f} mm³ removed\n{report['simulation_time_s']:.2f} s simulation\n{report['nominal_job_time_s']/60:.1f} min nominal job\n\nFinal .npy and .report.json saved."
        if report["incomplete_reasons"]:text+="\n\nIncomplete model:\n"+"\n".join(report["incomplete_reasons"])
        self.details.setText(text)
        for c in report["collisions"]:
            item=QtWidgets.QListWidgetItem(f"L{c['line']}  ·  {c['body']} → {c['target']}\n{c['time_s']:.2f} s  ·  {c['reason']}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole,c["time_s"])
            self.collisions.addItem(item)
        for widget in (self.start_button,self.pause_button,self.stop_button,self.timeline):widget.setEnabled(True)

    def frame(self,state):
        if state["generation"]!=self.generation:return
        if state['reset_mesh']:
            for item in self.stock_items.values():self.view.removeItem(item)
            self.stock_items.clear()
        for key,vertices,faces in state['mesh_updates']:
            item=self.stock_items.get(key)
            if not len(faces):
                if item is not None:self.view.removeItem(item);del self.stock_items[key]
                continue
            if item is None:
                item=gl.GLMeshItem(vertexes=vertices,faces=faces,smooth=False,color=(.76,.79,.83,1),
                                   shader='carvera_material',glOptions='opaque')
                self.stock_items[key]=item;self.view.addItem(item)
            else:item.setMeshData(vertexes=vertices,faces=faces)
        if self.rendered_tool!=state["tool"]:
            for item,role in self.tool_items:self.view.removeItem(item)
            self.tool_items=[]
            tool=self.sim.tools[state["tool"]]
            definitions=[("cutter",tool.cutting,np.empty((0,6)))]+[(b.role,b.frusta,b.boxes) for b in self.sim.machine.bodies(tool)]
            for role,rows,boxes in definitions:
                for mesh in (frusta_mesh(rows),boxes_mesh(boxes)):
                    vertices,faces=mesh
                    if not len(faces):continue
                    color=(.25,.70,.93,1) if role=="cutter" else ((.65,.72,.85,.17) if role=="head" else (.47,.55,.66,.65))
                    item=gl.GLMeshItem(vertexes=vertices,faces=faces,smooth=False,color=color,shader="shaded",glOptions="opaque" if role=="cutter" else "translucent",drawEdges=role=="head",edgeColor=(.6,.7,.8,.5))
                    self.view.addItem(item);self.tool_items.append((item,role))
            self.rendered_tool=state["tool"]
        for item,role in self.tool_items:
            item.resetTransform();item.translate(*map(float,state["tip"]))
            item.setVisible(self.show_head.isChecked() or role in ("cutter","shank","neck"))
        with QtCore.QSignalBlocker(self.timeline):
            self.timeline.setValue(round(1000000*state["time_s"]/max(self.program.duration,1e-10)))
        with QtCore.QSignalBlocker(self.seconds):self.seconds.setValue(state["time_s"])
        self.charts.set_time(state['time_s'])
        x,y,z=state["tip"]
        self.position.setText(f"L{state['line']:,} · T{state['tool']} · X {x:.3f}  Y {y:.3f}  Z {z:.3f} mm · {state['time_s']:.2f}/{self.program.duration:.2f} s · display {state['stride']*self.sim.stock.pitch:g} mm · {self.view.fps:.0f} FPS · update {state['frame_compute_ms']:.1f} ms")

    def toggle_head(self,enabled):
        for item,role in self.tool_items:item.setVisible(enabled or role in ("cutter","shank","neck"))

    def collision_clicked(self,item):self.pause();self.seek(item.data(QtCore.Qt.ItemDataRole.UserRole))
    def chart_seek(self,seconds):self.pause();self.seek(seconds)
    def timeline_changed(self,value):self.pause();self.seek(value*self.program.duration/1000000)
    def seek(self,seconds):
        self.target=min(self.program.duration,max(0.,seconds));self.generation+=1;self.request_frame()
    def request_frame(self):
        if self.report:self.worker.request(self.target,self.detail.currentData(),self.generation)
    def start_playback(self):
        if not self.report:return
        if self.target>=self.program.duration:self.seek(0.)
        self.playing=True;self.last_tick=time.perf_counter()
    def pause(self):self.playing=False
    def stop(self):self.pause();self.seek(0.)
    def toggle_play(self):self.pause() if self.playing else self.start_playback()
    def tick(self):
        now=time.perf_counter();dt=now-self.last_tick;self.last_tick=now
        if self.playing:
            self.target=min(self.program.duration,self.target+dt*self.speed.currentData())
            self.request_frame()
            if self.target>=self.program.duration:self.pause()
    def error(self,message):
        self.pause();self.badge.setText("ERROR");self.details.setText(message)
        self.position.setText("Verification failed; inspect the error. No successful result is claimed.")
        print(message,file=sys.stderr)
    def closeEvent(self,event):
        self.timer.stop();self.worker.stop();self.worker.join();event.accept()


def launch(sim,program,output,report_extra=None):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    window=Window(sim,program,output,report_extra)
    window.show()
    app.exec()
    return window.worker.exit_code
