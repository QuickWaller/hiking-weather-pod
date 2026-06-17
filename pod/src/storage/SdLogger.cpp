#include "SdLogger.h"
#include "algorithms/MathUtils.h"
#include <string.h>
#include <stdio.h>

// ── Path construction (platform-independent) ───────────────────────────────────

void SdLogger::buildPath(char* buf, size_t len, const char* dir, uint32_t unixTime) {
    // Decompose Unix timestamp into UTC Y/M/D
    uint16_t year; uint8_t month, day, hour, minute, second;
    MathUtils::dateTimeFromUnix(unixTime, year, month, day, hour, minute, second);
    snprintf(buf, len, "/%s/%04u-%02u-%02u.csv", dir, year, month, day);
}

// ── CSV headers ───────────────────────────────────────────────────────────────

const char* SdLogger::rawHeader() {
    return "timestamp,lat,lon,alt,temp,humidity,pressure_raw,pressure_adj,"
           "battery,storm_conf,rain_conf,storm_active,rain_active,"
           "pressure_rate,activity,state,modifier,banner,gps_ms,free_heap";
}

const char* SdLogger::inputsHeader(const char* const* names, uint8_t n,
                                   char* buf, size_t len) {
    size_t pos = 0;
    pos += (size_t)snprintf(buf + pos, len - pos, "timestamp");
    for (uint8_t i = 0; i < n && pos < len - 2; i++)
        pos += (size_t)snprintf(buf + pos, len - pos, ",%s", names[i]);
    return buf;
}

const char* SdLogger::predHeader(const char* const* names, uint8_t n,
                                 char* buf, size_t len) {
    return inputsHeader(names, n, buf, len);  // same structure
}

const char* SdLogger::eventHeader() {
    return "timestamp,level,code,detail";
}

// ── Low-level append ──────────────────────────────────────────────────────────

#ifndef NATIVE_TEST

#include <SD.h>

bool SdLogger::begin(uint8_t cs) {
    ready_ = SD.begin(cs);
    return ready_;
}

bool SdLogger::append(const char* dir, const char* header,
                      const char* row, uint32_t unixTime) {
    if (!ready_) return false;
    char path[40];
    buildPath(path, sizeof(path), dir, unixTime);
    bool newFile = !SD.exists(path);
    File f = SD.open(path, FILE_WRITE);
    if (!f) return false;
    if (newFile && header) { f.println(header); }
    f.println(row);
    f.close();
    return true;
}

#else  // native stub

bool SdLogger::begin(uint8_t /*cs*/) { ready_ = false; return false; }

bool SdLogger::append(const char* /*dir*/, const char* /*header*/,
                      const char* /*row*/, uint32_t /*unixTime*/) { return false; }

#endif

bool SdLogger::appendRaw   (const char* row, uint32_t t) { return append("raw",    rawHeader(),   row, t); }
bool SdLogger::appendInputs(const char* row, uint32_t t) { return append("inputs", nullptr,       row, t); }
bool SdLogger::appendPred  (const char* row, uint32_t t) { return append("pred",   nullptr,       row, t); }
bool SdLogger::appendEvent (const char* row, uint32_t t) { return append("events", eventHeader(), row, t); }
