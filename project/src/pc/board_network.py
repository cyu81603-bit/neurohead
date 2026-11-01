"""Select the Windows IPv4 egress interface as well as the board source IP."""
import os
import socket


def interface_index_for_ip(ip):
    if os.name!='nt':return None
    import ctypes as c
    from ctypes import wintypes as w
    class SocketAddress(c.Structure):
        _fields_=[('address',c.c_void_p),('length',c.c_int)]
    class Unicast(c.Structure):pass
    Unicast._fields_=[('alignment',c.c_ulonglong),('next',c.POINTER(Unicast)),('socket',SocketAddress)]
    class Adapter(c.Structure):pass
    Adapter._fields_=[('length',w.ULONG),('index',w.ULONG),('next',c.POINTER(Adapter)),
                     ('name',c.c_char_p),('unicast',c.POINTER(Unicast))]
    get=c.WinDLL('iphlpapi').GetAdaptersAddresses
    get.argtypes=[w.ULONG,w.ULONG,c.c_void_p,c.c_void_p,c.POINTER(w.ULONG)]
    get.restype=w.ULONG
    size=w.ULONG(15000)
    for _ in range(3):
        buffer=c.create_string_buffer(size.value)
        result=get(socket.AF_INET,0,None,buffer,c.byref(size))
        if result==111:continue
        if result:raise OSError(result,'GetAdaptersAddresses failed')
        adapter=c.cast(buffer,c.POINTER(Adapter))
        while adapter:
            item=adapter.contents;unicast=item.unicast
            while unicast:
                entry=unicast.contents
                if entry.socket.address and entry.socket.length>=16:
                    raw=c.string_at(entry.socket.address,16)
                    if int.from_bytes(raw[:2],'little')==socket.AF_INET and socket.inet_ntoa(raw[4:8])==ip:
                        return item.index
                unicast=entry.next
            adapter=item.next
        raise OSError(f'No local Windows adapter owns {ip}')
    raise OSError('Adapter list changed repeatedly')


def bind_board_socket(sock,ip='192.168.10.10',interface_index=None):
    sock.bind((ip,0))
    if os.name=='nt':
        index=interface_index if interface_index is not None else interface_index_for_ip(ip)
        if type(index) is not int or index<=0:raise ValueError('Invalid IPv4 interface index')
        # Winsock IP_UNICAST_IF (31) takes the interface index in network byte order.
        sock.setsockopt(socket.IPPROTO_IP,31,socket.htonl(index))
        return index
    return None
