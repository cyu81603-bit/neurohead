/* Minimal standalone Zynq interrupt/timer support for lwIP raw mode. */
#include "xparameters.h"
#include "xparameters_ps.h"
#include "xil_cache.h"
#include "xil_exception.h"
#include "xil_printf.h"
#include "xscugic.h"
#include "xscutimer.h"
#include "netif/xadapter.h"
#include "lwip/tcp.h"

#define INTC_DEVICE_ID       XPAR_SCUGIC_SINGLE_DEVICE_ID
#define TIMER_DEVICE_ID      XPAR_SCUTIMER_DEVICE_ID
#define INTC_BASE_ADDR       XPAR_SCUGIC_0_CPU_BASEADDR
#define INTC_DIST_BASE_ADDR  XPAR_SCUGIC_0_DIST_BASEADDR
#define TIMER_IRPT_INTR      XPAR_SCUTIMER_INTR
#define RESET_RX_TICKS       4U

static XScuTimer timer_instance;
static struct netif *attached_netif;
static unsigned int reset_rx_ticks;
volatile int TcpFastTmrFlag;
volatile int TcpSlowTmrFlag;
static unsigned int timer_phase;

/* Required by the standalone C runtime when no C++ constructors are used. */
void _init(void) {}
void _fini(void) {}

void neurohead_platform_attach_netif(struct netif *netif)
{
    attached_netif = netif;
}

static void timer_callback(XScuTimer *timer)
{
    TcpFastTmrFlag = 1;
    timer_phase ^= 1U;
    if (timer_phase != 0U) TcpSlowTmrFlag = 1;
    ++reset_rx_ticks;
    if (attached_netif != 0 && reset_rx_ticks >= RESET_RX_TICKS) {
        /* Vendor lwIP workaround for the Zynq GEM RX-stall erratum. */
        xemacpsif_resetrx_on_no_rxdata(attached_netif);
        reset_rx_ticks = 0U;
    }
    XScuTimer_ClearInterruptStatus(timer);
}

int neurohead_platform_init(void)
{
    int status;
    XScuTimer_Config *timer_config;

    Xil_ICacheEnable();
    Xil_DCacheEnable();

    timer_config = XScuTimer_LookupConfig(TIMER_DEVICE_ID);
    if (timer_config == 0) return XST_FAILURE;
    status = XScuTimer_CfgInitialize(&timer_instance, timer_config,
                                     timer_config->BaseAddr);
    if (status != XST_SUCCESS) return status;

    XScuTimer_EnableAutoReload(&timer_instance);
    /* 250 ms period: four ticks per second, reset check every 1 s. */
    XScuTimer_LoadTimer(&timer_instance,
                        XPAR_CPU_CORTEXA9_0_CPU_CLK_FREQ_HZ / 8U);

    Xil_ExceptionInit();
    XScuGic_DeviceInitialize(INTC_DEVICE_ID);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_IRQ_INT,
        (Xil_ExceptionHandler)XScuGic_DeviceInterruptHandler,
        (void *)INTC_DEVICE_ID);
    XScuGic_RegisterHandler(INTC_BASE_ADDR, TIMER_IRPT_INTR,
        (Xil_ExceptionHandler)timer_callback, (void *)&timer_instance);
    XScuGic_EnableIntr(INTC_DIST_BASE_ADDR, TIMER_IRPT_INTR);
    return XST_SUCCESS;
}

void neurohead_platform_enable_interrupts(void)
{
    Xil_ExceptionEnableMask(XIL_EXCEPTION_IRQ);
    XScuTimer_EnableInterrupt(&timer_instance);
    XScuTimer_Start(&timer_instance);
}

void neurohead_platform_cleanup(void)
{
    XScuTimer_Stop(&timer_instance);
    Xil_DCacheDisable();
    Xil_ICacheDisable();
}
