import os
import pytest


def test_timeline_click_and_drag_seek(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6')
    pytest.importorskip('pyqtgraph')
    from PySide6 import QtCore,QtWidgets,QtTest
    from carvera_sim.viewer import SeekSlider
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    slider=SeekSlider(QtCore.Qt.Orientation.Horizontal)
    slider.resize(1001,30);slider.setRange(0,1000000);slider.show();app.processEvents()
    QtTest.QTest.mouseClick(slider,QtCore.Qt.MouseButton.LeftButton,pos=QtCore.QPoint(750,15))
    assert slider.value()==750000
    QtTest.QTest.mousePress(slider,QtCore.Qt.MouseButton.LeftButton,pos=QtCore.QPoint(250,15))
    QtTest.QTest.mouseMove(slider,QtCore.QPoint(500,15))
    QtTest.QTest.mouseRelease(slider,QtCore.Qt.MouseButton.LeftButton,pos=QtCore.QPoint(500,15))
    assert slider.value()==500000
    slider.close()


def test_metric_charts_values_cursor_and_seek(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6')
    import numpy as np
    from PySide6 import QtWidgets,QtTest
    from carvera_sim.charts import MetricsCharts
    from carvera_sim.metrics import METRIC_DTYPE
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    charts=MetricsCharts()
    data=np.array([(0,1,1,1,2,120,500,False),(1,2,2,1,0,0,0,True)],dtype=METRIC_DTYPE)
    charts.set_metrics(data,2)
    assert len(charts.plots)==2
    assert charts.curves[0].getData()[1].tolist()==[120,120,0,0]
    assert charts.curves[1].getData()[1].tolist()==[500,500,0,0]
    charts.set_time(1.5)
    assert all(line.value()==1.5 for line in charts.cursor_lines)
    spy=QtTest.QSignalSpy(charts.seekRequested)
    charts.cursor_lines[0].setValue(.4)
    charts.cursor_lines[0].sigPositionChangeFinished.emit(charts.cursor_lines[0])
    assert spy.count()==1 and spy.at(0)==[.4]
    charts.close()
