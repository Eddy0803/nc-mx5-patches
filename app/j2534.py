"""Minimal SAE J2534 (PassThru 04.04) binding for reading an ECU over ISO 15765 (CAN). Windows only.

Only what the app needs: list installed interfaces, open one, connect ISO15765 at 500 kbit/s with a flow-control
filter, send a request and wait for the reply. Nothing here writes to the ECU's memory; the app only sends
read requests.
"""
import ctypes, struct, sys, winreg

ISO15765, CAN = 6, 5
FLOW_CONTROL_FILTER = 3
ISO15765_FRAME_PAD = 0x40
TX_MSG_TYPE, START_OF_MESSAGE, TX_INDICATION = 0x01, 0x02, 0x08
CLEAR_TX_BUFFER, CLEAR_RX_BUFFER = 0x07, 0x08
ERRORS = {0: 'OK', 1: 'not supported', 2: 'invalid channel', 3: 'invalid protocol', 4: 'NULL parameter',
          5: 'invalid ioctl value', 6: 'invalid flags', 7: 'failed', 8: 'device not connected', 9: 'timeout',
          0x0A: 'invalid message', 0x0B: 'invalid time interval', 0x0C: 'exceeded limit', 0x0D: 'invalid message id',
          0x0E: 'device in use', 0x0F: 'invalid ioctl id', 0x10: 'buffer empty', 0x11: 'buffer full', 0x12: 'buffer overflow',
          0x13: 'pin invalid', 0x14: 'channel in use', 0x15: 'message protocol id', 0x16: 'invalid filter id',
          0x17: 'no flow control', 0x18: 'not unique', 0x19: 'invalid baudrate', 0x1A: 'invalid device id'}
APP_BITS = 64 if sys.maxsize > 2 ** 32 else 32


class PASSTHRU_MSG(ctypes.Structure):
    _fields_ = [('ProtocolID', ctypes.c_ulong), ('RxStatus', ctypes.c_ulong), ('TxFlags', ctypes.c_ulong),
                ('Timestamp', ctypes.c_ulong), ('DataSize', ctypes.c_ulong), ('ExtraDataIndex', ctypes.c_ulong),
                ('Data', ctypes.c_ubyte * 4128)]


class J2534Error(Exception):
    pass


def dll_bits(path):
    try:
        with open(path, 'rb') as f:
            b = f.read(4096)
        pe = struct.unpack_from('<I', b, 0x3C)[0]
        m = struct.unpack_from('<H', b, pe + 4)[0]
        return {0x14C: 32, 0x8664: 64}.get(m)
    except (OSError, struct.error):
        return None


def list_devices():
    """installed J2534 04.04 interfaces -> [{name, vendor, dll, bits, usable, iso15765}]"""
    found = {}
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\PassThruSupport.04.04', 0, winreg.KEY_READ | view)
        except OSError:
            continue
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                k = winreg.OpenKey(root, sub, 0, winreg.KEY_READ | view)
                try: dll = winreg.QueryValueEx(k, 'FunctionLibrary')[0]
                except OSError: continue
                try: vendor = winreg.QueryValueEx(k, 'Vendor')[0]
                except OSError: vendor = ''
                try: iso = int(winreg.QueryValueEx(k, 'ISO15765')[0])
                except (OSError, ValueError): iso = 1
            except OSError:
                continue
            bits = dll_bits(dll)
            found[dll.lower()] = {'name': sub, 'vendor': vendor, 'dll': dll, 'bits': bits,
                                  'usable': bits == APP_BITS, 'iso15765': bool(iso)}
    return sorted(found.values(), key=lambda d: (not d['usable'], d['name']))


class PassThru:
    def __init__(self, dll_path):
        loader = ctypes.WinDLL if APP_BITS == 32 else ctypes.CDLL       # J2534 is __stdcall on 32-bit Windows
        try:
            self.dll = loader(dll_path)
        except OSError as e:
            raise J2534Error(f'could not load the J2534 driver ({e}). Is it a {APP_BITS}-bit driver?')
        L, PL = ctypes.c_long, ctypes.POINTER(ctypes.c_ulong)
        PM = ctypes.POINTER(PASSTHRU_MSG)
        spec = {'PassThruOpen': [ctypes.c_void_p, PL], 'PassThruClose': [ctypes.c_ulong],
                'PassThruConnect': [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, PL],
                'PassThruDisconnect': [ctypes.c_ulong],
                'PassThruReadMsgs': [ctypes.c_ulong, PM, PL, ctypes.c_ulong],
                'PassThruWriteMsgs': [ctypes.c_ulong, PM, PL, ctypes.c_ulong],
                'PassThruStartMsgFilter': [ctypes.c_ulong, ctypes.c_ulong, PM, PM, PM, PL],
                'PassThruIoctl': [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p],
                'PassThruReadVersion': [ctypes.c_ulong, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p],
                'PassThruGetLastError': [ctypes.c_char_p]}
        for name, args in spec.items():
            f = getattr(self.dll, name, None)
            if f is None:
                if name in ('PassThruReadVersion', 'PassThruGetLastError'): continue
                raise J2534Error(f'the driver has no {name} - not a J2534 04.04 driver?')
            f.argtypes, f.restype = args, L
        self.dev = self.chan = None

    def _check(self, rc, what):
        if rc != 0:
            msg = ERRORS.get(rc, f'error {rc} from the driver - is the interface plugged in and the ignition on?')
            try:
                buf = ctypes.create_string_buffer(256)
                if self.dll.PassThruGetLastError(buf) == 0 and buf.value:
                    msg += f' ({buf.value.decode(errors="replace")})'
            except AttributeError:
                pass
            raise J2534Error(f'{what}: {msg}')

    def open(self):
        dev = ctypes.c_ulong()
        self._check(self.dll.PassThruOpen(None, ctypes.byref(dev)), 'open the interface')
        self.dev = dev.value

    def version(self):
        try:
            fw, dl, api = (ctypes.create_string_buffer(80) for _ in range(3))
            if self.dll.PassThruReadVersion(self.dev, fw, dl, api) == 0:
                return f'firmware {fw.value.decode(errors="replace")}, driver {dl.value.decode(errors="replace")}'
        except AttributeError:
            pass
        return ''

    def connect_iso15765(self, tx_id=0x7E0, rx_id=0x7E8, baud=500000):
        ch = ctypes.c_ulong()
        self._check(self.dll.PassThruConnect(self.dev, ISO15765, 0, baud, ctypes.byref(ch)), 'connect ISO15765')
        self.chan = ch.value
        mask, pattern, flow = (self._msg(b'\xFF\xFF\xFF\xFF'), self._msg(struct.pack('>I', rx_id)),
                               self._msg(struct.pack('>I', tx_id)))
        fid = ctypes.c_ulong()
        self._check(self.dll.PassThruStartMsgFilter(self.chan, FLOW_CONTROL_FILTER, ctypes.byref(mask), ctypes.byref(pattern),
                                                    ctypes.byref(flow), ctypes.byref(fid)), 'set up the CAN filter')
        self.tx_id = tx_id
        self.dll.PassThruIoctl(self.chan, CLEAR_RX_BUFFER, None, None)

    @staticmethod
    def _msg(data, flags=ISO15765_FRAME_PAD):
        m = PASSTHRU_MSG(); m.ProtocolID = ISO15765; m.TxFlags = flags
        m.DataSize = len(data); ctypes.memmove(m.Data, data, len(data))
        return m

    def request(self, payload, timeout_ms=500):
        """send a diagnostic request to the ECU and return its reply payload (without the CAN id), or None on timeout"""
        self.dll.PassThruIoctl(self.chan, CLEAR_RX_BUFFER, None, None)
        m = self._msg(struct.pack('>I', self.tx_id) + bytes(payload))
        n = ctypes.c_ulong(1)
        self._check(self.dll.PassThruWriteMsgs(self.chan, ctypes.byref(m), ctypes.byref(n), 500), 'send')
        import time
        end = time.time() + timeout_ms / 1000
        while time.time() < end:
            r = PASSTHRU_MSG(); n = ctypes.c_ulong(1)
            rc = self.dll.PassThruReadMsgs(self.chan, ctypes.byref(r), ctypes.byref(n), 50)
            if rc not in (0, 9, 0x10) or n.value == 0:          # 9 = timeout, 0x10 = buffer empty
                if rc not in (0, 9, 0x10): self._check(rc, 'receive')
                continue
            if r.RxStatus & (TX_MSG_TYPE | START_OF_MESSAGE | TX_INDICATION):
                continue                                           # echoes / first-frame indications
            data = bytes(r.Data[:r.DataSize])
            if len(data) <= 4: continue
            body = data[4:]
            if body[:1] == b'\x7F' and len(body) >= 3 and body[2] == 0x78:   # "response pending"
                end = time.time() + 2; continue
            return body
        return None

    def close(self):
        try:
            if self.chan is not None: self.dll.PassThruDisconnect(self.chan)
        finally:
            self.chan = None
            if self.dev is not None:
                try: self.dll.PassThruClose(self.dev)
                finally: self.dev = None
