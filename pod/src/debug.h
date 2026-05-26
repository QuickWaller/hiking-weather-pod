#pragma once

#ifdef DEBUG
#  include <Arduino.h>
#  define LOG(fmt, ...)  Serial.printf("[DBG] " fmt "\n", ##__VA_ARGS__)
#  define LOG_WARN(fmt, ...) Serial.printf("[WRN] " fmt "\n", ##__VA_ARGS__)
#  define LOG_ERR(fmt, ...)  Serial.printf("[ERR] " fmt "\n", ##__VA_ARGS__)
#else
#  define LOG(fmt, ...)
#  define LOG_WARN(fmt, ...)
#  define LOG_ERR(fmt, ...)
#endif
