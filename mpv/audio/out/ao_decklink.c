/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "audio/format.h"
#include "common/msg.h"
#include "internal.h"
#include "video/out/decklink_bridge.h"

struct priv {
    struct decklink_audio *audio;
    bool reload_requested;
};

static void log_message(void *opaque, bool error, const char *message)
{
    struct ao *ao = opaque;
    mp_msg(ao->log, error ? MSGL_ERR : MSGL_INFO, "%s\n", message);
    struct priv *p = ao->priv;
    if (error && ao->driver_initialized && !p->reload_requested) {
        p->reload_requested = true;
        ao_request_reload(ao);
    }
}

static int init(struct ao *ao)
{
    struct priv *p = ao->priv;
    p->audio = decklink_audio_open(ao->global, log_message, ao);
    if (!p->audio)
        return -1;
    ao->samplerate = 48000;
    ao->format = AF_FORMAT_S16;
    mp_chmap_from_channels(&ao->channels, 2);
    ao->device_buffer = DECKLINK_AUDIO_CAPACITY;
    return 0;
}

static void uninit(struct ao *ao)
{
    struct priv *p = ao->priv;
    p->reload_requested = true;
    decklink_audio_close(p->audio);
}

static void reset(struct ao *ao)
{
    struct priv *p = ao->priv;
    decklink_audio_reset(p->audio);
}

static void start(struct ao *ao)
{
    struct priv *p = ao->priv;
    decklink_audio_start(p->audio);
}

static bool set_pause(struct ao *ao, bool paused)
{
    struct priv *p = ao->priv;
    return decklink_audio_pause(p->audio, paused) == 0;
}

static bool audio_write(struct ao *ao, void **data, int frames)
{
    struct priv *p = ao->priv;
    return decklink_audio_write(p->audio, data[0], frames) == 0;
}

static void get_state(struct ao *ao, struct mp_pcm_state *state)
{
    struct priv *p = ao->priv;
    struct decklink_audio_state s;
    *state = (struct mp_pcm_state){0};
    if (decklink_audio_get_state(p->audio, &s) < 0)
        return;
    state->queued_samples = s.queued;
    state->free_samples = (DECKLINK_AUDIO_CAPACITY - s.queued) / 128 * 128;
    state->delay = s.queued / 48000.0;
    state->playing = s.playing;
}

const struct ao_driver audio_out_decklink = {
    .name = "decklink",
    .description = "Blackmagic HDMI PCM audio (requires vo=decklink)",
    .init = init,
    .uninit = uninit,
    .reset = reset,
    .start = start,
    .set_pause = set_pause,
    .write = audio_write,
    .get_state = get_state,
    .priv_size = sizeof(struct priv),
};
