/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "stubs.h"
#include "video/out/decklink_bridge.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <vector>
#include <algorithm>

static bool same(REFIID a, REFIID b) { return !memcmp(&a, &b, sizeof(a)); }
template<class T> static HRESULT take(T &obj, void **p) {
    obj.AddRef(); *p = &obj; return S_OK;
}
static bool fail_enable, fail_bytes, fail_access, fail_end, fail_frame, no_device;
static bool interlaced, unsupported, enabled;
static int starts, ends, displays, disables;
static int64_t connection = bmdVideoConnectionSDI;
static bool audio_enabled, fail_audio_enable, fail_audio_write, fail_audio_query;
static bool audio_queue_started;
static uint32_t audio_write_limit = 10000;
static std::vector<int16_t> audio_queue;

static struct Buffer : StubIDeckLinkVideoBuffer {
    // 4 pixels x 2 rows with deliberate 8-byte row padding.
    std::array<uint8_t, 32> bytes;
    HRESULT StartAccess(BMDBufferAccessFlags flags) override {
        assert(flags == bmdBufferAccessWrite);
        if (fail_access) return E_FAIL;
        ++starts; return S_OK;
    }
    HRESULT EndAccess(BMDBufferAccessFlags) override { ++ends; return fail_end ? E_FAIL : S_OK; }
    HRESULT GetBytes(void **p) override {
        if (fail_bytes) return E_FAIL;
        *p = bytes.data(); return S_OK;
    }
} buffer;

static struct Frame : StubIDeckLinkMutableVideoFrame {
    HRESULT QueryInterface(REFIID iid, void **p) override {
        if (same(iid, IID_IDeckLinkVideoBuffer)) return take(buffer, p);
        return E_NOINTERFACE;
    }
} frame;

static struct Mode : StubIDeckLinkDisplayMode {
    long GetWidth() override { return 4; }
    long GetHeight() override { return 2; }
    BMDDisplayMode GetDisplayMode() override { return bmdModeHD1080p2997; }
    BMDFieldDominance GetFieldDominance() override {
        return interlaced ? bmdUpperFieldFirst : bmdProgressiveFrame;
    }
    HRESULT GetFrameRate(BMDTimeValue *duration, BMDTimeScale *scale) override {
        *duration = 1001; *scale = 30000; return S_OK;
    }
} mode;

static struct Output : StubIDeckLinkOutput {
    HRESULT EnableAudioOutput(BMDAudioSampleRate rate, BMDAudioSampleType type,
                              uint32_t channels, BMDAudioOutputStreamType stream) override {
        assert(enabled && !audio_enabled);
        assert(rate == bmdAudioSampleRate48kHz && type == bmdAudioSampleType16bitInteger);
        assert(channels == 2 && stream == bmdAudioOutputStreamContinuous);
        if (fail_audio_enable) return E_FAIL;
        audio_enabled = true; audio_queue_started = false; return S_OK;
    }
    HRESULT DisableAudioOutput() override {
        assert(audio_enabled); audio_enabled = false; audio_queue.clear(); return S_OK;
    }
    HRESULT WriteAudioSamplesSync(void *data, uint32_t frames, uint32_t *written) override {
        assert(audio_enabled && enabled);
        if (fail_audio_write) return E_FAIL;
        audio_queue_started = true;
        *written = std::min(frames, audio_write_limit);
        auto *pcm = static_cast<int16_t *>(data);
        audio_queue.insert(audio_queue.end(), pcm, pcm + *written * 2);
        return S_OK;
    }
    HRESULT GetBufferedAudioSampleFrameCount(uint32_t *frames) override {
        if (fail_audio_query || !audio_queue_started) return E_FAIL;
        *frames = audio_queue.size() / 2; return S_OK;
    }
    // Synchronous output on the tested driver retained stale queue accounting
    // after Flush. Pause/seek must reset the audio engine with Disable instead.
    HRESULT FlushBufferedAudioSamples() override { return S_OK; }
    HRESULT GetDisplayMode(BMDDisplayMode id, IDeckLinkDisplayMode **p) override {
        assert(id == bmdModeHD1080p2997); return take(mode, (void **)p);
    }
    HRESULT DoesSupportVideoMode(BMDVideoConnection c, BMDDisplayMode id,
        BMDPixelFormat f, BMDVideoOutputConversionMode conversion,
        BMDSupportedVideoModeFlags, BMDDisplayMode *actual, bool *ok) override {
        assert(c == bmdVideoConnectionHDMI && f == bmdFormat8BitYUV);
        assert(conversion == bmdNoVideoOutputConversion);
        *actual = id; *ok = !unsupported; return S_OK;
    }
    HRESULT EnableVideoOutput(BMDDisplayMode, BMDVideoOutputFlags) override {
        if (fail_enable) return E_ACCESSDENIED;
        enabled = true; return S_OK;
    }
    HRESULT DisableVideoOutput() override {
        assert(enabled); enabled = false; ++disables; return S_OK;
    }
    HRESULT RowBytesForPixelFormat(BMDPixelFormat, int32_t width, int32_t *row) override {
        assert(width == 4); *row = 16; return S_OK;
    }
    HRESULT CreateVideoFrame(int32_t w, int32_t h, int32_t row, BMDPixelFormat f,
        BMDFrameFlags, IDeckLinkMutableVideoFrame **p) override {
        assert(w == 4 && h == 2 && row == 16 && f == bmdFormat8BitYUV);
        if (fail_frame) return E_FAIL;
        return take(frame, (void **)p);
    }
    HRESULT DisplayVideoFrameSync(IDeckLinkVideoFrame *f) override {
        assert(f == &frame && starts == ends && enabled); ++displays; return S_OK;
    }
} output;

static struct Config : StubIDeckLinkConfiguration {
    ULONG Release() override {
        auto count = StubIDeckLinkConfiguration::Release();
        if (!count) connection = bmdVideoConnectionSDI;
        return count;
    }
    HRESULT GetInt(BMDDeckLinkConfigurationID id, int64_t *value) override {
        assert(id == bmdDeckLinkConfigVideoOutputConnection); *value = connection; return S_OK;
    }
    HRESULT SetInt(BMDDeckLinkConfigurationID id, int64_t value) override {
        assert(value == bmdVideoConnectionHDMI);
        assert(id == bmdDeckLinkConfigVideoOutputConnection); connection = value; return S_OK;
    }
} config;

static struct Device : StubIDeckLink {
    HRESULT QueryInterface(REFIID iid, void **p) override {
        if (same(iid, IID_IDeckLinkOutput)) return take(output, p);
        if (same(iid, IID_IDeckLinkConfiguration)) return take(config, p);
        return E_NOINTERFACE;
    }
} device;

static struct Iterator : StubIDeckLinkIterator {
    int next = 0;
    HRESULT Next(IDeckLink **p) override {
        *p = nullptr;
        if (next++ || no_device) return S_FALSE;
        return take(device, (void **)p);
    }
} iterator;

extern "C" IDeckLinkIterator *CreateDeckLinkIteratorInstance()
{
    iterator.next = 0; iterator.AddRef(); return &iterator;
}

static void log_message(void *, bool, const char *) {}
static decklink *open() { return decklink_open(0, "Hp29", log_message, nullptr); }
static void clean()
{
    assert(!enabled && !audio_enabled && connection == bmdVideoConnectionSDI);
    assert(!buffer.refs && !frame.refs && !mode.refs && !output.refs &&
           !config.refs && !device.refs && !iterator.refs);
}

int main()
{
    assert(!decklink_open(0, "invalid", log_message, nullptr)); clean();
    assert(!decklink_open(1, "Hp29", log_message, nullptr)); clean();
    no_device = true; assert(!open()); clean(); no_device = false;
    interlaced = true; assert(!open()); clean(); interlaced = false;
    unsupported = true; assert(!open()); clean(); unsupported = false;
    fail_enable = true; assert(!open()); clean(); fail_enable = false;
    assert(disables == 0);
    fail_frame = true; assert(!open()); clean(); fail_frame = false;
    assert(disables == 1);
    auto *d = open(); assert(d);
    int w, h; double fps;
    decklink_get_mode(d, &w, &h, &fps);
    assert(w == 4 && h == 2 && fps == 30000.0 / 1001);
    buffer.bytes.fill(0xee);
    // Source has a different stride from the device frame.
    const uint8_t src[] = {1,2,3,4,5,6,7,8,99,99,99,99,9,10,11,12,13,14,15,16};
    assert(decklink_display(d, src, 12) == 0 && displays == 1);
    assert(!memcmp(buffer.bytes.data(), src, 8));
    assert(!memcmp(buffer.bytes.data() + 16, src + 12, 8));
    assert(buffer.bytes[8] == 0xee && buffer.bytes[24] == 0xee);
    assert(decklink_display(d, src, 4) == -1 && displays == 1);
    fail_bytes = true; assert(decklink_display(d, src, 12) == -1);
    assert(starts == ends && displays == 1); fail_bytes = false;
    fail_access = true; assert(decklink_display(d, src, 12) == -1);
    assert(starts == ends && displays == 1); fail_access = false;
    fail_end = true; assert(decklink_display(d, src, 12) == -1);
    assert(starts == ends && displays == 1); fail_end = false;
    decklink_close(d); clean();
    assert(disables == 2);
    puts("PASS: modes, fractional fps, missing device, initialization failures, stride, buffer access and cleanup");

    int owner, other;
    assert(!decklink_audio_open(&owner, log_message, nullptr));
    d = open(); assert(d); decklink_register(d, &owner);
    assert(!decklink_audio_open(&other, log_message, nullptr));
    fail_audio_enable = true;
    assert(!decklink_audio_open(&owner, log_message, nullptr));
    fail_audio_enable = false;
    auto *a = decklink_audio_open(&owner, log_message, nullptr); assert(a);
    assert(!decklink_audio_open(&owner, log_message, nullptr));
    int16_t pcm[] = {10,11,20,21,30,31,40,41,50,51,60,61};
    assert(decklink_audio_write(a, pcm, 6) == 0);
    assert(audio_queue.empty()); // write must NOT start the device.
    decklink_audio_state state;
    assert(decklink_audio_get_state(a, &state) == 0 && state.queued == 6 && !state.playing);
    audio_write_limit = 2;
    assert(decklink_audio_start(a) == 0 && audio_queue.size() == 4);
    audio_write_limit = 0;
    assert(decklink_audio_get_state(a, &state) == 0 && state.queued == 6 && state.playing);
    assert(audio_queue.size() == 4); // zero write preserves pending audio.
    audio_queue.erase(audio_queue.begin(), audio_queue.begin()+2); // one frame played
    assert(decklink_audio_get_state(a, &state) == 0 && state.queued == 5);
    assert(decklink_audio_pause(a, true) == 0 && audio_queue.empty());
    assert(decklink_audio_get_state(a, &state) == 0 && state.queued == 5);
    audio_write_limit = 10000;
    assert(decklink_audio_pause(a, false) == 0 && audio_queue.size() == 10);
    assert(!memcmp(audio_queue.data(), pcm+2, 10*sizeof(int16_t)));
    assert(decklink_audio_reset(a) == 0 && audio_queue.empty());
    assert(decklink_audio_get_state(a, &state) == 0 && state.queued == 0 && !state.playing);
    assert(decklink_audio_write(a, pcm, DECKLINK_AUDIO_CAPACITY+1) < 0);
    assert(decklink_audio_write(a, pcm, 2) == 0 && audio_queue.empty());
    assert(decklink_audio_start(a) == 0);
    audio_queue.clear(); // drain/EOF
    assert(decklink_audio_get_state(a, &state) == 0 && state.queued == 0 && !state.playing);
    // VO can disappear before AO; its hardware clock/config must stay alive.
    assert(!audio_enabled); // drained engine is reset before re-use
    assert(decklink_audio_write(a, pcm, 2) == 0 && audio_enabled);
    decklink_close(d); assert(enabled && audio_enabled);
    assert(!decklink_audio_open(&owner, log_message, nullptr));
    decklink_audio_close(a); clean();

    // Reverse teardown order, SDK errors and a new audio track.
    d = open(); decklink_register(d, &owner);
    a = decklink_audio_open(&owner, log_message, nullptr); assert(a);
    assert(decklink_audio_write(a, pcm, 2) == 0);
    fail_audio_write = true; assert(decklink_audio_start(a) < 0);
    assert(decklink_audio_get_state(a, &state) < 0);
    fail_audio_write = false;
    decklink_audio_close(a); assert(enabled && !audio_enabled);
    a = decklink_audio_open(&owner, log_message, nullptr); assert(a);
    assert(decklink_audio_write(a, pcm, 2) == 0 && decklink_audio_start(a) == 0);
    fail_audio_query = true; assert(decklink_audio_get_state(a, &state) < 0);
    fail_audio_query = false;
    decklink_audio_close(a);
    decklink_close(d); clean();
    puts("PASS: shared A/V lifetime, PCM queue, partial/zero writes, pause recovery, seek, drain and SDK audio errors");
}
