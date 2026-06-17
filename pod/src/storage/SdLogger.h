#pragma once
#include <stdint.h>
#include <stddef.h>

// SD card logger — appends rows to daily UTC-dated CSV files.
//
// Directory layout on the SD card:
//   /raw/YYYY-MM-DD.csv      10-min telemetry (LogFormatter::formatEntry)
//   /inputs/YYYY-MM-DD.csv   Hourly model feature vectors
//   /pred/YYYY-MM-DD.csv     Hourly model predictions
//   /events/YYYY-MM-DD.csv   Diagnostic events
//
// All timestamps are UTC with a trailing Z. The date in the filename is also
// UTC (derived from the Unix timestamp). Missing SD degrades gracefully — all
// append() calls return false and the pod continues without logging.

class SdLogger {
public:
    // Initialise the SD card. Call once from setup().
    // cs = SPI chip-select pin.
    bool begin(uint8_t cs);

    // Append a newline-terminated row to the given subdirectory.
    // Creates the file (with CSV header) if it doesn't exist.
    // unixTime is used to determine the filename (UTC date).
    bool appendRaw   (const char* row, uint32_t unixTime);
    bool appendInputs(const char* row, uint32_t unixTime);
    bool appendPred  (const char* row, uint32_t unixTime);
    bool appendEvent (const char* row, uint32_t unixTime);

    bool isReady() const { return ready_; }

    // Build the path: "/dir/YYYY-MM-DD.csv" from a Unix timestamp.
    // Exposed for testing.
    static void buildPath(char* buf, size_t len,
                          const char* dir, uint32_t unixTime);

    // CSV headers for each log type.
    static const char* rawHeader();
    static const char* inputsHeader(const char* const* names, uint8_t n,
                                    char* buf, size_t len);
    static const char* predHeader(const char* const* names, uint8_t n,
                                  char* buf, size_t len);
    static const char* eventHeader();

private:
    bool ready_ = false;
    bool append(const char* dir, const char* header,
                const char* row, uint32_t unixTime);
};
