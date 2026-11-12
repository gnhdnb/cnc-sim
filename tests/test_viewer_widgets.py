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
