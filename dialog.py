"""Dialog: convert between WGS 84 decimal degrees, DMS, UTM (incl. Garmin string) and
Indonesia TM-3. Any input format -> all output formats. Transformations: QGIS/PROJ."""
import math
import re
from pathlib import Path

from qgis.PyQt.QtWidgets import (QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                                 QLineEdit, QComboBox, QPushButton, QPlainTextEdit, QLabel, QCheckBox,
                                 QApplication, QMessageBox, QFileDialog)
from qgis.core import (QgsCoordinateTransform, QgsProject, QgsPointXY, QgsGeometry, QgsVectorLayer,
                       QgsFeature, QgsField, QgsMapLayerProxyModel, QgsVectorFileWriter)
from qgis.gui import QgsMapLayerComboBox, QgsFieldComboBox, QgsFileWidget, QgsMapToolEmitPoint

from . import core as c
from . import engine as eng

FORMATS = ["Geographic WGS 84 (decimal degrees or DMS)", "UTM (WGS 84)", "Indonesia TM-3 (DGN95)"]
GEO, UTM, TM3 = 0, 1, 2
ZONE_ITEMS = [c.AUTO] + c.CHOICES


def add_row(form, store, key, text, widget):
    lab = QLabel(text)
    form.addRow(lab, widget)
    store[key] = (lab, widget)


def show_rows(store, keys):
    for k, (lab, w) in store.items():
        lab.setVisible(k in keys)
        w.setVisible(k in keys)


def north_from(v, default_north):
    s = str(v).strip().upper()
    return s.startswith("N") if s[:1] in ("N", "S") else default_north


class CalculatorDialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("Coordinate Calculator: WGS 84 / DMS / UTM / Indonesia TM-3")
        self.resize(680, 700)
        self._last = None
        self._pt_id = None
        self.tool = QgsMapToolEmitPoint(iface.mapCanvas())
        self.tool.canvasClicked.connect(self._picked)
        tabs = QTabWidget()
        tabs.addTab(self._single_tab(), "Single point")
        tabs.addTab(self._batch_tab(), "Batch (layer / CSV / Excel)")
        QVBoxLayout(self).addWidget(tabs)
        self._s_refresh()
        self._b_refresh()

    # ------------------------------------------------------------------ single
    def _single_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        self.s_fmt = QComboBox()
        self.s_fmt.addItems(FORMATS)
        self.s_fmt.currentIndexChanged.connect(self._s_refresh)
        form.addRow("Input format:", self.s_fmt)
        self.sr = {}
        self.e1, self.e2, self.e3 = QLineEdit(), QLineEdit(), QLineEdit()
        self.s_hemi = QComboBox()
        self.s_hemi.addItems(["North", "South"])
        self.s_zone = QComboBox()
        self.s_zone.addItems(ZONE_ITEMS)
        add_row(form, self.sr, "e1", "", self.e1)
        add_row(form, self.sr, "hemi", "Hemisphere:", self.s_hemi)
        add_row(form, self.sr, "e2", "", self.e2)
        add_row(form, self.sr, "e3", "", self.e3)
        add_row(form, self.sr, "zone", "", self.s_zone)
        lay.addLayout(form)
        self.s_hint = QLabel()
        self.s_hint.setStyleSheet("color: gray")
        self.s_hint.setWordWrap(True)
        lay.addWidget(self.s_hint)
        btns = QHBoxLayout()
        for text, fn in (("Convert", self.s_convert), ("Pick from map", self._pick),
                         ("Add point to map", self._add_point), ("Copy result", self._copy)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        lay.addLayout(btns)
        self.s_out = QPlainTextEdit()
        self.s_out.setReadOnly(True)
        self.s_out.setStyleSheet("font-family: monospace")
        lay.addWidget(self.s_out)
        return w

    def _s_refresh(self):
        f = self.s_fmt.currentIndex()
        labels = self.sr
        if f == GEO:
            labels["e1"][0].setText("Latitude:")
            labels["e2"][0].setText("Longitude:")
            labels["zone"][0].setText("TM-3 zone for output:")
            show_rows(self.sr, {"e1", "e2", "zone"})
            hint = "Decimal degrees or DMS, e.g. -5.3589  or  5°21'32.18\"S  or  5 21 32.18 LS."
        elif f == UTM:
            labels["e1"][0].setText("UTM zone (1-60):")
            labels["e2"][0].setText("Easting (m):")
            labels["e3"][0].setText("Northing (m):")
            labels["zone"][0].setText("TM-3 zone for output:")
            show_rows(self.sr, {"e1", "hemi", "e2", "e3", "zone"})
            hint = "Choose the hemisphere explicitly (band letters are not read)."
        else:
            labels["e1"][0].setText("Easting (m):")
            labels["e2"][0].setText("Northing (m):")
            labels["zone"][0].setText("TM-3 zone of the input:")
            show_rows(self.sr, {"e1", "e2", "zone"})
            hint = "Easting alone does not identify the zone, so pick the input's TM-3 zone."
        self.s_hint.setText(hint + "  Results are shown in all formats.")

    def _s_input(self):
        f = self.s_fmt.currentIndex()
        label = c.label_of(self.s_zone.currentText())
        out_zone = None if label is None else c.ZONE_BY_LABEL[label]
        if f == GEO:
            return (c.parse_angle(self.e2.text(), "longitude"),
                    c.parse_angle(self.e1.text(), "latitude"), out_zone)
        if f == UTM:
            zone, e, n = c.to_float(self.e1.text()), c.to_float(self.e2.text()), c.to_float(self.e3.text())
            if not all(math.isfinite(v) for v in (zone, e, n)):
                raise ValueError("Zone, easting and northing must be numbers.")
            lon, lat = eng.from_utm(int(zone), self.s_hemi.currentIndex() == 0, e, n)
            return lon, lat, out_zone
        if out_zone is None:
            raise ValueError("Select the TM-3 zone of the input.")
        e, n = c.to_float(self.e1.text()), c.to_float(self.e2.text())
        if not (math.isfinite(e) and math.isfinite(n)):
            raise ValueError("Easting and northing must be numbers.")
        lon, lat = eng.from_tm3(out_zone, e, n)
        return lon, lat, None

    def s_convert(self):
        try:
            lon, lat, zone = self._s_input()
            o = eng.all_outputs(lon, lat, zone)
        except ValueError as exc:
            QMessageBox.warning(self, "Input error", str(exc))
            return
        self._last = o
        self.s_out.setPlainText(eng.describe(o))

    def _copy(self):
        QApplication.clipboard().setText(self.s_out.toPlainText())

    def _pick(self):
        self.iface.mapCanvas().setMapTool(self.tool)
        self.iface.messageBar().pushMessage("Coordinate Calculator", "Click on the map to pick a point.", duration=4)

    def _picked(self, point, _button):
        canvas = self.iface.mapCanvas()
        p = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(), eng.WGS,
                                   QgsProject.instance()).transform(point)
        self.s_fmt.setCurrentIndex(GEO)
        self.e1.setText(f"{p.y():.8f}")
        self.e2.setText(f"{p.x():.8f}")
        canvas.unsetMapTool(self.tool)
        self.s_convert()
        self.show()
        self.raise_()
        self.activateWindow()

    def _add_point(self):
        o = self._last
        if not o:
            QMessageBox.information(self, "Nothing to add", "Convert a point first.")
            return
        lyr = QgsProject.instance().mapLayer(self._pt_id) if self._pt_id else None
        if lyr is None:
            lyr = QgsVectorLayer("Point?crs=EPSG:4326&field=utm:string&field=tm3:string", "Converted points", "memory")
            QgsProject.instance().addMapLayer(lyr)
            self._pt_id = lyr.id()
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(o["lon"], o["lat"])))
        f.setAttributes([o.get("garmin", ""), f"{o['tm3_zone']} {o['tm3_e']:.0f} {o['tm3_n']:.0f}" if "tm3_e" in o else ""])
        lyr.dataProvider().addFeatures([f])
        lyr.updateExtents()
        lyr.triggerRepaint()

    # ------------------------------------------------------------------- batch
    def _batch_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        self.br = {}
        self.layer_cb = QgsMapLayerComboBox()
        self.layer_cb.setFilters(QgsMapLayerProxyModel.VectorLayer)  # includes attribute-only tables
        browse = QPushButton("Open CSV / Excel file…")
        browse.clicked.connect(self._open_file)
        self.b_fmt = QComboBox()
        self.b_fmt.addItems(FORMATS)
        self.b_fmt.currentIndexChanged.connect(self._b_refresh)
        self.x_cb, self.y_cb, self.zf_cb, self.hf_cb = (QgsFieldComboBox() for _ in range(4))
        self.zf_cb.setAllowEmptyFieldName(True)
        self.hf_cb.setAllowEmptyFieldName(True)
        self.b_uz = QLineEdit()
        self.b_uh = QComboBox()
        self.b_uh.addItems(["North", "South"])
        self.b_zone = QComboBox()
        self.b_zone.addItems(ZONE_ITEMS)
        self.out_file = QgsFileWidget()
        self.out_file.setStorageMode(QgsFileWidget.SaveFile)
        self.out_file.setFilter("CSV (*.csv);;Excel (*.xlsx);;GeoPackage (*.gpkg)")
        form.addRow("Input layer / table:", self.layer_cb)
        form.addRow("", browse)
        form.addRow("Input format:", self.b_fmt)
        add_row(form, self.br, "x", "", self.x_cb)
        add_row(form, self.br, "y", "", self.y_cb)
        add_row(form, self.br, "zf", "Zone field (optional):", self.zf_cb)
        add_row(form, self.br, "uz", "Fixed UTM zone (1-60):", self.b_uz)
        add_row(form, self.br, "hf", "Hemisphere field (N/S, optional):", self.hf_cb)
        add_row(form, self.br, "uh", "Fixed hemisphere:", self.b_uh)
        add_row(form, self.br, "zone", "", self.b_zone)
        form.addRow("Save result to file (optional):", self.out_file)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(QLabel("Add columns:"))
        self.chk = {}
        for key, text in (("dd", "Decimal degrees"), ("dms", "DMS"), ("utm", "UTM + Garmin"), ("tm3", "TM-3")):
            self.chk[key] = QCheckBox(text)
            self.chk[key].setChecked(True)
            row.addWidget(self.chk[key])
        lay.addLayout(row)
        run = QPushButton("Convert")
        run.clicked.connect(self._b_run)
        lay.addWidget(run)
        self.b_log = QPlainTextEdit()
        self.b_log.setReadOnly(True)
        lay.addWidget(self.b_log)
        self.layer_cb.layerChanged.connect(self._b_layer)
        return w

    def _b_layer(self):
        lyr = self.layer_cb.currentLayer()
        for cb in (self.x_cb, self.y_cb, self.zf_cb, self.hf_cb):
            cb.setLayer(lyr)
        if lyr is None:
            return
        f = self.b_fmt.currentIndex()
        px, py = (r"lon|lng|bujur|^x$", r"lat|lintang|^y$") if f == GEO else \
                 (r"east|timur|^x$|^e$", r"north|utara|^y$|^n$")
        for cb, pat in ((self.x_cb, px), (self.y_cb, py), (self.zf_cb, r"zone|zona|utm_?zone|^zn$"),
                        (self.hf_cb, r"hemi|belahan")):
            cb.setField("")
            for name in lyr.fields().names():
                if re.search(pat, name, re.I):
                    cb.setField(name)
                    break
        if f != UTM:
            self.hf_cb.setField("")

    def _b_refresh(self):
        f = self.b_fmt.currentIndex()
        r = self.br
        r["x"][0].setText("Longitude field:" if f == GEO else "Easting field:")
        r["y"][0].setText("Latitude field:" if f == GEO else "Northing field:")
        r["zone"][0].setText("TM-3 zone of the input:" if f == TM3 else "TM-3 zone for output:")
        show_rows(r, {GEO: {"x", "y", "zone"}, UTM: {"x", "y", "zf", "uz", "hf", "uh", "zone"},
                      TM3: {"x", "y", "zf", "zone"}}[f])
        self._b_layer()

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open table", "",
                                              "CSV / Excel (*.csv *.txt *.xlsx *.xls);;All files (*)")
        if not path:
            return
        lyr = QgsVectorLayer(path, Path(path).stem, "ogr")
        if not lyr.isValid():
            QMessageBox.warning(self, "Cannot open", "QGIS could not read this file. For unusual CSV formats "
                                "use Layer > Add Layer > Add Delimited Text Layer.")
            return
        QgsProject.instance().addMapLayer(lyr)
        self.layer_cb.setLayer(lyr)
        self._b_layer()

    def _b_run(self):
        src = self.layer_cb.currentLayer()
        f = self.b_fmt.currentIndex()
        xf, yf = self.x_cb.currentField(), self.y_cb.currentField()
        zf, hf = self.zf_cb.currentField(), self.hf_cb.currentField()
        if src is None or not xf or not yf or xf == yf:
            QMessageBox.warning(self, "Input", "Choose a layer and two different coordinate fields.")
            return
        groups = [g for g in ("dd", "dms", "utm", "tm3") if self.chk[g].isChecked()]
        if not groups:
            QMessageBox.warning(self, "Output", "Tick at least one output column group.")
            return
        zlabel = c.label_of(self.b_zone.currentText())
        zone_obj = None if zlabel is None else c.ZONE_BY_LABEL[zlabel]
        fixed_utm = c.to_float(self.b_uz.text())
        if f == UTM and not zf and not (math.isfinite(fixed_utm) and 1 <= fixed_utm <= 60):
            QMessageBox.warning(self, "UTM zone", "Pick a zone field or enter a fixed UTM zone (1-60).")
            return
        if f == TM3 and not zf and zone_obj is None:
            QMessageBox.warning(self, "TM-3 zone", "Pick a zone field or select the TM-3 zone of the input.")
            return

        taken = set(src.fields().names())
        spec = []
        for g in groups:
            for name, key, typ in eng.GROUPS[g]:
                out_name, i = name, 2
                while out_name in taken:
                    out_name, i = f"{name}_{i}", i + 1
                taken.add(out_name)
                spec.append((out_name, key, typ))
        out = QgsVectorLayer("Point?crs=EPSG:4326", f"{src.name()}_converted", "memory")
        pr = out.dataProvider()
        pr.addAttributes(list(src.fields()) + [QgsField(n, t) for n, _k, t in spec])
        out.updateFields()

        done = bad = far = no_utm = 0
        rows = []
        for feat in src.getFeatures():
            extra, geom = [None] * len(spec), None
            try:
                if f == GEO:
                    lon, lat = eng.angle(feat[xf], "longitude"), eng.angle(feat[yf], "latitude")
                    out_zone = zone_obj
                else:
                    e, n = c.to_float(feat[xf]), c.to_float(feat[yf])
                    if not (math.isfinite(e) and math.isfinite(n)):
                        raise ValueError
                    out_zone = None if f == TM3 else zone_obj
                    if f == UTM:
                        zn = c.to_float(feat[zf]) if zf else fixed_utm
                        north = north_from(feat[hf], True) if hf else self.b_uh.currentIndex() == 0
                        lon, lat = eng.from_utm(int(zn), north, e, n)
                    else:
                        z = c.ZONE_BY_LABEL.get(c.norm_zone(feat[zf])) if zf else zone_obj
                        if z is None:
                            raise ValueError
                        lon, lat = eng.from_tm3(z, e, n)
                if not (math.isfinite(lon) and math.isfinite(lat)):
                    raise ValueError
                o = eng.all_outputs(lon, lat, out_zone)
                extra = []
                for _n, key, _t in spec:
                    v = o.get(key)
                    extra.append(round(v, 8 if key in ("lon", "lat") else 3) if isinstance(v, float) else v)
                geom = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
                far += 1 if o.get("tm3_far") else 0
                no_utm += 0 if "utm_e" in o else 1
                done += 1
            except Exception:
                bad += 1
                extra = [None] * len(spec)
            nf = QgsFeature(out.fields())
            nf.setAttributes(list(feat.attributes()) + extra)
            if geom:
                nf.setGeometry(geom)
            rows.append(nf)
        pr.addFeatures(rows)
        out.updateExtents()
        QgsProject.instance().addMapLayer(out)

        msg = [f"Rows: {len(rows)}   Converted: {done}"]
        if bad:
            msg.append(f"{bad} row(s) could not be converted (non-numeric, out of range, bad zone/hemisphere). "
                       f"Check decimal separators and zone values. They were kept with empty results.")
        if far:
            msg.append(f"⚠ {far} point(s) lie outside their TM-3 zone's 3° band.")
        if no_utm:
            msg.append(f"{no_utm} point(s) outside UTM range (80°S–84°N): UTM columns left empty.")
        path = self.out_file.filePath()
        if path:
            drv = {".csv": "CSV", ".xlsx": "XLSX", ".gpkg": "GPKG", ".shp": "ESRI Shapefile"}.get(
                Path(path).suffix.lower())
            if drv is None:
                msg.append("Unsupported output extension; result kept as a temporary layer only.")
            else:
                opt = QgsVectorFileWriter.SaveVectorOptions()
                opt.driverName, opt.fileEncoding = drv, "UTF-8"
                res = QgsVectorFileWriter.writeAsVectorFormatV3(
                    out, path, QgsProject.instance().transformContext(), opt)
                msg.append(f"Saved: {path}" if res[0] == QgsVectorFileWriter.NoError else f"Save failed: {res[1]}")
        msg.append("Result added to the project as a temporary layer (EPSG:4326 points).")
        self.b_log.setPlainText("\n".join(msg))
