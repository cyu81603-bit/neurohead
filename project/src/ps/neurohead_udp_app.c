/* NH22 development firmware: new v3 protocol only. Never use with v1 RTL.
 * PS/lwIP startup is reused from the existing NeuroHead baseline.
 * PWM telemetry is a setting, not measured position.
 */
#include "xil_io.h"
#include "xparameters.h"
#include "lwip/init.h"
#include "lwip/udp.h"
#include "lwip/ip_addr.h"
#include "lwip/netif.h"
#include "lwip/priv/tcp_priv.h"
#include "netif/xadapter.h"
#include "xil_printf.h"
#include "xstatus.h"
#include "nh22_protocol.h"
#include <string.h>
#ifndef XPAR_NEUROHEAD_SERVO_0_BASEADDR
#error "Missing servo AXI peripheral"
#endif
#if XPAR_NEUROHEAD_SERVO_0_BASEADDR != 0x40000000U
#error "Unexpected servo base address"
#endif
#define BASE XPAR_NEUROHEAD_SERVO_0_BASEADDR
#define RD(off) Xil_In32(BASE+(off))
#define WR(off,value) Xil_Out32(BASE+(off),(value))
void neurohead_platform_attach_netif(struct netif *);
int neurohead_platform_init(void);
void neurohead_platform_enable_interrupts(void);
extern volatile int TcpFastTmrFlag,TcpSlowTmrFlag;
static unsigned char mac[6]={2,0x4e,0x48,0x20,0x26,0x21};
static struct netif server_netif;
static uint32_t last_sequence,accepted,invalid,stale;
static uint8_t have_sequence;
static void telemetry(struct udp_pcb *pcb,const ip_addr_t *addr,u16_t port,uint32_t timestamp,uint8_t is_query){
 uint8_t out[NH22_TELEMETRY_BYTES];struct pbuf *reply;unsigned i;
 memset(out,0,sizeof out);out[0]='N';out[1]='T';out[2]=3;out[3]=(is_query?2:0)|(have_sequence?4:0);
 nh22_put32(out+4,last_sequence);nh22_put32(out+8,RD(0x0c));
 nh22_put32(out+12,RD(0x14));nh22_put32(out+16,RD(0x18));
 nh22_put32(out+20,accepted);nh22_put32(out+24,invalid);nh22_put32(out+28,stale);
 nh22_put32(out+32,RD(0x28));nh22_put32(out+36,timestamp);
 /* Sequential reads, not an atomic snapshot of moving channels. */
 for(i=0;i<NH22_N;i++){nh22_put16(out+40+2*i,(uint16_t)RD(0x100+4*i));nh22_put16(out+84+2*i,(uint16_t)RD(0x200+4*i));}
 nh22_put16(out+128,nh22_crc(out,128));
 reply=pbuf_alloc(PBUF_TRANSPORT,sizeof out,PBUF_RAM);
 if(reply){memcpy(reply->payload,out,sizeof out);(void)udp_sendto(pcb,reply,addr,port);pbuf_free(reply);}
}
static int apply_config(const uint8_t *p){
 unsigned ch=p[8];uint32_t bit=1U<<ch,hold=RD(0x1c),configured=RD(0x18);
 uint32_t rejected=RD(0x24);
 if(RD(0x0c)&7U)return 0;
 WR(0x300+4*ch,nh22_u16(p+10));WR(0x400+4*ch,nh22_u16(p+12));
 WR(0x500+4*ch,nh22_u16(p+14));WR(0x600+4*ch,nh22_u16(p+16));
 WR(0x1c,p[9]?(hold|bit):(hold&~bit));
 WR(0x18,configured|bit);
 return RD(0x24)==rejected && RD(0x300+4*ch)==nh22_u16(p+10)
  && RD(0x400+4*ch)==nh22_u16(p+12) && RD(0x500+4*ch)==nh22_u16(p+14)
  && RD(0x600+4*ch)==nh22_u16(p+16) && (RD(0x18)&bit);
}
static int apply_motion(const uint8_t *p){
 unsigned i;uint32_t mask=nh22_u32(p+8),count=RD(0x20);
 if(RD(0x0c)&2U || (mask&~RD(0x18)))return 0;
 for(i=0;i<NH22_N;i++)if(mask&(1U<<i)){
  uint32_t v=nh22_u16(p+12+2*i);
  if(v<RD(0x300+4*i) || v>RD(0x400+4*i))return 0;
 }
 for(i=0;i<NH22_N;i++)if(mask&(1U<<i))WR(0x100+4*i,nh22_u16(p+12+2*i));
 WR(0x10,mask);WR(0x08,1);
 return RD(0x20)==count+1 && !(RD(0x0c)&2U);
}
static void receive(void *arg,struct udp_pcb *pcb,struct pbuf *buf,const ip_addr_t *addr,u16_t port){
 uint8_t p[NH22_MOTION_BYTES];size_t n;nh22_kind kind;uint32_t seq,timestamp=0;int ok=0;
 (void)arg;if(!buf)return;n=buf->tot_len;
 if(n>sizeof p){invalid++;pbuf_free(buf);return;}
 pbuf_copy_partial(buf,p,(u16_t)n,0);pbuf_free(buf);
 kind=nh22_validate(p,n);
 if(kind==NH22_INVALID){invalid++;return;}
 if(kind==NH22_QUERY){telemetry(pcb,addr,port,nh22_u32(p+6),1);return;}
 if(kind==NH22_STOP){
  /* Emergency disarm is idempotent and deliberately not blocked by sequence. */
  WR(0x08,2);telemetry(pcb,addr,port,0,0);return;
 }
 seq=nh22_u32(p+4);
 if(have_sequence && !nh22_newer(seq,last_sequence)){stale++;return;}
 if(kind==NH22_CONFIG)ok=apply_config(p);
 else if(kind==NH22_MOTION){ok=apply_motion(p);timestamp=nh22_u32(p+56);}
 if(ok){last_sequence=seq;have_sequence=1;accepted++;}
 else invalid++;
 telemetry(pcb,addr,port,timestamp,0);
}
int main(void){
 struct udp_pcb *pcb;ip_addr_t ip,mask,gateway;
 if(neurohead_platform_init()!=XST_SUCCESS)return -1;
 if(RD(0)!=0x3232484eU || RD(4)!=0x00030016U){
  xil_printf("NH22 WRONG HARDWARE: refusing application startup\r\n");return -1;
 }
 IP4_ADDR(&ip,192,168,10,20);IP4_ADDR(&mask,255,255,255,0);IP4_ADDR(&gateway,0,0,0,0);
 lwip_init();
 if(!xemac_add(&server_netif,&ip,&mask,&gateway,mac,XPAR_XEMACPS_0_BASEADDR))return -1;
 netif_set_default(&server_netif);netif_set_up(&server_netif);
 neurohead_platform_attach_netif(&server_netif);
 pcb=udp_new();if(!pcb || udp_bind(pcb,IP_ADDR_ANY,5005)!=ERR_OK)return -1;
 udp_recv(pcb,receive,0);neurohead_platform_enable_interrupts();
 xil_printf("NH22 v3 ready 192.168.10.20:5005; all outputs initially disabled\r\n");
 for(;;){
  if(TcpFastTmrFlag){tcp_fasttmr();TcpFastTmrFlag=0;}
  if(TcpSlowTmrFlag){tcp_slowtmr();TcpSlowTmrFlag=0;}
  xemacif_input(&server_netif);
 }
}
