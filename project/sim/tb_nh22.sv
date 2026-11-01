// AXI transaction and electrical PWM tests; no physical hardware is accessed.
`timescale 1ns/1ps
module tb_nh22;
 reg clk=0;always #5 clk=~clk;
 reg rst=0;
 reg [11:0] awaddr=0,araddr=0;
 reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
 reg [31:0] wdata=0;
 reg [3:0] wstrb=15;
 wire awready,wready,bvalid,arready,rvalid;
 wire [1:0] bresp,rresp;
 wire [31:0] rdata;
 wire [21:0] pwm;
 nh22_axi #(.CLK_HZ(1000000),.WATCHDOG_MS(70)) d(
 .pwm(pwm),.s_axi_aclk(clk),.s_axi_aresetn(rst),
 .s_axi_awaddr(awaddr),.s_axi_awprot(3'b0),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
 .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
 .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
 .s_axi_araddr(araddr),.s_axi_arprot(3'b0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
 .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready));
 task wr(input [11:0] addr,input [31:0] value,input [1:0] response);
 begin
  @(negedge clk);awaddr=addr;awvalid=1;
  do @(posedge clk);while(!awready);
  @(negedge clk);awvalid=0;
  repeat(3) @(negedge clk);wdata=value;wvalid=1;
  do @(posedge clk);while(!wready);
  @(negedge clk);wvalid=0;
  wait(bvalid);#1;
  if(bresp!==response)$fatal(1,"write addr %h response %d expected %d",addr,bresp,response);
  repeat(3) begin @(negedge clk);if(!bvalid)$fatal(1,"B response not held");end
  bready=1;@(negedge clk);bready=0;
 end endtask
 task rd(input [11:0] addr,input [31:0] value,input [1:0] response);
 begin
  @(negedge clk);araddr=addr;arvalid=1;
  do @(posedge clk);while(!arready);
  @(negedge clk);arvalid=0;wait(rvalid);#1;
  if(rdata!==value || rresp!==response)$fatal(1,"read %h got %h/%d expected %h/%d",addr,rdata,rresp,value,response);
  repeat(3) begin @(negedge clk);if(!rvalid || rdata!==value)$fatal(1,"R response not held");end
  rready=1;@(negedge clk);rready=0;
 end endtask
 task boundary;
 begin wait(d.tick==19999);@(posedge clk);#1;end
 endtask
 integer i,width;
 initial begin
  repeat(5)@(negedge clk);rst=1;
  repeat(30)@(negedge clk);
  if(pwm!==0)$fatal(1,"outputs active on reset");
  rd('h000,32'h3232484e,0);
  wr('h010,1,0);wr('h008,1,2); // unconfigured commit
  wr('h010,32'h400000,2); // invalid bit 22
  rd('h800,0,2); // no address alias into low registers
  wstrb=1;wr('h100,1600,2);wstrb=15;rd('h100,1500,0);
  for(i=0;i<22;i=i+1) begin
   wr('h300+4*i,1490,0);wr('h400+4*i,1510,0);
   wr('h500+4*i,1500,0);wr('h600+4*i,2,0);
  end
  wr('h018,32'h310001,0);wr('h01c,32'h100000,0);
  wr('h100,1510,0);wr('h140,1490,0);wr('h150,1504,0);wr('h154,1506,0);
  wr('h010,32'h310001,0);wr('h008,1,0);
  if(d.active_mask!==0)$fatal(1,"enabled before frame boundary");
  boundary;
  if(d.active_mask!==32'h310001)$fatal(1,"atomic enable failed");
  @(posedge pwm[0]);#1;
  if(pwm!==22'h310001)$fatal(1,"registered outputs not aligned");
  width=0;
  while(pwm[0])begin width=width+1;@(posedge clk);#1;end
  if(width!=1500)$fatal(1,"pulse width %d",width);
  wr('h300,1480,2); // calibration locked while active
  boundary;
  rd('h200,1502,0);rd('h240,1498,0);rd('h250,1502,0);rd('h254,1502,0);
  // Out-of-mechanical-range command is rejected and does not refresh watchdog.
  wr('h100,1600,0);wr('h008,1,2);rd('h020,1,0);
  boundary;
  rd('h250,1504,0);
  wait(d.timeout_latched);#1;
  if(d.active_mask!==32'h100000)$fatal(1,"timeout policy failed");
  @(posedge clk);#1;if(pwm[21] || pwm[16] || pwm[0])$fatal(1,"registered timeout pin did not stop");
  rd('h028,1,0);rd('h250,1504,0);
  wr('h100,1500,0);wr('h008,1,2); // latched fault requires disarm
  wr('h008,2,0);if(pwm!==0)$fatal(1,"disarm did not disable");
  rd('h00c,0,0);
  wr('h010,32'h100000,0);wr('h008,1,0);boundary;
  // A STOP exactly on watchdog expiry must dominate hold-on-timeout.
  @(negedge clk);awaddr='h008;awvalid=1;wdata=2;wvalid=1;
  @(posedge clk);@(negedge clk);awvalid=0;wvalid=0;
  force d.wd=69999;
  @(posedge clk);#1;
  if(d.active_mask!==0 || d.timeout_latched!==0)$fatal(1,"STOP lost to watchdog expiry");
  @(posedge clk);#1;if(pwm!==0)$fatal(1,"registered PWM did not stop within one clock");
  release d.wd;
  @(negedge clk);bready=1;@(negedge clk);bready=0;
  $display("NH22_RTL_PASS: reset, 22 configuration slots, independent AXI AW/W, backpressure, address decode, atomic commit, pulse width, slew, limits, watchdog hold/disable, disarm");
  $finish;
 end
 initial begin #3000000;$fatal(1,"testbench timeout");end
endmodule
