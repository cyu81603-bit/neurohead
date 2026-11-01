// Check actual 50MHz timebase -> 20ms frame and 1500us high pulse.
`timescale 1ns/1ps
module tb_nh22_50mhz;
 reg clk=0;always #10 clk=~clk;
 reg rst=0,valid=0;
 reg [11:0] addr=0;
 reg [31:0] data=0;
 wire awready,wready,bvalid,pwm;
 wire [1:0] bresp;
 nh22_axi #(.N(1)) d(.pwm(pwm),.s_axi_aclk(clk),.s_axi_aresetn(rst),
 .s_axi_awaddr(addr),.s_axi_awprot(3'b0),.s_axi_awvalid(valid),.s_axi_awready(awready),
 .s_axi_wdata(data),.s_axi_wstrb(4'hf),.s_axi_wvalid(valid),.s_axi_wready(wready),
 .s_axi_bvalid(bvalid),.s_axi_bresp(bresp),.s_axi_bready(1'b1),
 .s_axi_araddr(12'b0),.s_axi_arprot(3'b0),.s_axi_arvalid(1'b0),.s_axi_arready(),
 .s_axi_rdata(),.s_axi_rresp(),.s_axi_rvalid(),.s_axi_rready(1'b1));
 task wr(input [11:0] a,input [31:0] v);
 begin
  @(negedge clk);addr=a;data=v;valid=1;
  @(posedge clk);if(!awready || !wready)$fatal(1,"not ready");
  @(negedge clk);valid=0;wait(bvalid);#1;if(bresp!=0)$fatal(1,"write rejected");
  @(negedge clk);@(negedge clk);
 end endtask
 time rise,fall,next_rise;
 initial begin
  repeat(3)@(negedge clk);rst=1;
  wr('h018,1);wr('h010,1);wr('h008,1);
  @(posedge pwm);rise=$time;
  @(negedge pwm);fall=$time;
  if(fall-rise!=1500000)$fatal(1,"expected 1500000ns high, got %d",fall-rise);
  @(posedge pwm);next_rise=$time;
  if(next_rise-rise!=20000000)$fatal(1,"expected 20000000ns period, got %d",next_rise-rise);
  @(negedge clk);rst=0;#1;
  if(pwm!==0)$fatal(1,"reset did not suppress pulse");
  $display("NH22_50MHZ_PWM_PASS: 1500us high, 20ms period, reset suppresses PWM");
  $finish;
 end
 initial begin #60000000;$fatal(1,"timeout");end
endmodule
