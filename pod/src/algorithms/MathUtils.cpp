#include "MathUtils.h"
#include "config.h"
#include <math.h>

static constexpr float DEG2RAD = 3.14159265358979f / 180.0f;
static constexpr float EARTH_R_M = 6371000.0f;

float MathUtils::altitudeAdjustedPressure(float rawHpa, float altitudeM) {
    // Hypsometric formula: P0 = P * exp(alt / (29.3 * T_virtual))
    // Simplified with standard temperature lapse rate, T_virtual ≈ 288K at sea level
    return rawHpa * expf(altitudeM / 8434.0f);
}

float MathUtils::dewPointC(float tempC, float humidity) {
    // Magnus formula. Clamp humidity to a sane range first: humidity == 0 (a failed
    // AHT10 defaults to 0) would feed logf(0) → -inf → NaN dew point, silently
    // disabling fog detection downstream. >100 (bad reading) is clamped too.
    if (humidity < 1.0f)   humidity = 1.0f;
    if (humidity > 100.0f) humidity = 100.0f;
    const float a = 17.27f;
    const float b = 237.7f;
    float gamma = (a * tempC / (b + tempC)) + logf(humidity / 100.0f);
    return (b * gamma) / (a - gamma);
}

float MathUtils::haversineM(float lat1, float lon1, float lat2, float lon2) {
    float dLat = (lat2 - lat1) * DEG2RAD;
    float dLon = (lon2 - lon1) * DEG2RAD;
    float a = sinf(dLat / 2) * sinf(dLat / 2)
            + cosf(lat1 * DEG2RAD) * cosf(lat2 * DEG2RAD)
            * sinf(dLon / 2) * sinf(dLon / 2);
    return EARTH_R_M * 2.0f * atan2f(sqrtf(a), sqrtf(1.0f - a));
}

float MathUtils::speedKph(float distM, uint32_t dtSeconds) {
    if (dtSeconds == 0) return 0.0f;
    return (distM / dtSeconds) * 3.6f;
}

uint32_t MathUtils::unixFromDateTime(uint16_t year, uint8_t month, uint8_t day,
                                     uint8_t hour, uint8_t minute, uint8_t second) {
    // Guard against garbage RTC values — month outside 1..12 would index doy[] out
    // of bounds. Return 0 (the "no valid time" sentinel) rather than read OOB.
    if (month < 1 || month > 12) return 0;
    static const uint16_t doy[] = {0,31,59,90,120,151,181,212,243,273,304,334};
    uint32_t y     = year - 1970;
    uint32_t leaps = (year-1)/4 - (year-1)/100 + (year-1)/400
                   - (1969/4   - 1969/100   + 1969/400);
    uint32_t days  = y * 365 + leaps + doy[month - 1] + (day - 1);
    bool isLeap    = (year % 4 == 0) && (year % 100 != 0 || year % 400 == 0);
    if (isLeap && month > 2) days++;
    return days * 86400UL + hour * 3600UL + minute * 60UL + second;
}

void MathUtils::dateTimeFromUnix(uint32_t unix, uint16_t& year, uint8_t& month,
                                  uint8_t& day, uint8_t& hour, uint8_t& minute,
                                  uint8_t& second) {
    second = unix % 60; unix /= 60;
    minute = unix % 60; unix /= 60;
    hour   = unix % 24; unix /= 24;

    // Howard Hinnant's civil-from-days algorithm
    uint32_t z   = unix + 719468;
    uint32_t era = z / 146097;
    uint32_t doe = z - era * 146097;
    uint32_t yoe = (doe - doe/1460 + doe/36524 - doe/146096) / 365;
    uint32_t y   = yoe + era * 400;
    uint32_t doy = doe - (365*yoe + yoe/4 - yoe/100);
    uint32_t mp  = (5*doy + 2) / 153;
    uint32_t d   = doy - (153*mp + 2)/5 + 1;
    uint32_t m   = mp < 10 ? mp + 3 : mp - 9;
    if (m <= 2) y++;

    year   = (uint16_t)y;
    month  = (uint8_t)m;
    day    = (uint8_t)d;
}

float MathUtils::median(const float* values, int n) {
    if (n <= 0) return 0.0f;
    // GPS buffer holds at most 15 entries; cap the local copy accordingly.
    const int MAXN = 15;
    if (n > MAXN) n = MAXN;
    float tmp[MAXN];
    for (int i = 0; i < n; i++) tmp[i] = values[i];

    // Insertion sort — n is tiny (<=15), so this is cheaper than anything fancier.
    for (int i = 1; i < n; i++) {
        float key = tmp[i];
        int j = i - 1;
        while (j >= 0 && tmp[j] > key) { tmp[j + 1] = tmp[j]; j--; }
        tmp[j + 1] = key;
    }

    if (n & 1) return tmp[n / 2];
    return (tmp[n / 2 - 1] + tmp[n / 2]) * 0.5f;
}

float MathUtils::linearRegressionSlope(const float* values, int n) {
    if (n < 2) return 0.0f;
    float sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    for (int i = 0; i < n; i++) {
        sumX  += i;
        sumY  += values[i];
        sumXY += i * values[i];
        sumX2 += i * i;
    }
    float denom = n * sumX2 - sumX * sumX;
    if (fabsf(denom) < 1e-9f) return 0.0f;
    return (n * sumXY - sumX * sumY) / denom;
}

float MathUtils::linearRegressionSlopeXY(const float* xs, const float* ys, int n) {
    if (n < 2) return 0.0f;
    float sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    for (int i = 0; i < n; i++) {
        sumX  += xs[i];
        sumY  += ys[i];
        sumXY += xs[i] * ys[i];
        sumX2 += xs[i] * xs[i];
    }
    float denom = n * sumX2 - sumX * sumX;
    if (fabsf(denom) < 1e-9f) return 0.0f;  // all x equal — slope undefined
    return (n * sumXY - sumX * sumY) / denom;
}

// ── NZ timezone / DST ─────────────────────────────────────────────────────────

// Day of week for a date: 0=Sunday … 6=Saturday. Epoch day 0 (1970-01-01) was a
// Thursday, so (daysSinceEpoch + 4) mod 7 maps Sunday→0.
static uint8_t dayOfWeek(uint16_t y, uint8_t m, uint8_t d) {
    uint32_t u = MathUtils::unixFromDateTime(y, m, d, 0, 0, 0);
    return (uint8_t)(((u / 86400UL) + 4) % 7);
}

int MathUtils::nzUtcOffsetMinutes(uint32_t utcUnix) {
    uint16_t year; uint8_t mo, da, hh, mm, ss;
    dateTimeFromUnix(utcUnix, year, mo, da, hh, mm, ss);
    (void)mo; (void)da; (void)hh; (void)mm; (void)ss;  // only the year is needed

    // DST begins last Sunday of September at 02:00 NZST. Just before the switch the
    // clock is on NZST, so that wall time maps to UTC by subtracting the STD offset.
    uint8_t septDay = 30;
    while (dayOfWeek(year, 9, septDay) != 0) septDay--;
    uint32_t dstStartUtc = unixFromDateTime(year, 9, septDay, 2, 0, 0)
                         - (uint32_t)NZ_STD_OFFSET_MIN * 60;

    // DST ends first Sunday of April at 03:00 NZDT — that wall time is on NZDT, so
    // subtract the DST offset to get UTC.
    uint8_t aprDay = 1;
    while (dayOfWeek(year, 4, aprDay) != 0) aprDay++;
    uint32_t dstEndUtc = unixFromDateTime(year, 4, aprDay, 3, 0, 0)
                       - (uint32_t)NZ_DST_OFFSET_MIN * 60;

    // Austral summer wraps the new year: each calendar year is in DST from its own
    // Sep start onward AND up to its own Apr end. Between those it's standard time.
    bool dst = (utcUnix >= dstStartUtc) || (utcUnix < dstEndUtc);
    return dst ? NZ_DST_OFFSET_MIN : NZ_STD_OFFSET_MIN;
}

// ── Sunrise / sunset ──────────────────────────────────────────────────────────

int MathUtils::dayOfYear(uint16_t year, uint8_t month, uint8_t day) {
    static const int cum[12] = { 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334 };
    int m = (month >= 1 && month <= 12) ? month : 1;
    int doy = cum[m - 1] + day;
    bool leap = (year % 4 == 0 && year % 100 != 0) || (year % 400 == 0);
    if (leap && m > 2) doy += 1;
    return doy;
}

// USNO/Almanac sunrise-sunset algorithm. Returns the event time in UTC hours
// [0,24); sets valid=false at latitudes where the sun does not rise/set that day.
static float sunEventUtcHours(float lat, float lon, int doy, bool rising,
                              float zenithDeg, bool& valid) {
    const float D2R = 3.14159265358979f / 180.0f;
    const float R2D = 180.0f / 3.14159265358979f;

    float lngHour = lon / 15.0f;
    float t = rising ? (doy + (6.0f  - lngHour) / 24.0f)
                     : (doy + (18.0f - lngHour) / 24.0f);

    float M = 0.9856f * t - 3.289f;                                  // mean anomaly (deg)
    float L = M + 1.916f * sinf(M * D2R) + 0.020f * sinf(2.0f * M * D2R) + 282.634f;
    L = fmodf(L, 360.0f); if (L < 0) L += 360.0f;                    // true longitude

    float RA = R2D * atanf(0.91764f * tanf(L * D2R));
    RA = fmodf(RA, 360.0f); if (RA < 0) RA += 360.0f;
    float Lq  = floorf(L  / 90.0f) * 90.0f;                          // RA → same quadrant as L
    float RAq = floorf(RA / 90.0f) * 90.0f;
    RA = (RA + (Lq - RAq)) / 15.0f;                                  // → hours

    float sinDec = 0.39782f * sinf(L * D2R);
    float cosDec = cosf(asinf(sinDec));

    float cosH = (cosf(zenithDeg * D2R) - sinDec * sinf(lat * D2R))
               / (cosDec * cosf(lat * D2R));
    if (cosH > 1.0f || cosH < -1.0f) { valid = false; return 0.0f; } // no rise/set that day

    float H = rising ? (360.0f - R2D * acosf(cosH)) : (R2D * acosf(cosH));
    H /= 15.0f;

    float localT = H + RA - 0.06571f * t - 6.622f;                   // local mean time (hrs)
    float UT = localT - lngHour;
    UT = fmodf(UT, 24.0f); if (UT < 0) UT += 24.0f;
    valid = true;
    return UT;
}

float MathUtils::tiltCompensatedHeading(
    int16_t mx, int16_t my, int16_t mz,
    float ax, float ay, float az,
    float offsetX, float offsetY, float offsetZ)
{
    float cx = (float)mx - offsetX;
    float cy = (float)my - offsetY;
    float cz = (float)mz - offsetZ;

    float roll  = atan2f(ay, az);
    float pitch = atan2f(-ax, sqrtf(ay * ay + az * az));

    float cosPitch = cosf(pitch), sinPitch = sinf(pitch);
    float cosRoll  = cosf(roll),  sinRoll  = sinf(roll);

    // Project magnetometer onto horizontal plane (Honeywell AN-203). Heading is
    // atan2(By, Bx) — matching the flat read() formula atan2(y, x) when level, so
    // the tilt-compensated and 2D paths share one convention (0 = N, clockwise).
    float Bx = cx * cosPitch + cy * sinRoll * sinPitch - cz * cosRoll * sinPitch;
    float By = cy * cosRoll  - cz * sinRoll;

    float heading = atan2f(By, Bx) * (180.0f / 3.14159265358979f);
    if (heading < 0.0f) heading += 360.0f;
    return heading;
}

void MathUtils::sunriseSunsetMinutes(float lat, float lon, int doy, int utcOffsetMin,
                                     int16_t& sunriseMin, int16_t& sunsetMin) {
    bool rValid, sValid;
    float riseUT = sunEventUtcHours(lat, lon, doy, true,  SUN_ZENITH_DEG, rValid);
    float setUT  = sunEventUtcHours(lat, lon, doy, false, SUN_ZENITH_DEG, sValid);

    if (rValid) {
        int m = (int)lroundf(riseUT * 60.0f) + utcOffsetMin;
        sunriseMin = (int16_t)(((m % 1440) + 1440) % 1440);          // wrap into [0,1439]
    } else sunriseMin = -1;

    if (sValid) {
        int m = (int)lroundf(setUT * 60.0f) + utcOffsetMin;
        sunsetMin = (int16_t)(((m % 1440) + 1440) % 1440);
    } else sunsetMin = -1;
}
