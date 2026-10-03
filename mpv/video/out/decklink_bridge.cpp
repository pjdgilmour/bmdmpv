/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "decklink_bridge.h"

#include <DeckLinkAPI.h>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <algorithm>
#include <mutex>
#include <vector>

struct decklink {
    IDeckLink *device = nullptr;
    IDeckLinkOutput *output = nullptr;
    IDeckLinkConfiguration *config = nullptr;
    IDeckLinkMutableVideoFrame *frame = nullptr;
    IDeckLinkVideoBuffer *buffer = nullptr;
    decklink_log_fn log;
    void *opaque;
    int width = 0, height = 0, row_bytes = 0;
    double fps = 0;
    bool enabled = false;
    unsigned long long displayed = 0;
    std::mutex mutex;
    void *owner = nullptr;
    bool video_attached = true;
    bool audio_attached = false;
};

// Registry lock protects attachment/lifetime only. Device lock serializes SDK
// calls on the VO and AO threads. Always acquire registry before device lock.
static std::mutex registry_mutex;
static std::vector<decklink *> sessions;

void decklink_register(decklink *d, void *owner)
{
    std::lock_guard lock(registry_mutex);
    d->owner = owner;
    sessions.push_back(d);
}

template<class T> static void release(T *&obj)
{
    if (obj)
        obj->Release();
    obj = nullptr;
}

static void message(decklink *d, bool error, const char *fmt, ...)
    __attribute__((format(printf, 3, 4)));

static void message(decklink *d, bool error, const char *fmt, ...)
{
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    d->log(d->opaque, error, buf);
}

static bool check(decklink *d, HRESULT hr, const char *operation)
{
    if (hr == S_OK)
        return true;
    message(d, true, "%s failed (HRESULT 0x%08x).", operation, unsigned(hr));
    return false;
}

static bool supported(IDeckLinkOutput *out, IDeckLinkDisplayMode *mode)
{
    bool ok = false;
    BMDDisplayMode actual = bmdModeUnknown;
    return mode->GetFieldDominance() == bmdProgressiveFrame &&
        out->DoesSupportVideoMode(bmdVideoConnectionHDMI, mode->GetDisplayMode(),
            bmdFormat8BitYUV, bmdNoVideoOutputConversion,
            bmdSupportedVideoModeDefault, &actual, &ok) == S_OK && ok &&
        actual == mode->GetDisplayMode();
}

static void mode_code(BMDDisplayMode mode, char code[5])
{
    for (int i = 0; i < 4; ++i)
        code[i] = (uint32_t(mode) >> (24 - 8 * i)) & 0xff;
    code[4] = 0;
}

int decklink_list(decklink_log_fn log, void *opaque)
{
    decklink d;
    d.log = log;
    d.opaque = opaque;
    auto *it = CreateDeckLinkIteratorInstance();
    if (!it) {
        message(&d, true, "Cannot load DeckLink driver. Install compatible Desktop Video (SDK 16.0). ");
        return -1;
    }
    IDeckLink *device = nullptr;
    int count = 0;
    while (it->Next(&device) == S_OK) {
        const char *name = nullptr;
        device->GetDisplayName(&name);
        message(&d, false, "Device %d: %s", count++, name ? name : "(unnamed)");
        free(const_cast<char *>(name));
        IDeckLinkOutput *out = nullptr;
        if (device->QueryInterface(IID_IDeckLinkOutput, (void **)&out) == S_OK) {
            IDeckLinkDisplayModeIterator *modes = nullptr;
            if (out->GetDisplayModeIterator(&modes) == S_OK) {
                IDeckLinkDisplayMode *mode = nullptr;
                while (modes->Next(&mode) == S_OK) {
                    BMDTimeValue duration = 0;
                    BMDTimeScale scale = 0;
                    if (supported(out, mode) && mode->GetFrameRate(&duration, &scale) == S_OK && duration > 0) {
                        char code[5];
                        mode_code(mode->GetDisplayMode(), code);
                        name = nullptr;
                        mode->GetName(&name);
                        message(&d, false, "  %s  %ldx%ld  %.6f fps  %s", code,
                                mode->GetWidth(), mode->GetHeight(), double(scale) / duration,
                                name ? name : "");
                        free(const_cast<char *>(name));
                    }
                    release(mode);
                }
                release(modes);
            }
            release(out);
        } else {
            message(&d, false, "  No compatible output interface (capture-only or older driver).");
        }
        release(device);
    }
    release(it);
    if (!count)
        message(&d, true, "No DeckLink devices visible. Check driver, permissions and /dev/blackmagic.");
    return count ? 0 : -1;
}

static void destroy(decklink *d)
{
    if (!d)
        return;
    if (d->enabled) {
        check(d, d->output->DisableVideoOutput(), "DisableVideoOutput");
        message(d, false, "Displayed %llu video frames.", d->displayed);
    }
    release(d->buffer);
    release(d->frame);
    // Configuration changes are temporary until this interface is released.
    // Do not write the GetInt result back: it is a bitmask, whereas SetInt
    // accepts a single connection, not a mask (SDK sections 2.5.17 and 3.18).
    release(d->config);
    release(d->output);
    release(d->device);
    delete d;
}

void decklink_close(decklink *d)
{
    if (!d)
        return;
    std::lock_guard lock(registry_mutex);
    sessions.erase(std::remove(sessions.begin(), sessions.end(), d), sessions.end());
    d->video_attached = false;
    if (!d->audio_attached)
        destroy(d);
    // Otherwise the AO retains the device (including the video clock) until
    // its own teardown. It must not use the old VO log callback after this.
}

decklink *decklink_open(int device_index, const char *mode_name,
                        decklink_log_fn log, void *opaque)
{
    auto *d = new (std::nothrow) decklink;
    if (!d)
        return nullptr;
    d->log = log;
    d->opaque = opaque;
    auto fail = [&]() -> decklink * { decklink_close(d); return nullptr; };
    if (device_index < 0 || !mode_name || strlen(mode_name) != 4) {
        message(d, true, "Select a device index and a four-character mode code (e.g. Hp30).");
        return fail();
    }
    auto *it = CreateDeckLinkIteratorInstance();
    if (!it) {
        message(d, true, "Cannot load DeckLink driver; Desktop Video compatible with SDK 16.0 is required.");
        return fail();
    }
    for (int i = 0; i <= device_index; ++i) {
        release(d->device);
        if (it->Next(&d->device) != S_OK)
            break;
    }
    release(it);
    if (!d->device) {
        message(d, true, "Device %d not found. Check driver, permissions and device index.", device_index);
        return fail();
    }
    if (!check(d, d->device->QueryInterface(IID_IDeckLinkOutput, (void **)&d->output),
               "Query output interface (requires compatible Desktop Video)"))
        return fail();

    uint32_t id = 0;
    for (int i = 0; i < 4; ++i)
        id = (id << 8) | uint8_t(mode_name[i]);
    IDeckLinkDisplayMode *mode = nullptr;
    if (!check(d, d->output->GetDisplayMode(BMDDisplayMode(id), &mode), "GetDisplayMode"))
        return fail();
    BMDTimeValue duration = 0;
    BMDTimeScale scale = 0;
    bool valid = supported(d->output, mode) &&
                 mode->GetFrameRate(&duration, &scale) == S_OK && duration > 0 && scale > 0;
    d->width = mode->GetWidth();
    d->height = mode->GetHeight();
    release(mode);
    if (!valid || d->width <= 0 || d->height <= 0 || d->width % 2) {
        message(d, true, "Mode '%s' does not support progressive HDMI output in 8-bit YUV.", mode_name);
        return fail();
    }
    d->fps = double(scale) / duration;
    int64_t connections = 0;
    if (!check(d, d->device->QueryInterface(IID_IDeckLinkConfiguration, (void **)&d->config),
               "Query configuration interface") ||
        !check(d, d->config->GetInt(bmdDeckLinkConfigVideoOutputConnection, &connections),
               "Get output connection"))
        return fail();
    if (!(connections & bmdVideoConnectionHDMI)) {
        if (!check(d, d->config->SetInt(bmdDeckLinkConfigVideoOutputConnection,
                                      bmdVideoConnectionHDMI), "Select HDMI output"))
            return fail();
    }
    if (!check(d, d->output->EnableVideoOutput(BMDDisplayMode(id), bmdVideoOutputFlagDefault),
               "EnableVideoOutput (close Resolve or other applications using this device)"))
        return fail();
    d->enabled = true;
    if (!check(d, d->output->RowBytesForPixelFormat(bmdFormat8BitYUV, d->width, &d->row_bytes),
               "RowBytesForPixelFormat") || d->row_bytes < d->width * 2 ||
        !check(d, d->output->CreateVideoFrame(d->width, d->height, d->row_bytes,
                     bmdFormat8BitYUV, bmdFrameFlagDefault, &d->frame), "CreateVideoFrame") ||
        !check(d, d->frame->QueryInterface(IID_IDeckLinkVideoBuffer, (void **)&d->buffer),
               "Query video buffer"))
        return fail();
    message(d, false, "HDMI device %d: %s, %dx%d, %.6f fps, UYVY 8-bit.",
            device_index, mode_name, d->width, d->height, d->fps);
    return d;
}

void decklink_get_mode(decklink *d, int *width, int *height, double *fps)
{
    *width = d->width;
    *height = d->height;
    *fps = d->fps;
}

int decklink_display(decklink *d, const uint8_t *uyvy, ptrdiff_t stride)
{
    if (!d || !uyvy || stride < d->width * 2)
        return -1;
    std::lock_guard lock(d->mutex);
    if (!check(d, d->buffer->StartAccess(bmdBufferAccessWrite), "StartAccess"))
        return -1;
    void *bytes = nullptr;
    bool ok = check(d, d->buffer->GetBytes(&bytes), "GetBytes") && bytes;
    if (ok) {
        for (int y = 0; y < d->height; ++y)
            memcpy(static_cast<uint8_t *>(bytes) + size_t(y) * d->row_bytes,
                   uyvy + y * stride, d->width * 2);
    }
    // Every successful StartAccess must be balanced, even if GetBytes fails.
    bool ended = check(d, d->buffer->EndAccess(bmdBufferAccessWrite), "EndAccess");
    if (!ok || !ended)
        return -1;
    if (!check(d, d->output->DisplayVideoFrameSync(d->frame), "DisplayVideoFrameSync"))
        return -1;
    ++d->displayed;
    return 0;
}

struct decklink_audio {
    decklink *device;
    decklink_log_fn log;
    void *opaque;
    // Mirror all unplayed frames, including frames in the hardware queue.
    // This is what allows pause to flush the device without losing samples.
    int16_t pcm[DECKLINK_AUDIO_CAPACITY * 2];
    int count = 0;
    uint32_t submitted = 0;
    bool running = false, paused = false, failed = false;
    bool hardware_enabled = false;
    unsigned long long written = 0;
};

static bool audio_check(decklink_audio *a, HRESULT hr, const char *operation)
{
    if (hr == S_OK)
        return true;
    if (!a->failed) {
        char msg[256];
        snprintf(msg, sizeof(msg), "%s failed (HRESULT 0x%08x).", operation, unsigned(hr));
        a->log(a->opaque, true, msg);
    }
    a->failed = true;
    return false;
}

decklink_audio *decklink_audio_open(void *owner, decklink_log_fn log, void *opaque)
{
    std::lock_guard registry_lock(registry_mutex);
    decklink *d = nullptr;
    for (auto *candidate : sessions) {
        if (candidate->owner == owner && candidate->video_attached) {
            d = candidate;
            break;
        }
    }
    if (!d || d->audio_attached) {
        log(opaque, true, "DeckLink audio requires an active, unused --vo=decklink session in this player.");
        return nullptr;
    }
    auto *a = new (std::nothrow) decklink_audio;
    if (!a)
        return nullptr;
    a->device = d;
    a->log = log;
    a->opaque = opaque;
    std::lock_guard device_lock(d->mutex);
    if (!audio_check(a, d->output->EnableAudioOutput(bmdAudioSampleRate48kHz,
                     bmdAudioSampleType16bitInteger, 2, bmdAudioOutputStreamContinuous),
                     "EnableAudioOutput")) {
        delete a;
        return nullptr;
    }
    d->audio_attached = true;
    a->hardware_enabled = true;
    log(opaque, false, "HDMI audio: stereo PCM, 48000 Hz, 16-bit (same device as video).");
    return a;
}

// Called under the device lock. Use the hardware queue, not a software timer,
// to determine how many samples have actually left the device buffer.
static bool audio_update(decklink_audio *a)
{
    if (a->failed)
        return false;
    // Desktop Video may not have created its queue until the first write.
    if (!a->submitted)
        return true;
    uint32_t queued = 0;
    if (!audio_check(a, a->device->output->GetBufferedAudioSampleFrameCount(&queued),
                     "GetBufferedAudioSampleFrameCount"))
        return false;
    if (queued > a->submitted) {
        char msg[192];
        snprintf(msg, sizeof(msg), "Audio queue accounting failed: device=%u, submitted=%u, retained=%d.",
                 queued, a->submitted, a->count);
        a->log(a->opaque, true, msg);
        a->failed = true;
        return false;
    }
    int consumed = a->submitted - queued;
    a->count -= consumed;
    memmove(a->pcm, a->pcm + consumed * 2, a->count * 2 * sizeof(int16_t));
    a->submitted = queued;
    // Re-arm the synchronous audio engine after drain/underrun. Reusing its
    // old stream after a gap can leave stale counts on the tested driver.
    if (!a->count && a->hardware_enabled && a->running) {
        if (!audio_check(a, a->device->output->DisableAudioOutput(), "DisableAudioOutput"))
            return false;
        a->hardware_enabled = false;
    }
    return true;
}

static bool audio_pump(decklink_audio *a)
{
    if (!a->running || a->paused || a->count == int(a->submitted))
        return !a->failed;
    if (!a->hardware_enabled) {
        if (!audio_check(a, a->device->output->EnableAudioOutput(bmdAudioSampleRate48kHz,
                         bmdAudioSampleType16bitInteger, 2, bmdAudioOutputStreamContinuous),
                         "EnableAudioOutput"))
            return false;
        a->hardware_enabled = true;
    }
    uint32_t written = 0;
    uint32_t pending = a->count - a->submitted;
    if (!audio_check(a, a->device->output->WriteAudioSamplesSync(
                         a->pcm + a->submitted * 2, pending, &written), "WriteAudioSamplesSync") ||
        !audio_check(a, written <= pending ? S_OK : E_FAIL, "Audio write accounting"))
        return false;
    // Partial and zero writes retain the unwritten tail for the next poll.
    a->submitted += written;
    a->written += written;
    return true;
}

int decklink_audio_write(decklink_audio *a, const int16_t *pcm, int frames)
{
    std::lock_guard lock(a->device->mutex);
    if (!audio_update(a) || !pcm || frames < 0 || frames > DECKLINK_AUDIO_CAPACITY - a->count)
        return -1;
    memcpy(a->pcm + a->count * 2, pcm, frames * 2 * sizeof(int16_t));
    a->count += frames;
    return audio_pump(a) ? 0 : -1;
}

int decklink_audio_get_state(decklink_audio *a, decklink_audio_state *state)
{
    std::lock_guard lock(a->device->mutex);
    *state = {};
    if (!audio_update(a) || !audio_pump(a))
        return -1;
    state->queued = a->count;
    state->playing = a->running && a->count > 0;
    return 0;
}

int decklink_audio_start(decklink_audio *a)
{
    std::lock_guard lock(a->device->mutex);
    a->running = true;
    a->paused = false;
    return !a->failed && audio_pump(a) ? 0 : -1;
}

int decklink_audio_pause(decklink_audio *a, bool paused)
{
    std::lock_guard lock(a->device->mutex);
    if (!audio_update(a))
        return -1;
    if (paused && !a->paused) {
        // FlushBufferedAudioSamples does not reset synchronous output's queue
        // reliably on Desktop Video 16.4. Disable/re-enable audio instead;
        // keep video active and retain unplayed PCM in our software mirror.
        if (a->hardware_enabled && !audio_check(a, a->device->output->DisableAudioOutput(), "DisableAudioOutput"))
            return -1;
        a->hardware_enabled = false;
        a->submitted = 0;
    }
    a->paused = paused;
    return audio_pump(a) ? 0 : -1;
}

int decklink_audio_reset(decklink_audio *a)
{
    std::lock_guard lock(a->device->mutex);
    bool ok = !a->hardware_enabled || audio_check(a, a->device->output->DisableAudioOutput(), "DisableAudioOutput");
    if (ok)
        a->hardware_enabled = false;
    a->count = 0;
    a->submitted = 0;
    a->running = a->paused = false;
    return ok ? 0 : -1;
}

void decklink_audio_close(decklink_audio *a)
{
    if (!a)
        return;
    std::lock_guard registry_lock(registry_mutex);
    auto *d = a->device;
    {
        std::lock_guard device_lock(d->mutex);
        if (a->hardware_enabled)
            audio_check(a, d->output->DisableAudioOutput(), "DisableAudioOutput");
    }
    char msg[128];
    snprintf(msg, sizeof(msg), "Submitted %llu audio sample frames to HDMI.", a->written);
    a->log(a->opaque, false, msg);
    d->audio_attached = false;
    if (!d->video_attached) {
        d->log = a->log;
        d->opaque = a->opaque;
        destroy(d);
    }
    delete a;
}
