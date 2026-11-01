#ifndef NH22_PROTOCOL_H
#define NH22_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
#define NH22_N 22U
#define NH22_MASK 0x003fffffU
#define NH22_MOTION_BYTES 62U
#define NH22_CONFIG_BYTES 20U
#define NH22_QUERY_BYTES 12U
#define NH22_STOP_BYTES 10U
#define NH22_TELEMETRY_BYTES 130U
typedef enum { NH22_INVALID=0,NH22_QUERY,NH22_MOTION,NH22_CONFIG,NH22_STOP } nh22_kind;
uint16_t nh22_u16(const uint8_t *p);
uint32_t nh22_u32(const uint8_t *p);
uint16_t nh22_crc(const uint8_t *p,size_t n);
void nh22_put16(uint8_t *p,uint16_t v);
void nh22_put32(uint8_t *p,uint32_t v);
nh22_kind nh22_validate(const uint8_t *p,size_t n);
int nh22_newer(uint32_t a,uint32_t b);
#endif
