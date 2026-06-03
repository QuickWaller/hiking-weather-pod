#pragma once
#include <stdint.h>
#include <stddef.h>

// Severity levels
// W = warning  (discarded on compaction)
// E = error    (kept on compaction)
// C = critical (kept on compaction)

class EventLog {
public:
    void begin();
    void warn(const char* code, const char* detail, uint32_t unixTime);
    void error(const char* code, const char* detail, uint32_t unixTime);
    void critical(const char* code, const char* detail, uint32_t unixTime);

private:
    void write(char severity, const char* code, const char* detail, uint32_t unixTime);
    void compact();

    bool _full = false;

    static constexpr size_t MAX_BYTES  = 100 * 1024;  // 100KB
    static constexpr const char* PATH  = "/events.log";
    static constexpr const char* PTMP  = "/events.tmp";
};
