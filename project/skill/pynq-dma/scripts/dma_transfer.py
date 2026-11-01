"""Bounded polling for full-buffer, equal-size AXI DMA simple transfers."""
import math
import time


class TransferFailure(RuntimeError):
    def __init__(self, message, dma, buffers, snapshot):
        super().__init__(message)
        self.dma = dma
        self.buffers = buffers  # Keep allocations alive until explicit recovery.
        self.snapshot = snapshot


def _snapshot(dma):
    result = {}
    try:
        result['register_map'] = str(dma.register_map)
    except Exception as exc:
        result['register_map'] = type(exc).__name__ + ': ' + str(exc)
    for label, channel in [('send', dma.sendchannel), ('recv', dma.recvchannel)]:
        result[label] = {}
        for name in ('idle', 'running', 'error', 'transferred'):
            try:
                result[label][name] = getattr(channel, name)
            except Exception as exc:
                result[label][name] = type(exc).__name__ + ': ' + str(exc)
    return result


def exchange(dma, tx, rx, *, timeout, max_bytes, tx_word_bytes, rx_word_bytes,
             tx_dre, rx_dre, poll_seconds=0.001, start_ip=None):
    """Caller owns buffers. No implicit reset/retry/free, even on failure."""
    for value in (timeout, poll_seconds):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('timeout and poll_seconds must be finite positive values')
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('max_bytes must be a positive integer from the DMA configuration')
    parameters = getattr(dma, 'description', {}).get('parameters', {})
    if any(key not in parameters for key in ('c_include_sg', 'c_micro_dma')):
        raise ValueError('explicit simple/non-micro HWH DMA parameters required')
    if int(parameters['c_include_sg']) or int(parameters['c_micro_dma']):
        raise ValueError('SG and Micro DMA are outside this helper')
    if tx is rx:
        raise ValueError('use distinct tx/rx allocations')
    for buf, width, dre in ((tx, tx_word_bytes, tx_dre), (rx, rx_word_bytes, rx_dre)):
        if type(width) is not int or width <= 0 or type(dre) is not bool:
            raise ValueError('explicit channel width and DRE required')
        if not all(hasattr(buf, attr) for attr in ('device_address', 'nbytes', 'flush', 'invalidate')):
            raise TypeError('use PYNQ allocated buffers')
        if not buf.flags.c_contiguous or not (0 < buf.nbytes <= max_bytes):
            raise ValueError('invalid contiguous buffer length')
        if not dre and (buf.device_address % width or buf.nbytes % width):
            raise ValueError('unaligned address/length without DRE')
    if tx.nbytes != rx.nbytes:
        raise ValueError('this helper requires equal frame byte counts')
    if max(tx.device_address, rx.device_address) < min(
            tx.device_address + tx.nbytes, rx.device_address + rx.nbytes):
        raise ValueError('overlapping device allocations')
    # PYNQ simple channels can have idle=0 before their first transfer. This is a
    # version-dependent private driver flag: absent means fail closed when busy.
    for channel in (dma.sendchannel, dma.recvchannel):
        if channel.error or not channel.running or (not channel.idle and not getattr(channel, '_first_transfer', False)):
            raise ValueError('DMA stopped, busy or in error before transfer')
    started = time.monotonic()
    deadline = started + timeout
    try:
        tx.flush()
        # Flush dirty receive cache lines before device writes into the same memory.
        rx.flush()
        dma.recvchannel.transfer(rx)
        if start_ip is not None:
            start_ip()
        dma.sendchannel.transfer(tx)
        while True:
            if dma.sendchannel.error or dma.recvchannel.error:
                raise RuntimeError('DMA error flag')
            if dma.sendchannel.idle and dma.recvchannel.idle:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('DMA deadline expired; inspect TLAST/DMASR')
            time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
        # Simple-mode wait performs driver accounting/invalidation after idle is known.
        dma.sendchannel.wait()
        dma.recvchannel.wait()
        if dma.sendchannel.transferred != tx.nbytes or dma.recvchannel.transferred != rx.nbytes:
            raise RuntimeError('short transfer')
        rx.invalidate()
        return dict(bytes_per_direction=tx.nbytes, elapsed_seconds=time.monotonic()-started,
                    scope='host round trip including cache sync and polling')
    except Exception as exc:
        before = _snapshot(dma)
        stops = {}
        for name, channel in [('send', dma.sendchannel), ('recv', dma.recvchannel)]:
            try:
                # PYNQ stop() may itself poll MMIO; this is not a hard realtime deadline.
                channel.stop()
                stops[name] = 'returned; recovery must confirm quiescence'
            except Exception as stop_error:
                stops[name] = repr(stop_error)
        raise TransferFailure(str(exc), dma, (tx, rx),
                              dict(before_stop=before, stop=stops, buffers_retained=True)) from exc
