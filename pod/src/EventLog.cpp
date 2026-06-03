#include "EventLog.h"
#include "debug.h"
#include <LittleFS.h>
#include <Arduino.h>
#include <stdio.h>

void EventLog::begin() {
    if (!LittleFS.begin(true)) {
        LOG_ERR("EventLog: LittleFS mount failed");
    }
}

void EventLog::warn(const char* code, const char* detail, uint32_t t) {
    write('W', code, detail, t);
}

void EventLog::error(const char* code, const char* detail, uint32_t t) {
    write('E', code, detail, t);
}

void EventLog::critical(const char* code, const char* detail, uint32_t t) {
    write('C', code, detail, t);
}

void EventLog::write(char severity, const char* code, const char* detail, uint32_t t) {
    if (_full) return;

    File f = LittleFS.open(PATH, "a");
    if (!f) {
        LOG_ERR("EventLog: open failed");
        return;
    }

    size_t sizeBefore = f.size();
    f.printf("%lu,%c,%s,%s\n", (unsigned long)t, severity, code, detail);
    f.close();

    if (sizeBefore >= MAX_BYTES) {
        compact();
    }
}

void EventLog::compact() {
    LOG("EventLog: compacting — removing W entries");

    File src = LittleFS.open(PATH, "r");
    File tmp = LittleFS.open(PTMP, "w");
    if (!src || !tmp) {
        LOG_ERR("EventLog: compact open failed");
        if (src) src.close();
        if (tmp) tmp.close();
        return;
    }

    char line[192];
    while (src.available()) {
        int len = src.readBytesUntil('\n', line, sizeof(line) - 1);
        if (len <= 0) continue;
        line[len] = '\0';
        // Keep E, C entries — field 2 is the severity char after first comma
        const char* p = strchr(line, ',');
        if (p && (p[1] == 'E' || p[1] == 'C')) {
            tmp.printf("%s\n", line);
        }
    }

    // Mark compaction in the retained log
    tmp.printf("0,C,LOG_COMPACT,W entries purged\n");

    src.close();
    tmp.close();

    LittleFS.remove(PATH);
    LittleFS.rename(PTMP, PATH);
    LOG("EventLog: compact done");

    // If still over limit after dropping all W entries, seal the log
    File check = LittleFS.open(PATH, "r");
    size_t sizeAfter = check ? check.size() : MAX_BYTES;
    if (check) check.close();

    if (sizeAfter >= MAX_BYTES) {
        _full = true;
        File f = LittleFS.open(PATH, "a");
        if (f) {
            f.printf("0,C,LOG_FULL,no further entries will be written\n");
            f.close();
        }
        LOG_WARN("EventLog: full — logging stopped");
    }
}
