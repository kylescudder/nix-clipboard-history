/* Keep a pointer present in headless Sway so GTK can bind wl_pointer before
 * one-shot wlrctl commands send events. No pointer requests are synthesized here. */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>
#include "pointer-client.h"

static struct zwlr_virtual_pointer_manager_v1 *manager;

static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version) {
    if (strcmp(interface, zwlr_virtual_pointer_manager_v1_interface.name) == 0)
        manager = wl_registry_bind(registry, name,
                                   &zwlr_virtual_pointer_manager_v1_interface, 1);
}

static void removed(void *data, struct wl_registry *registry, uint32_t name) {}
static const struct wl_registry_listener listener = {global, removed};

int main(int argc, char **argv) {
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return 1;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &listener, NULL);
    if (wl_display_roundtrip(display) < 0 || !manager) return 1;
    zwlr_virtual_pointer_manager_v1_create_virtual_pointer(manager, NULL);
    if (wl_display_roundtrip(display) < 0) return 1;
    FILE *ready = fopen(argv[1], "w");
    if (!ready) return 1;
    fclose(ready);
    while (wl_display_dispatch(display) >= 0) {}
    return 0;
}
