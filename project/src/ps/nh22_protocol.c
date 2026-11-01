#include "nh22_protocol.h"
uint16_t nh22_u16(const uint8_t *p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
uint32_t nh22_u32(const uint8_t *p){return nh22_u16(p)|((uint32_t)nh22_u16(p+2)<<16);}
void nh22_put16(uint8_t *p,uint16_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);}
void nh22_put32(uint8_t *p,uint32_t v){nh22_put16(p,(uint16_t)v);nh22_put16(p+2,(uint16_t)(v>>16));}
uint16_t nh22_crc(const uint8_t *p,size_t n){
 uint16_t c=0xffffU;unsigned b;
 while(n--){c^=(uint16_t)*p++<<8;for(b=0;b<8;b++)c=(c&0x8000U)?(uint16_t)((c<<1)^0x1021U):(uint16_t)(c<<1);}
 return c;
}
int nh22_newer(uint32_t a,uint32_t b){uint32_t d=a-b;return d!=0 && d<0x80000000U;}
nh22_kind nh22_validate(const uint8_t *p,size_t n){
 unsigned i;uint32_t mask;
 if(!p || n<10 || p[0]!='N' || p[2]!=3 || p[3]!=0 ||
    nh22_u16(p+n-2)!=nh22_crc(p,n-2))return NH22_INVALID;
 if(p[1]=='Q' && n==NH22_QUERY_BYTES)return NH22_QUERY;
 if(p[1]=='S' && n==NH22_STOP_BYTES)return NH22_STOP;
 if(p[1]=='H' && n==NH22_MOTION_BYTES){
  mask=nh22_u32(p+8);
  if(!mask || (mask&~NH22_MASK))return NH22_INVALID;
  for(i=0;i<NH22_N;i++)
   if((mask&(1U<<i)) && (nh22_u16(p+12+2*i)<600 || nh22_u16(p+12+2*i)>2400))return NH22_INVALID;
  return NH22_MOTION;
 }
 if(p[1]=='C' && n==NH22_CONFIG_BYTES){
  uint16_t lo=nh22_u16(p+10),hi=nh22_u16(p+12),mid=nh22_u16(p+14),step=nh22_u16(p+16);
  if(p[8]>=NH22_N || p[9]>1 || lo<600 || hi>2400 || lo>mid || mid>hi || step<1 || step>100)return NH22_INVALID;
  return NH22_CONFIG;
 }
 return NH22_INVALID;
}
