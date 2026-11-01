#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "nh22_protocol.h"
static void checksum(uint8_t *p,size_t n){nh22_put16(p+n-2,nh22_crc(p,n-2));}
int main(int argc,char **argv){
 uint8_t p[62]={0};unsigned i;
 if(argc==2){
  FILE *f=fopen(argv[1],"rb");size_t n;assert(f);n=fread(p,1,sizeof p,f);fclose(f);
  printf("%d\n",(int)nh22_validate(p,n));return 0;
 }
 assert(nh22_crc((const uint8_t*)"123456789",9)==0x29b1);
 assert(nh22_newer(0,0xffffffffU));assert(!nh22_newer(0,0));assert(!nh22_newer(0x80000000U,0));
 p[0]='N';p[1]='H';p[2]=3;nh22_put32(p+8,NH22_MASK);
 for(i=0;i<22;i++)nh22_put16(p+12+2*i,1500);
 checksum(p,62);assert(nh22_validate(p,62)==NH22_MOTION);
 p[10]^=1;assert(nh22_validate(p,62)==NH22_INVALID);p[10]^=1;
 nh22_put32(p+8,1U<<22);checksum(p,62);assert(nh22_validate(p,62)==NH22_INVALID);
 nh22_put32(p+8,1U<<21);nh22_put16(p+54,2401);checksum(p,62);assert(nh22_validate(p,62)==NH22_INVALID);
 nh22_put16(p+54,600);checksum(p,62);assert(nh22_validate(p,62)==NH22_MOTION);
 assert(nh22_validate(p,16)==NH22_INVALID);assert(nh22_validate(NULL,0)==NH22_INVALID);
 puts("NH22_C_PROTOCOL_PASS");return 0;
}
