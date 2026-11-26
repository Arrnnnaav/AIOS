"""What this PC is playing, captured on this PC (WASAPI loopback): the sound
of a tutorial video the person plays, for local transcription (Whisper) so
a video can become a walkthrough. Started and stopped by the person; the
audio stays in memory on this computer and is never stored or sent.

Through Windows' own audio API (comtypes, already a dependency): no driver,
no "Stereo Mix", no new package.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import POINTER, byref, c_float, c_int16, c_uint64, c_void_p
from ctypes.wintypes import DWORD, LPCWSTR, LPWSTR, UINT, WORD

import comtypes
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown

#: Whisper listens at 16 kHz mono.
RATE = 16_000
_LOOPBACK = 0x00020000  # AUDCLNT_STREAMFLAGS_LOOPBACK
_SILENT = 0x2  # AUDCLNT_BUFFERFLAGS_SILENT


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1  # as Windows declares it: 18 bytes, no padding
    _fields_ = [
        ("wFormatTag", WORD),
        ("nChannels", WORD),
        ("nSamplesPerSec", DWORD),
        ("nAvgBytesPerSec", DWORD),
        ("nBlockAlign", WORD),
        ("wBitsPerSample", WORD),
        ("cbSize", WORD),
    ]


class WAVEFORMATEXTENSIBLE(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("Format", WAVEFORMATEX),
        ("wValidBitsPerSample", WORD),
        ("dwChannelMask", DWORD),
        ("SubFormat", GUID),
    ]


_FLOAT = GUID(
    "{00000003-0000-0010-8000-00AA00389B71}"
)  # KSDATAFORMAT_SUBTYPE_IEEE_FLOAT


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "GetBuffer",
            (["out"], POINTER(c_void_p)),
            (["out"], POINTER(UINT)),
            (["out"], POINTER(DWORD)),
            (["out"], POINTER(c_uint64)),
            (["out"], POINTER(c_uint64)),
        ),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], UINT)),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(UINT))),
    ]


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "Initialize",
            (["in"], DWORD),
            (["in"], DWORD),
            (["in"], c_uint64),
            (["in"], c_uint64),
            (["in"], POINTER(WAVEFORMATEX)),
            (["in"], POINTER(GUID)),
        ),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(UINT))),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_uint64))),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(UINT))),
        COMMETHOD(
            [],
            HRESULT,
            "IsFormatSupported",
            (["in"], DWORD),
            (["in"], POINTER(WAVEFORMATEX)),
            (["out"], POINTER(POINTER(WAVEFORMATEX))),
        ),
        COMMETHOD(
            [], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)))
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDevicePeriod",
            (["out"], POINTER(c_uint64)),
            (["out"], POINTER(c_uint64)),
        ),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], c_void_p)),
        COMMETHOD(
            [],
            HRESULT,
            "GetService",
            (["in"], POINTER(GUID)),
            (["out"], POINTER(POINTER(IUnknown))),
        ),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "Activate",
            (["in"], POINTER(GUID)),
            (["in"], DWORD),
            (["in"], c_void_p),
            (["out"], POINTER(POINTER(IUnknown))),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "OpenPropertyStore",
            (["in"], DWORD),
            (["out"], POINTER(c_void_p)),
        ),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(LPWSTR))),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(DWORD))),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "EnumAudioEndpoints",
            (["in"], DWORD),
            (["in"], DWORD),
            (["out"], POINTER(c_void_p)),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDefaultAudioEndpoint",
            (["in"], DWORD),
            (["in"], DWORD),
            (["out"], POINTER(POINTER(IMMDevice))),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDevice",
            (["in"], LPCWSTR),
            (["out"], POINTER(POINTER(IMMDevice))),
        ),
    ]


_ENUMERATOR = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")


class _Resampler:
    """Streaming linear resampling to 16 kHz mono that carries its position
    across blocks: resampling each 10 ms block alone put a seam every block
    and moved a 440 Hz tone's peak to 240 Hz (measured 27 Nov)."""

    def __init__(self, rate: int):
        self.step = rate / RATE  # native samples per output sample
        self.tail = None  # the last native sample of the previous block
        self.pos = 0.0  # next output position, in native samples from the tail

    def feed(self, block):
        import numpy as np

        mono = block.mean(axis=1, dtype=np.float32)
        if not len(mono):
            return np.zeros(0, dtype=np.float32)
        if self.step == 1.0:
            return mono
        buf = mono if self.tail is None else np.concatenate(([self.tail], mono))
        last = len(buf) - 1
        count = int((last - self.pos) // self.step) + 1 if last >= self.pos else 0
        positions = self.pos + self.step * np.arange(count, dtype=np.float64)
        out = np.interp(positions, np.arange(len(buf)), buf).astype(np.float32)
        self.pos = (self.pos + self.step * count) - last  # relative to the new tail
        self.tail = buf[-1]
        return out


def record(stop, *, max_seconds: float = 900.0, sleep=time.sleep):
    """Capture what the default speakers play until STOP() or MAX_SECONDS.
    Returns 16 kHz mono float32 samples (a numpy array). Silence while
    nothing plays is captured as silence. Each block is turned into 16 kHz
    mono as it arrives, so 15 minutes stay under 60 MB whatever the device
    (a 192 kHz 7.1 mix kept as is would take gigabytes; review 27 Nov)."""

    import numpy as np

    comtypes.CoInitialize()
    enumerator = device = client = capture = None
    fmt = None
    chunks: list = []
    resampler = None
    try:
        enumerator = comtypes.CoCreateInstance(_ENUMERATOR, IMMDeviceEnumerator, CLSCTX_ALL)
        device = enumerator.GetDefaultAudioEndpoint(0, 1)  # eRender, eMultimedia
        client = device.Activate(byref(IAudioClient._iid_), CLSCTX_ALL, None).QueryInterface(IAudioClient)
        fmt = client.GetMixFormat()
        mix = fmt.contents
        channels, rate, bits = mix.nChannels, mix.nSamplesPerSec, mix.wBitsPerSample
        is_float = bits == 32 and (
            mix.wFormatTag == 3
            or (
                mix.wFormatTag == 0xFFFE
                and ctypes.cast(fmt, POINTER(WAVEFORMATEXTENSIBLE)).contents.SubFormat == _FLOAT
            )
        )
        resampler = _Resampler(rate)
        client.Initialize(0, _LOOPBACK, 10_000_000, 0, fmt, None)  # shared, 1 s buffer
        capture = client.GetService(byref(IAudioCaptureClient._iid_)).QueryInterface(IAudioCaptureClient)
        client.Start()
        until = time.monotonic() + max_seconds
        try:
            while not stop() and time.monotonic() < until:
                sleep(0.02)
                while capture.GetNextPacketSize():
                    data, frames, flags, _pos, _qpc = capture.GetBuffer()
                    try:
                        if not frames:
                            continue
                        if flags & _SILENT or not data:
                            block = np.zeros((frames, channels), dtype=np.float32)
                        elif is_float:
                            buf = (c_float * (frames * channels)).from_address(data)
                            block = np.frombuffer(buf, dtype=np.float32).reshape(frames, channels)
                        else:  # 16-bit PCM mix formats
                            buf = (c_int16 * (frames * channels)).from_address(data)
                            block = np.frombuffer(buf, dtype=np.int16).reshape(frames, channels).astype(np.float32) / 32768
                        chunks.append(resampler.feed(block))  # copies before the release
                    finally:
                        capture.ReleaseBuffer(frames)
        finally:
            try:
                client.Stop()
            except Exception:  # noqa: BLE001 - never hide the error that stopped it
                pass
    finally:
        if fmt is not None:
            ctypes.windll.ole32.CoTaskMemFree(fmt)
        # Every COM object goes before the apartment does (review 27 Nov).
        enumerator = device = client = capture = None
        import gc

        gc.collect()
        comtypes.CoUninitialize()
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32)
