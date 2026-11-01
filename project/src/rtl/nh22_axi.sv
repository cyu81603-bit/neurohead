// 22-channel PWM development image. Reset is disarmed. No joint feedback.
`timescale 1ns/1ps
module nh22_axi #(
 parameter integer N=22, CLK_HZ=50000000, FRAME_US=20000, WATCHDOG_MS=300,
 parameter integer C_S_AXI_DATA_WIDTH=32, C_S_AXI_ADDR_WIDTH=12
)(
 output reg [N-1:0] pwm,
 (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 S_AXI_CLK CLK" *)
 (* X_INTERFACE_PARAMETER="XIL_INTERFACENAME S_AXI_CLK, ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET s_axi_aresetn, FREQ_HZ 50000000" *)
 input wire s_axi_aclk,
 (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 S_AXI_RST RST" *)
 (* X_INTERFACE_PARAMETER="XIL_INTERFACENAME S_AXI_RST, POLARITY ACTIVE_LOW" *)
 input wire s_axi_aresetn,
 input wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_awaddr, input wire [2:0] s_axi_awprot,
 input wire s_axi_awvalid, output wire s_axi_awready,
 input wire [31:0] s_axi_wdata, input wire [3:0] s_axi_wstrb,
 input wire s_axi_wvalid, output wire s_axi_wready,
 output reg [1:0] s_axi_bresp, output reg s_axi_bvalid, input wire s_axi_bready,
 input wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_araddr, input wire [2:0] s_axi_arprot,
 input wire s_axi_arvalid, output wire s_axi_arready,
 output reg [31:0] s_axi_rdata, output reg [1:0] s_axi_rresp,
 output reg s_axi_rvalid, input wire s_axi_rready
);
 localparam integer CPU=CLK_HZ/1000000, FC=CPU*FRAME_US, WC=(CLK_HZ/1000)*WATCHDOG_MS;
 localparam [31:0] MASK=(32'hffffffff >> (32-N));
 reg [$clog2(FC)-1:0] tick;
 localparam integer SUB_W=(CPU>1)?$clog2(CPU):1;
 reg [SUB_W-1:0] cycle_in_us;
 reg [$clog2(FRAME_US)-1:0] us_tick;
 reg [$clog2(WC+1)-1:0] wd;
 reg [31:0] requested_mask,active_mask,configured_mask,hold_mask,pending_mask;
 reg [31:0] accepted,rejected,watchdog_events,frames;
 reg pending,timeout_latched;
 reg [15:0] target[0:N-1],staged[0:N-1],goal[0:N-1],current[0:N-1];
 reg [15:0] lo[0:N-1],hi[0:N-1],neutral[0:N-1],step_us[0:N-1];
 reg aw_hold,w_hold;
 reg [C_S_AXI_ADDR_WIDTH-1:0] wa;
 reg [31:0] data;
 reg [3:0] strb;
 integer i,index;
 reg invalid,write_bad;
 wire disarming=aw_hold && w_hold && !s_axi_bvalid && strb==4'hf && wa==12'h008 && data==2;
 wire idle_config=(active_mask==0 && !pending && !timeout_latched);
 wire expires=(active_mask!=0 || pending) && !timeout_latched && (wd==WC-1);
 assign s_axi_awready=!aw_hold && !s_axi_bvalid;
 assign s_axi_wready=!w_hold && !s_axi_bvalid;
 assign s_axi_arready=!s_axi_rvalid;
 function automatic [15:0] slew(input [15:0] a,b,s);
  reg [16:0] diff;
  begin
   if(b>a) begin diff={1'b0,b}-{1'b0,a};slew=(diff>s)?a+s:b;end
   else begin diff={1'b0,a}-{1'b0,b};slew=(diff>s)?a-s:b;end
  end
 endfunction
 genvar g;
 generate for(g=0;g<N;g=g+1) begin:outputs
  always @(posedge s_axi_aclk or negedge s_axi_aresetn) begin
   if(!s_axi_aresetn) pwm[g]<=1'b0;
   else pwm[g]<=active_mask[g] && (us_tick<current[g]);
  end
 end endgenerate
 always @(posedge s_axi_aclk) begin
  if(!s_axi_aresetn) begin
   tick<=0;us_tick<=0;cycle_in_us<=0;wd<=0;requested_mask<=0;active_mask<=0;configured_mask<=0;
   hold_mask<=0;pending_mask<=0;pending<=0;timeout_latched<=0;
   accepted<=0;rejected<=0;watchdog_events<=0;frames<=0;
   aw_hold<=0;w_hold<=0;wa<=0;data<=0;strb<=0;
   s_axi_bvalid<=0;s_axi_bresp<=0;s_axi_rvalid<=0;s_axi_rdata<=0;s_axi_rresp<=0;
   for(i=0;i<N;i=i+1) begin
    target[i]<=1500;staged[i]<=1500;goal[i]<=1500;current[i]<=1500;
    lo[i]<=1500;hi[i]<=1500;neutral[i]<=1500;step_us[i]<=1;
   end
  end else begin
   if(tick==FC-1) begin
    us_tick<=0;cycle_in_us<=0;
   end else if(cycle_in_us==CPU-1) begin
    cycle_in_us<=0;us_tick<=us_tick+1'b1;
   end else cycle_in_us<=cycle_in_us+1'b1;
   if(tick==FC-1) begin
    tick<=0;frames<=frames+1;
    if(pending && !timeout_latched) begin
     active_mask<=pending_mask;pending<=0;
     for(i=0;i<N;i=i+1) begin
      goal[i]<=staged[i];
      if(!active_mask[i]) current[i]<=neutral[i];
      else if(pending_mask[i]) current[i]<=slew(current[i],staged[i],step_us[i]);
     end
    end else if(!timeout_latched) begin
     for(i=0;i<N;i=i+1)
      if(active_mask[i]) current[i]<=slew(current[i],goal[i],step_us[i]);
    end
   end else tick<=tick+1'b1;
   if((active_mask!=0 || pending) && !timeout_latched && !expires) wd<=wd+1'b1;
   if(s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
   if(s_axi_awvalid && s_axi_awready) begin wa<=s_axi_awaddr;aw_hold<=1;end
   if(s_axi_wvalid && s_axi_wready) begin data<=s_axi_wdata;strb<=s_axi_wstrb;w_hold<=1;end
   if(aw_hold && w_hold && !s_axi_bvalid) begin
    aw_hold<=0;w_hold<=0;s_axi_bvalid<=1;s_axi_bresp<=0;
    write_bad=0;index=0;invalid=0;
    if(strb!=4'hf || wa[1:0]!=0) write_bad=1;
    else if(wa==12'h008) begin
     if(data==2) begin
      active_mask<=0;requested_mask<=0;pending<=0;wd<=0;timeout_latched<=0;
     end else if(data==1) begin
      invalid=timeout_latched || expires || requested_mask==0 || ((requested_mask&~configured_mask)!=0);
      for(i=0;i<N;i=i+1)
       if(requested_mask[i] && (lo[i]<600 || hi[i]>2400 || lo[i]>neutral[i] ||
          neutral[i]>hi[i] || target[i]<lo[i] || target[i]>hi[i] || step_us[i]<1 || step_us[i]>100)) invalid=1;
      if(invalid) write_bad=1;
      else begin
       for(i=0;i<N;i=i+1) staged[i]<=target[i];
       pending_mask<=requested_mask;pending<=1;wd<=0;accepted<=accepted+1;
      end
     end else write_bad=1;
    end else if(wa==12'h010) begin
     if((data&~MASK)!=0) write_bad=1;else requested_mask<=data;
    end else if(wa==12'h018 || wa==12'h01c) begin
     if(!idle_config || (data&~MASK)!=0) write_bad=1;
     else if(wa==12'h018) configured_mask<=data;else hold_mask<=data;
    end else if(wa>=12'h100 && wa<12'h100+N*4) begin
     index=(wa-12'h100)>>2;
     if(data[31:16]!=0) write_bad=1;else target[index]<=data[15:0];
    end else if(wa>=12'h300 && wa<12'h300+N*4) begin
     index=(wa-12'h300)>>2;
     if(!idle_config || data<600 || data>2400) write_bad=1;else lo[index]<=data[15:0];
    end else if(wa>=12'h400 && wa<12'h400+N*4) begin
     index=(wa-12'h400)>>2;
     if(!idle_config || data<600 || data>2400) write_bad=1;else hi[index]<=data[15:0];
    end else if(wa>=12'h500 && wa<12'h500+N*4) begin
     index=(wa-12'h500)>>2;
     if(!idle_config || data<600 || data>2400) write_bad=1;else neutral[index]<=data[15:0];
    end else if(wa>=12'h600 && wa<12'h600+N*4) begin
     index=(wa-12'h600)>>2;
     if(!idle_config || data<1 || data>100) write_bad=1;else step_us[index]<=data[15:0];
    end else write_bad=1;
    if(write_bad) begin s_axi_bresp<=2;rejected<=rejected+1;end
   end
   // A watchdog expiration wins over a concurrent commit or frame update.
   // Hold-mask channels freeze their PWM setting; other channels are disabled.
   if(expires && !disarming) begin
    timeout_latched<=1;watchdog_events<=watchdog_events+1;
    active_mask<=active_mask&hold_mask;pending<=0;wd<=WC;
    for(i=0;i<N;i=i+1) current[i]<=current[i];
   end
   if(s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
   if(s_axi_arvalid && s_axi_arready) begin
    s_axi_rvalid<=1;s_axi_rresp<=0;s_axi_rdata<=0;
    if(s_axi_araddr[1:0]!=0) s_axi_rresp<=2;
    else case(s_axi_araddr)
     12'h000:s_axi_rdata<=32'h3232484e;
     12'h004:s_axi_rdata<=32'h00030000|N;
     12'h00c:s_axi_rdata<={29'b0,pending,timeout_latched,(active_mask!=0)};
     12'h010:s_axi_rdata<=requested_mask;
     12'h014:s_axi_rdata<=active_mask;
     12'h018:s_axi_rdata<=configured_mask;
     12'h01c:s_axi_rdata<=hold_mask;
     12'h020:s_axi_rdata<=accepted;
     12'h024:s_axi_rdata<=rejected;
     12'h028:s_axi_rdata<=watchdog_events;
     12'h02c:s_axi_rdata<=frames;
     12'h030:s_axi_rdata<=N;
     12'h034:s_axi_rdata<=WATCHDOG_MS;
     default:begin
      if(s_axi_araddr>=12'h100 && s_axi_araddr<12'h100+N*4)
       s_axi_rdata<={16'b0,target[(s_axi_araddr-12'h100)>>2]};
      else if(s_axi_araddr>=12'h200 && s_axi_araddr<12'h200+N*4)
       s_axi_rdata<={16'b0,current[(s_axi_araddr-12'h200)>>2]};
      else if(s_axi_araddr>=12'h300 && s_axi_araddr<12'h300+N*4)
       s_axi_rdata<={16'b0,lo[(s_axi_araddr-12'h300)>>2]};
      else if(s_axi_araddr>=12'h400 && s_axi_araddr<12'h400+N*4)
       s_axi_rdata<={16'b0,hi[(s_axi_araddr-12'h400)>>2]};
      else if(s_axi_araddr>=12'h500 && s_axi_araddr<12'h500+N*4)
       s_axi_rdata<={16'b0,neutral[(s_axi_araddr-12'h500)>>2]};
      else if(s_axi_araddr>=12'h600 && s_axi_araddr<12'h600+N*4)
       s_axi_rdata<={16'b0,step_us[(s_axi_araddr-12'h600)>>2]};
      else s_axi_rresp<=2;
     end
    endcase
   end
  end
 end
endmodule
