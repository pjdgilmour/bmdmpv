/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "video/out/decklink_bridge.h"
#include <cstdio>

static void log_message(void *, bool error, const char *message)
{
    fprintf(error ? stderr : stdout, "%s\n", message);
}

int main()
{
    return decklink_list(log_message, nullptr) == 0 ? 0 : 1;
}
