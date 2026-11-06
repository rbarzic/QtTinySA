"""Built-in 2.4 GHz wireless channel presets (frequencies in Hz)."""

# Bluetooth Core v6.2, Vol 6, Part B, 1.4.1, Table 1.3.
# Channel numbers are Link Layer indices, not Direct Test Mode RF indices.
BLE_CHANNELS = tuple(
    (channel, (2404 + 2 * channel if channel <= 10 else 2406 + 2 * channel) * 1_000_000)
    for channel in range(37)
) + ((37, 2_402_000_000), (38, 2_426_000_000), (39, 2_480_000_000))

# IEEE 802.15.4-2020, 10.1.3.3 (channel page zero).
ZIGBEE_CHANNELS = tuple(
    (channel, (2405 + 5 * (channel - 11)) * 1_000_000)
    for channel in range(11, 27)
)

# Display spans, not occupied bandwidths: leave context around each channel.
CHANNEL_SPANS_MHZ = {'BLE 2G': 4, 'Zigbee 2G': 5}


def ensure_wireless_presets(db):
    """Add missing defaults without changing existing presets or requiring a DB reset."""
    from PySide6.QtSql import QSqlQuery

    def execute(sql, values=()):
        query = QSqlQuery(db)
        query.prepare(sql)
        for value in values:
            query.addBindValue(value)
        if not query.exec():
            raise RuntimeError(f"Cannot add wireless presets: {query.lastError().text()}")
        return query

    if not db.transaction():
        raise RuntimeError(f"Cannot start wireless preset transaction: {db.lastError().text()}")
    try:
        for preset, channels in (('BLE 2G', BLE_CHANNELS), ('Zigbee 2G', ZIGBEE_CHANNELS)):
            execute('INSERT OR IGNORE INTO freqtype (preset, LO) VALUES (?, 0)', (preset,))
            query = execute('SELECT ID FROM freqtype WHERE preset = ?', (preset,))
            if not query.next():
                raise RuntimeError(f"Missing wireless preset type: {preset}")
            type_id = query.value(0)
            query.finish()
            entries = [(preset, 2_400_000_000, 2_483_500_000)]
            entries.extend(
                (f'ch{channel} (adv)' if preset == 'BLE 2G' and channel >= 37 else f'ch{channel}',
                 frequency, 0)
                for channel, frequency in channels
            )
            for name, start, stop in entries:
                # Check type as well as name: other bands also contain ch11, etc.
                execute(
                    'INSERT INTO frequencies (name, type, startF, stopF) '
                    'SELECT ?, ?, ?, ? WHERE NOT EXISTS '
                    '(SELECT 1 FROM frequencies WHERE type = ? AND name = ?)',
                    (name, type_id, start, stop, type_id, name),
                )
        if not db.commit():
            raise RuntimeError(f"Cannot commit wireless presets: {db.lastError().text()}")
    except Exception:
        db.rollback()
        raise
