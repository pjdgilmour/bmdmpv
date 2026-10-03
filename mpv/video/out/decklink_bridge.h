/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef MP_DECKLINK_BRIDGE_H
#define MP_DECKLINK_BRIDGE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

struct decklink;
typedef void (*decklink_log_fn)(void *opaque, bool error, const char *message);

// Device indices include all devices, including capture-only devices.
// Modes are four-character SDK identifiers (e.g. Hp30), not list indices.
struct decklink *decklink_open(int device, const char *mode,
                              decklink_log_fn log, void *opaque);
int decklink_list(decklink_log_fn log, void *opaque);
void decklink_close(struct decklink *ctx);
void decklink_get_mode(struct decklink *ctx, int *width, int *height, double *fps);
int decklink_display(struct decklink *ctx, const uint8_t *uyvy, ptrdiff_t stride);

// Publish a VO session for the AO belonging to the same mpv instance.
void decklink_register(struct decklink *ctx, void *owner);

#define DECKLINK_AUDIO_CAPACITY 9600
struct decklink_audio;
struct decklink_audio_state {
    int queued;
    bool playing;
};
// Audio uses the active VO's device, mode and lifetime. Stereo S16, 48000 Hz.
struct decklink_audio *decklink_audio_open(void *owner, decklink_log_fn log, void *opaque);
void decklink_audio_close(struct decklink_audio *audio);
int decklink_audio_write(struct decklink_audio *audio, const int16_t *pcm, int frames);
int decklink_audio_get_state(struct decklink_audio *audio, struct decklink_audio_state *state);
int decklink_audio_start(struct decklink_audio *audio);
int decklink_audio_pause(struct decklink_audio *audio, bool paused);
int decklink_audio_reset(struct decklink_audio *audio);

#ifdef __cplusplus
}
#endif
#endif
