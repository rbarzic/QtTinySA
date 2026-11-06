"""Run with: QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests"""
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from PySide6.QtSql import QSqlDatabase, QSqlQuery
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox
from QtTinySA import Analyser, ApplicationController, Data
from modules.wireless_presets import ensure_wireless_presets


class WirelessPresetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / 'prefs.db'
        shutil.copy2(ROOT / 'src/QtTSAprefs.db', path)
        self.connection = uuid.uuid4().hex
        self.db = QSqlDatabase.addDatabase('QSQLITE', self.connection)
        self.db.setDatabaseName(str(path))
        self.assertTrue(self.db.open())
        self.execute('PRAGMA foreign_keys = ON')

    def tearDown(self):
        self.db.close()
        self.db = None
        QSqlDatabase.removeDatabase(self.connection)
        self.temp.cleanup()

    def execute(self, sql):
        query = QSqlQuery(self.db)
        self.assertTrue(query.exec(sql), query.lastError().text())
        rows = []
        while query.next():
            rows.append(tuple(query.value(i) for i in range(query.record().count())))
        return rows

    def test_channel_mapping_and_idempotent_migration(self):
        original = self.execute('SELECT * FROM frequencies ORDER BY ID')
        ensure_wireless_presets(self.db)
        ble = dict(self.execute(
            "SELECT name, startF FROM frequencies JOIN freqtype ON type = freqtype.ID "
            "WHERE preset = 'BLE 2G' AND stopF = 0"))
        self.assertEqual(len(ble), 40)
        self.assertEqual(ble['ch37 (adv)'], 2402_000_000)
        self.assertEqual(ble['ch38 (adv)'], 2426_000_000)
        self.assertEqual(ble['ch39 (adv)'], 2480_000_000)
        self.assertEqual(ble['ch0'], 2404_000_000)
        self.assertEqual(ble['ch10'], 2424_000_000)
        self.assertEqual(ble['ch11'], 2428_000_000)
        self.assertEqual(ble['ch36'], 2478_000_000)
        self.assertEqual(sorted(ble.values()), list(range(2402_000_000, 2481_000_000, 2_000_000)))
        zigbee = dict(self.execute(
            "SELECT name, startF FROM frequencies JOIN freqtype ON type = freqtype.ID "
            "WHERE preset = 'Zigbee 2G' AND stopF = 0"))
        self.assertEqual(zigbee, {f'ch{ch}': (2405 + (ch - 11) * 5) * 1_000_000
                                  for ch in range(11, 27)})
        seeded = self.execute('SELECT * FROM frequencies ORDER BY ID')
        self.assertEqual(seeded[:len(original)], original)
        ensure_wireless_presets(self.db)
        self.assertEqual(self.execute('SELECT * FROM frequencies ORDER BY ID'), seeded)
        # User edits survive subsequent starts.
        self.execute("UPDATE frequencies SET visible = 0 WHERE name = 'ch37 (adv)'")
        ensure_wireless_presets(self.db)
        self.assertEqual(self.execute("SELECT visible FROM frequencies WHERE name = 'ch37 (adv)'"), [(0,)])

    def test_dropdown_selection_and_sweep_ranges(self):
        ensure_wireless_presets(self.db)
        data = SimpleNamespace(config=self.db)
        data.bandselect = Data._set_bandselect(data)
        data.bandstype = Data._set_bandstype(data)
        ui = SimpleNamespace(band_box=QComboBox(), filterBox=QComboBox())
        ui.band_box.setModel(data.bandselect.tm)
        ui.band_box.setModelColumn(1)
        ui.filterBox.setModel(data.bandstype.tm)
        ui.filterBox.setModelColumn(1)
        for name in ('centre_freq', 'span_freq', 'start_freq', 'stop_freq'):
            spin = QDoubleSpinBox()
            spin.setRange(0, 10000)
            spin.setDecimals(6)
            setattr(ui, name, spin)
        analyser = SimpleNamespace(ui=ui, data=data, setting_change=lambda: None,
                                   set_mixer_highlighting=lambda: None)
        analyser.setGraphFreq = lambda start, stop: setattr(analyser, 'sweep', (start, stop))
        analyser.setCentreFreq = lambda: Analyser.setCentreFreq(analyser)
        analyser.setStartFreq = lambda: Analyser.setStartFreq(analyser)
        controller = SimpleNamespace(data=data, analyser=analyser)
        ui.band_box.currentIndexChanged.connect(lambda: Analyser.band_changed(analyser))
        for preset, count, span in (('BLE 2G', 41, 4), ('Zigbee 2G', 17, 5), ('WiFi 2G', 16, 94)):
            with self.subTest(preset=preset):
                ui.filterBox.setCurrentIndex(ui.filterBox.findText(preset))
                ApplicationController.set_band_filter(controller, preset)
                self.assertEqual(ui.band_box.count(), count)
                for index in range(ui.band_box.count()):
                    ui.band_box.setCurrentIndex(index)
                    # Also exercise the first row if its index was already selected.
                    Analyser.band_changed(analyser)
                    record = data.bandselect.tm.record(index)
                    start, stop = record.value('startF'), record.value('stopF')
                    if stop in (0, '', start):
                        self.assertEqual(ui.centre_freq.value(), start / 1e6)
                        self.assertEqual(ui.span_freq.value(), span)
                        self.assertEqual(analyser.sweep, (start - span * 500_000, start + span * 500_000))
                    else:
                        self.assertEqual(analyser.sweep, (start, stop))
        # Model resets can temporarily clear the selection; don't attempt to tune it.
        before = analyser.sweep
        ui.band_box.setCurrentIndex(-1)
        self.assertEqual(analyser.sweep, before)
        ui.band_box.currentIndexChanged.disconnect()
        data.bandselect.tm.clear()
        data.bandstype.tm.clear()
        analyser.__dict__.clear()
        controller.__dict__.clear()
        data.__dict__.clear()


if __name__ == '__main__':
    unittest.main()
