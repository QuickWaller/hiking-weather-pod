#include "GpsReader.h"
#include "config.h"
#include "debug.h"
#include "algorithms/MathUtils.h"

static constexpr int GPS_BAUD = 9600;

static HardwareSerial gpsSerial(2);

void GpsReader::begin() {
    gpsSerial.setRxBufferSize(512);
    gpsSerial.begin(GPS_BAUD, SERIAL_8N1, PIN_GPS_RX, PIN_GPS_TX);
    _startMs = millis();
    LOG("GPS UART2 started — RX=GPIO%d TX=GPIO%d", PIN_GPS_RX, PIN_GPS_TX);
}

void GpsReader::poll() {
    while (gpsSerial.available()) {
        char c = gpsSerial.read();

        if (c == '\n' || _len >= 127) {
            _buf[_len] = '\0';

            // Raw NMEA for first 30s — confirms module is alive
            if (millis() - _startMs < 30000)
                LOG("NMEA: %s", _buf);

            parseGGA(_buf);
            parseRMC(_buf);
            parseGSV(_buf);
            _len = 0;
        } else if (c != '\r') {
            _buf[_len++] = c;
        }
    }

    // Status line every 10s while waiting for fix
    if (!_gotFirstFix && millis() - _lastStatusMs >= 10000) {
        logStatus();
        _lastStatusMs = millis();
    }
}

void GpsReader::parseGSV(const char* line) {
    // $GPGSV/$GAGSV/$GBGSV/$GQGSV — field 3 is total sats in view for that constellation
    // Accumulate across all constellations; reset each full cycle via $GPGSV msg 1/N
    if (strlen(line) < 6 || line[0] != '$') return;
    // Accept any xGSV sentence
    if (strncmp(line + 3, "GSV", 3) != 0) return;

    char buf[128];
    strncpy(buf, line, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char* tok = strtok(buf, ",");
    int field = 0, msgNum = 0, totalSats = 0;
    while (tok) {
        if (field == 1) msgNum    = atoi(tok);
        if (field == 3) totalSats = atoi(tok);
        tok = strtok(nullptr, ",");
        field++;
    }
    // Only count on first message of each constellation's sequence to avoid double-counting
    if (msgNum == 1) _satsInView += totalSats;
}

void GpsReader::logStatus() {
    uint32_t elapsed = (millis() - _startMs) / 1000;
    LOG("GPS waiting — sats_in_view=%d  elapsed=%lus", _satsInView, elapsed);
    _satsInView = 0;  // reset so next 10s window accumulates fresh
}

bool GpsReader::parseRMC(const char* line) {
    if (strncmp(line, "$GNRMC", 6) != 0 && strncmp(line, "$GPRMC", 6) != 0)
        return false;

    char buf[128];
    strncpy(buf, line, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char* tok = strtok(buf, ",");
    int field = 0;
    char status = 'V';
    uint32_t rawTime = 0;  // HHMMSS
    uint32_t rawDate = 0;  // DDMMYY

    while (tok) {
        switch (field) {
            case 1: rawTime = (uint32_t)atof(tok); break;
            case 2: status  = tok[0];               break;
            case 9: rawDate = (uint32_t)atol(tok);  break;
        }
        tok = strtok(nullptr, ",");
        field++;
    }

    if (status != 'A' || rawDate == 0) return false;

    uint8_t  hour  = rawTime / 10000;
    uint8_t  min   = (rawTime / 100) % 100;
    uint8_t  sec   = rawTime % 100;
    uint8_t  day   = rawDate / 10000;
    uint8_t  month = (rawDate / 100) % 100;
    uint16_t year  = 2000 + (rawDate % 100);

    _fix.unixTime = MathUtils::unixFromDateTime(year, month, day, hour, min, sec);
    return true;
}

bool GpsReader::parseGGA(const char* line) {
    if (strncmp(line, "$GNGGA", 6) != 0 && strncmp(line, "$GPGGA", 6) != 0)
        return false;

    char buf[128];
    strncpy(buf, line, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char* tok   = strtok(buf, ",");
    int   field = 0;
    float rawLat = 0, rawLon = 0, altM = 0;
    char  latDir = 'N', lonDir = 'E';
    int   quality = 0, sats = 0;

    while (tok) {
        switch (field) {
            case 2: rawLat  = atof(tok); break;
            case 3: latDir  = tok[0];    break;
            case 4: rawLon  = atof(tok); break;
            case 5: lonDir  = tok[0];    break;
            case 6: quality = atoi(tok); break;
            case 7: sats    = atoi(tok); break;
            case 9: altM    = atof(tok); break;
        }
        tok = strtok(nullptr, ",");
        field++;
    }

    if (quality == 0 || rawLat == 0.0f) return false;

    // DDMM.MMMM → decimal degrees
    int latDeg = (int)(rawLat / 100);
    float lat  = latDeg + (rawLat - latDeg * 100) / 60.0f;
    if (latDir == 'S') lat = -lat;

    int lonDeg = (int)(rawLon / 100);
    float lon  = lonDeg + (rawLon - lonDeg * 100) / 60.0f;
    if (lonDir == 'W') lon = -lon;

    if (!_gotFirstFix) {
        _gotFirstFix = true;
        uint32_t ttff = millis() - _startMs;
        LOG(">>> FIRST FIX in %lu ms (%lu s)", ttff, ttff / 1000);
    }

    _fix = { lat, lon, altM, sats, quality, millis(), true };
    LOG("GPS  lat=%.6f lon=%.6f alt=%.1fm sats=%d q=%d", lat, lon, altM, sats, quality);
    return true;
}
