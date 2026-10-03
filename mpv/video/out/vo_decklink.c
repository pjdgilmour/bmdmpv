/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include <string.h>

#include "common/msg.h"
#include "options/m_option.h"
#include "sub/osd.h"
#include "video/mp_image.h"
#include "video/sws_utils.h"
#include "vo.h"
#include "decklink_bridge.h"

struct priv {
    int device;
    char *mode;
    struct decklink *decklink;
    int width, height;
    double fps;
    struct mp_sws_context *sws;
    struct mp_image *image;
    struct mp_rect src, dst;
    struct mp_osd_res osd;
    bool ready, failed;
};

static void decklink_log(void *opaque, bool error, const char *message)
{
    struct vo *vo = opaque;
    mp_msg(vo->log, error ? MSGL_ERR : MSGL_INFO, "%s\n", message);
}

static int preinit(struct vo *vo)
{
    struct priv *p = vo->priv;
    if (!strcmp(p->mode, "help")) {
        decklink_list(decklink_log, vo);
        return -1;
    }
    p->decklink = decklink_open(p->device, p->mode, decklink_log, vo);
    if (!p->decklink)
        return -1;
    decklink_get_mode(p->decklink, &p->width, &p->height, &p->fps);
    p->sws = mp_sws_alloc(vo);
    p->sws->log = vo->log;
    mp_sws_enable_cmdline_opts(p->sws, vo->global);
    decklink_register(p->decklink, vo->global);
    return 0;
}

static int query_format(struct vo *vo, int format)
{
    struct priv *p = vo->priv;
    return mp_sws_supports_formats(p->sws, IMGFMT_UYVY, format);
}

static int reconfig(struct vo *vo, struct mp_image_params *params)
{
    struct priv *p = vo->priv;
    p->ready = false;
    // Software scaling does not perform HDR tone mapping or gamut conversion.
    if (pl_color_space_is_hdr(&params->color) ||
        params->color.primaries == PL_COLOR_PRIM_BT_2020 ||
        params->repr.sys == PL_COLOR_SYSTEM_DOLBYVISION) {
        MP_ERR(vo, "This output supports SDR only; convert HDR/wide-gamut content to SDR first.\n");
        return -1;
    }
    vo->dwidth = p->width;
    vo->dheight = p->height;
    vo_get_src_dst_rects(vo, &p->src, &p->dst, &p->osd);
    // UYVY contains pairs of pixels. Align both ends, including pillarbox bars.
    p->dst.x0 = MP_ALIGN_DOWN(p->dst.x0, 2);
    p->dst.x1 = MP_ALIGN_DOWN(p->dst.x1, 2);
    if (mp_rect_w(p->dst) < 2 || mp_rect_h(p->dst) < 1)
        return -1;

    talloc_free(p->image);
    p->image = mp_image_alloc(IMGFMT_UYVY, p->width, p->height);
    if (!p->image)
        return -1;
    struct mp_image_params target = {
        .imgfmt = IMGFMT_UYVY,
        .w = p->width, .h = p->height,
        .p_w = 1, .p_h = 1,
        .repr = {
            .sys = PL_COLOR_SYSTEM_BT_709,
            .levels = PL_COLOR_LEVELS_LIMITED,
        },
        .color = {
            .primaries = PL_COLOR_PRIM_BT_709,
            .transfer = PL_COLOR_TRC_BT_1886,
        },
    };
    mp_image_params_guess_csp(&target);
    mp_image_set_params(p->image, &target);
    p->sws->src = *params;
    p->sws->src.w = mp_rect_w(p->src);
    p->sws->src.h = mp_rect_h(p->src);
    p->sws->dst = target;
    p->sws->dst.w = mp_rect_w(p->dst);
    p->sws->dst.h = mp_rect_h(p->dst);
    if (mp_sws_reinit(p->sws) < 0)
        return -1;
    vo->want_redraw = true;
    return 0;
}

static bool draw_frame(struct vo *vo, struct vo_frame *frame)
{
    struct priv *p = vo->priv;
    p->ready = false;
    if (p->failed || !p->image)
        return false;
    mp_image_clear(p->image, 0, 0, p->width, p->height);
    double pts = 0;
    if (frame->current) {
        struct mp_image src = *frame->current;
        struct mp_rect crop = p->src;
        crop.x0 = MP_ALIGN_DOWN(crop.x0, src.fmt.align_x);
        crop.y0 = MP_ALIGN_DOWN(crop.y0, src.fmt.align_y);
        mp_image_crop_rc(&src, crop);
        struct mp_image dst = *p->image;
        mp_image_crop_rc(&dst, p->dst);
        if (mp_sws_scale(p->sws, &dst, &src) < 0)
            return false;
        pts = frame->current->pts;
    }
    osd_draw_on_image(vo->osd, p->osd, pts, 0, p->image);
    p->ready = true;
    return true;
}

static void flip_page(struct vo *vo)
{
    struct priv *p = vo->priv;
    if (p->ready && decklink_display(p->decklink, p->image->planes[0],
                                   p->image->stride[0]) < 0) {
        p->failed = true;
        MP_ERR(vo, "DeckLink output failed; restart playback after checking the device.\n");
    }
    p->ready = false;
}

static int control(struct vo *vo, uint32_t request, void *data)
{
    struct priv *p = vo->priv;
    switch (request) {
    case VOCTRL_GET_DISPLAY_FPS:
        *(double *)data = p->fps;
        return VO_TRUE;
    case VOCTRL_GET_DISPLAY_RES:
        ((int *)data)[0] = p->width;
        ((int *)data)[1] = p->height;
        return VO_TRUE;
    case VOCTRL_RESET:
        p->ready = false;
        return VO_TRUE;
    case VOCTRL_SCREENSHOT_WIN:
        *(struct mp_image **)data = p->image ? mp_image_new_copy(p->image) : NULL;
        return VO_TRUE;
    case VOCTRL_SET_PANSCAN:
    case VOCTRL_VO_OPTS_CHANGED:
        if (vo->params)
            return reconfig(vo, vo->params) < 0 ? VO_ERROR : VO_TRUE;
        return VO_TRUE;
    }
    return VO_NOTIMPL;
}

static void uninit(struct vo *vo)
{
    struct priv *p = vo->priv;
    talloc_free(p->image);
    decklink_close(p->decklink);
}

#define OPT_BASE_STRUCT struct priv
const struct vo_driver video_out_decklink = {
    .description = "Blackmagic DeckLink/Intensity HDMI (SDR, synchronous video)",
    .name = "decklink",
    .preinit = preinit,
    .query_format = query_format,
    .reconfig = reconfig,
    .control = control,
    .draw_frame = draw_frame,
    .flip_page = flip_page,
    .uninit = uninit,
    .priv_size = sizeof(struct priv),
    .priv_defaults = &(const struct priv) {.mode = "Hp30"},
    .options = (const struct m_option[]) {
        {"device", OPT_INT(device), M_RANGE(0, 255)},
        {"mode", OPT_STRING(mode)},
        {0},
    },
    .options_prefix = "vo-decklink",
};
