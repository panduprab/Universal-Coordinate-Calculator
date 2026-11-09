from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

MENU = "&Universal Coordinate Calculator"


class TM3Plugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dlg = None

    def initGui(self):
        self.action = QAction(QgsApplication.getThemeIcon("/mActionCapturePoint.svg"),
                              "Universal Coordinate Calculator", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(MENU, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginMenu(MENU, self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dlg:
            self.dlg.close()
            self.dlg = None

    def run(self):
        if self.dlg is None:
            from .dialog import CalculatorDialog
            self.dlg = CalculatorDialog(self.iface)
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()
